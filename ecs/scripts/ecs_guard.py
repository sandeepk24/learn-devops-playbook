#!/usr/bin/env python3
"""ecs_guard.py - health gate and watchdog for ECS services.

Two ways to use it:

  Watchdog (scheduled job, every 15 minutes or so):
      ecs_guard.py --cluster prod --fix

  Post-deploy gate (last step of the deploy pipeline):
      ecs_guard.py --cluster prod --services api \
          --expect-task-def api:42 --wait 600

It reads ECS and the load balancer, prints one line per finding, and exits
non-zero when something is broken. It never changes service settings. The only
write it can make is --fix, which forces a new deployment when a service is
running fewer tasks than desired. Settings drift is reported, not corrected,
so Terraform stays the source of truth.

Exit codes: 0 = healthy, 1 = at least one FAIL (or a WARN with --strict).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

import boto3

OK, WARN, FAIL = "OK", "WARN", "FAIL"

# A stop is "normal" when ECS did it on purpose during a deploy or scale-in.
NORMAL_STOP = re.compile(r"scaling activity|deployment", re.I)
BAD_STOP = re.compile(r"failed|error|outofmemory|cannotpull|essential container", re.I)
# 143 is SIGTERM. Containers exit with it on every normal stop.
OK_EXIT_CODES = (0, None, 143)


def get_service(ecs, cluster, name):
    resp = ecs.describe_services(cluster=cluster, services=[name])
    return resp["services"][0] if resp.get("services") else None


def primary_deployment(svc):
    return next((d for d in svc["deployments"] if d["status"] == "PRIMARY"), None)


def is_deploying(svc):
    primary = primary_deployment(svc)
    return len(svc["deployments"]) > 1 or (
        primary is not None and primary.get("rolloutState") == "IN_PROGRESS"
    )


def wait_for_rollout(ecs, cluster, name, timeout, interval=15):
    """Block until the rollout finishes, fails, or the timeout passes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        svc = get_service(ecs, cluster, name)
        if svc is None:
            return
        primary = primary_deployment(svc)
        state = primary.get("rolloutState") if primary else None
        if state == "FAILED":
            return
        settled = len(svc["deployments"]) == 1 and svc["runningCount"] == svc["desiredCount"]
        if settled and state in (None, "COMPLETED"):
            return
        time.sleep(interval)


def task_def_matches(arn, expected):
    # arn:aws:ecs:region:acct:task-definition/api:42  vs  "api:42" or the full arn
    return arn == expected or arn.endswith("/" + expected)


def bad_stopped_tasks(ecs, cluster, name, window_minutes):
    """Tasks that stopped for a bad reason inside the window."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    arns = ecs.list_tasks(
        cluster=cluster, serviceName=name, desiredStatus="STOPPED", maxResults=50
    ).get("taskArns", [])
    if not arns:
        return []
    bad = []
    for t in ecs.describe_tasks(cluster=cluster, tasks=arns)["tasks"]:
        stopped_at = t.get("stoppedAt")
        if stopped_at is None or stopped_at < cutoff:
            continue
        reason = t.get("stoppedReason") or ""
        exit_codes = [c.get("exitCode") for c in t.get("containers", [])]
        if NORMAL_STOP.search(reason):
            continue
        if any(code not in OK_EXIT_CODES for code in exit_codes) or BAD_STOP.search(reason):
            bad.append(reason[:90] or f"exit codes {exit_codes}")
    return bad


def check_service(ecs, elbv2, cluster, name, args):
    """Return a list of (level, message) for one service."""
    svc = get_service(ecs, cluster, name)
    if svc is None:
        return [(FAIL, "service not found")]

    found = []
    if svc["status"] != "ACTIVE":
        found.append((FAIL, f"status is {svc['status']}"))

    desired, running = svc["desiredCount"], svc["runningCount"]
    has_lb = bool(svc.get("loadBalancers"))
    deploying = is_deploying(svc)
    primary = primary_deployment(svc)
    rollout = primary.get("rolloutState") if primary else None

    # Rollout state and rollback detection
    if rollout == "FAILED":
        reason = primary.get("rolloutStateReason", "no reason given")
        found.append((FAIL, f"deployment failed: {reason}"))
    elif deploying:
        found.append((WARN, "deployment in progress"))
    if args.expect_task_def and primary:
        if not task_def_matches(primary["taskDefinition"], args.expect_task_def):
            found.append((FAIL, f"serving {primary['taskDefinition'].split('/')[-1]}, "
                                f"expected {args.expect_task_def} (rolled back?)"))

    # Task count
    if desired > 0 and running < desired and not deploying:
        found.append((FAIL, f"running {running} of {desired} tasks"))
        if args.fix and rollout != "FAILED":
            ecs.update_service(cluster=cluster, service=name, forceNewDeployment=True)
            found.append((WARN, "forced a new deployment"))

    # Settings drift. Reported only; fix it in Terraform.
    dc = svc.get("deploymentConfiguration", {})
    if has_lb and dc.get("minimumHealthyPercent", 100) < 100:
        found.append((WARN, f"minimumHealthyPercent is {dc['minimumHealthyPercent']}, expected 100"))
    if not dc.get("deploymentCircuitBreaker", {}).get("enable"):
        found.append((WARN, "deployment circuit breaker is off"))
    if desired < 3:
        found.append((WARN, f"desiredCount is {desired}, fewer than 3"))
    if has_lb and not svc.get("healthCheckGracePeriodSeconds"):
        found.append((WARN, "healthCheckGracePeriodSeconds is 0"))

    # Load balancer targets
    for lb in svc.get("loadBalancers", []):
        arn = lb.get("targetGroupArn")
        if not arn:
            continue
        tg = arn.split("/")[1]
        states = Counter(
            t["TargetHealth"]["State"]
            for t in elbv2.describe_target_health(TargetGroupArn=arn)["TargetHealthDescriptions"]
        )
        if desired > 0 and states.get("healthy", 0) == 0:
            found.append((FAIL, f"target group {tg} has no healthy targets {dict(states)}"))
            continue
        ignore = {"healthy", "draining"} | ({"initial"} if deploying else set())
        unhealthy = {k: v for k, v in states.items() if k not in ignore}
        if unhealthy:
            found.append((WARN, f"target group {tg} has unhealthy targets {unhealthy}"))

    # Tasks that keep dying
    bad = bad_stopped_tasks(ecs, cluster, name, args.stopped_window)
    if len(bad) >= args.stopped_threshold:
        top, count = Counter(bad).most_common(1)[0]
        found.append((WARN, f"{len(bad)} tasks stopped badly in {args.stopped_window}m, "
                            f"most common: {top} ({count}x)"))

    return found or [(OK, f"{running}/{desired} running")]


def list_all_services(ecs, cluster):
    names = []
    for page in ecs.get_paginator("list_services").paginate(cluster=cluster):
        names += [a.split("/")[-1] for a in page["serviceArns"]]
    return names


def notify(text):
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return
    req = urllib.request.Request(
        url, data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except OSError as exc:
        print(f"could not post to Slack: {exc}", file=sys.stderr)


def write_summary(cluster, results):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a") as fh:
        fh.write(f"### ECS guard: {cluster}\n\n| Service | Level | Finding |\n|---|---|---|\n")
        for svc, level, msg in results:
            fh.write(f"| {svc} | {level} | {msg} |\n")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Health gate and watchdog for ECS services.")
    p.add_argument("--cluster", required=True)
    p.add_argument("--services", help="comma separated; default is every service in the cluster")
    p.add_argument("--region", default=os.environ.get("AWS_REGION"))
    p.add_argument("--expect-task-def", help="family:revision the service must be serving")
    p.add_argument("--wait", type=int, default=0, metavar="SECONDS",
                   help="wait for the rollout to settle before checking")
    p.add_argument("--fix", action="store_true",
                   help="force a new deployment when running < desired")
    p.add_argument("--strict", action="store_true", help="treat WARN as a failure")
    p.add_argument("--stopped-window", type=int, default=30, metavar="MINUTES")
    p.add_argument("--stopped-threshold", type=int, default=3, metavar="TASKS")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    session = boto3.session.Session(region_name=args.region)
    ecs, elbv2 = session.client("ecs"), session.client("elbv2")

    names = args.services.split(",") if args.services else list_all_services(ecs, args.cluster)
    if args.expect_task_def and len(names) != 1:
        sys.exit("--expect-task-def needs exactly one service in --services")

    results = []
    for name in names:
        if args.wait:
            wait_for_rollout(ecs, args.cluster, name, args.wait)
        for level, msg in check_service(ecs, elbv2, args.cluster, name, args):
            print(f"[{level:<4}] {name}: {msg}")
            results.append((name, level, msg))

    write_summary(args.cluster, results)
    failures = [r for r in results if r[1] == FAIL]
    warnings = [r for r in results if r[1] == WARN]
    if failures:
        notify(f"ECS guard failed on {args.cluster}:\n" + "\n".join(f"{s}: {m}" for s, _, m in failures))
    return 1 if failures or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
