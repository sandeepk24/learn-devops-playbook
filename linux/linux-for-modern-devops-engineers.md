# Linux for DevOps Engineers

Ask ten DevOps engineers what "knowing Linux" actually means and you'll get ten different answers. Some will point to shell scripting. Others will talk about systemd unit files, or cgroups, or the fact that every container you've ever deployed is, underneath all the YAML, just a Linux process wearing a costume. They're all a little bit right, and that's kind of the problem — Linux isn't one skill, it's a stack of them, and most engineers pick up just enough to get by until something breaks at 3 AM and forces them to go deeper.

This article is about that deeper layer. Not the "here are fifty commands you should memorize" version of Linux content — you can find that anywhere — but the parts that actually explain *why* your pods keep getting OOMKilled, why a service that works fine locally falls over in production, and why "just restart it" is sometimes the right answer and sometimes a way of postponing a much worse problem.

## Why Linux Fundamentals Still Matter in a Kubernetes World

There's a tempting narrative that Kubernetes and managed cloud services have abstracted Linux away. You write a Deployment manifest, you set some resource limits, and the orchestrator handles the rest. In practice, that abstraction leaks constantly. Kubernetes doesn't invent new primitives — it orchestrates the same namespaces, cgroups, and process trees that have existed in the kernel for years. When a container gets killed for exceeding memory limits, that's the kernel's OOM killer doing its job, and Kubernetes is just relaying the message.

So when something goes sideways — and it will — you're not debugging Kubernetes. You're debugging Linux with Kubernetes as an extra layer of indirection. Engineers who understand what's actually happening underneath tend to fix things in minutes. Everyone else ends up restarting pods and hoping.

## The Process Model: Everything Is a Tree

Every process on a Linux system has a parent, except PID 1, which is the ancestor of everything. This sounds academic until you're troubleshooting a zombie process problem in a container and realize the reason it's happening is that your application isn't PID 1 — some init wrapper is, and it's not reaping child processes correctly.

```
PID 1 (init/systemd)
 └── PID 842 (containerd-shim)
      └── PID 850 (your app entrypoint)
           └── PID 851 (worker process, forked)
                └── PID 852 (zombie — parent exited without wait())
```

This is exactly why images like `tini` or `dumb-init` exist, and why you'll see them tucked into so many production Dockerfiles as the entrypoint. They exist purely to do the boring job of reaping zombie children, something PID 1 is supposed to do and your application almost certainly isn't built to handle.

A quick way to see this in action locally:

```python
import subprocess

result = subprocess.run(
    ["ps", "-eo", "pid,ppid,stat,cmd"],
    capture_output=True, text=True
)
for line in result.stdout.splitlines():
    if "Z" in line.split()[2:3]:  # STAT column shows Z for zombie
        print("Zombie found:", line)
```

Nothing fancy — just a reminder that the process table is queryable, scriptable, and worth checking before you assume a memory leak is the culprit.

## Memory: The Part Everyone Gets Wrong

If there's one Linux concept that trips up even senior engineers, it's memory accounting. `free -h` shows you "used" memory that includes buffers and cache, which the kernel will happily reclaim under pressure. New engineers see a number close to 100% and panic. Meanwhile, the actual signal you want — whether the system is under real memory pressure — comes from `available`, not `used`.

Inside a container, this gets murkier still. `cgroup` limits define what your container is allowed to consume, but plenty of language runtimes — older JVMs are the classic offender — don't respect cgroup limits by default and instead read `/proc/meminfo`, which reports the *host's* total memory. That mismatch is how you end up with a Java process configured with a heap size larger than its container's actual memory ceiling, quietly building toward an OOM kill that looks mysterious until you know where to look.

| Symptom | Likely Cause | Where to Check |
|---|---|---|
| Container OOMKilled despite low reported usage | cgroup memory limit hit, cache counted against limit | `cat /sys/fs/cgroup/memory.max` (or v1 equivalent) |
| JVM crashes with OutOfMemoryError under low limits | Heap sized against host memory, not container limit | JVM flags, `-XX:+UseContainerSupport` |
| `free -h` shows high usage but app runs fine | Page cache inflating "used" | Look at `available` column instead |
| Gradual memory growth over days | Possible leak, or unbounded cache/connection pool | `pmap`, heap dumps, or app-level metrics |

None of this is exotic knowledge. It's just not the kind of thing you learn from a Kubernetes tutorial, because Kubernetes tutorials assume the memory model underneath already makes sense to you.

## systemd: Love It or Hate It, You're Using It

Whatever your opinion on systemd's sprawl, it's the init system running under the vast majority of production Linux hosts today, and it's worth actually understanding rather than treating as a black box you `systemctl restart` and walk away from.

A well-written unit file tells you a lot about how a service is expected to behave — whether it restarts on failure, how long it waits before doing so, what it depends on before starting. Here's a fairly typical one for a background worker:

```ini
[Unit]
Description=Background job worker
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
ExecStart=/usr/local/bin/worker --config /etc/worker/config.yaml
Restart=on-failure
RestartSec=5
User=worker
Group=worker

[Install]
WantedBy=multi-user.target
```

The detail people skip past is `Requires=` versus `After=`. `After=` just controls ordering — it doesn't guarantee the dependency is actually running. `Requires=` enforces that the dependency exists and is active, and if it fails, this unit fails with it. Mixing these up is a common reason services start "successfully" against a database connection that isn't actually ready yet, and then spend their first few seconds crash-looping while retry logic catches up.

## Networking Basics That Save You Hours

You don't need to be a network engineer to run production systems, but you do need to be comfortable with a few layers. When a service can't reach another service, the question isn't "is the network broken" — it almost never is. The question is which of about four things is actually wrong: DNS resolution, routing, a firewall rule, or the application not listening on the interface you think it is.

That last one catches people constantly. An app bound to `127.0.0.1` inside a container is invisible to anything outside that container's network namespace, even though `curl localhost:8080` from inside the container works perfectly. The fix is almost always binding to `0.0.0.0`, but the debugging path to get there involves knowing to check `ss -tlnp` or `netstat -tlnp` and actually look at which address the socket is bound to, not just which port.

```bash
# Is anything actually listening, and on which interface?
ss -tlnp | grep 8080

# Can you resolve the service name from inside the pod/container?
nslookup my-service.default.svc.cluster.local

# Is there a route, or does it just look like there should be one?
ip route get 10.0.4.15
```

Three commands, and together they narrow the failure down to a specific layer instead of a vague "networking issue" that gets escalated to whoever owns the VPC.

## File Descriptors and the "Too Many Open Files" Trap

This one deserves its own mention because it's so common and so easy to fix once you know what's happening. Every open file, socket, and pipe consumes a file descriptor, and both the process and the system have limits on how many can be open at once. A connection pool that isn't closing connections properly, or a service under heavy load that opens far more sockets than expected, will eventually hit that ceiling and start throwing `EMFILE` errors that look nothing like a resource limit problem from the application's perspective.

Checking current limits is simple enough:

```bash
ulimit -n                 # soft limit for current shell
cat /proc/<pid>/limits    # hard and soft limits for a running process
ls /proc/<pid>/fd | wc -l # how many are actually open right now
```

Raising the limit is often the quick fix, and sometimes it's the right one. But it's worth pausing before doing that reflexively — a file descriptor leak that gets papered over with a higher ulimit doesn't go away, it just takes longer to show up again, usually during your next traffic spike.

## Bringing It Together

None of this is meant to replace Kubernetes knowledge or cloud platform expertise — those still matter enormously. But there's a reason experienced engineers keep coming back to Linux fundamentals when things get genuinely difficult to debug. Every abstraction you work with — containers, pods, serverless functions — is built on the same handful of kernel primitives: processes, namespaces, cgroups, file descriptors, and the network stack. Understanding those primitives doesn't make the higher layers unnecessary. It makes you much faster at figuring out which layer actually broke.

The next time something fails in a way that doesn't match the error message, it's worth dropping down a level. Check the process tree. Check the actual memory numbers, not just the headline percentage. Check what the socket is really bound to. More often than you'd expect, the answer was sitting there in `/proc` the whole time.

---

*Found this useful? More production-focused DevOps writing like this lives at [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — practical breakdowns, not tutorials.*
