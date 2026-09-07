# Linux for Modern DevOps Engineers

Ask ten DevOps engineers what "knowing Linux" means and you'll get ten different answers. Some say shell scripting. Others bring up systemd unit files, or cgroups, or the fact that every container you've ever deployed is just a Linux process wearing a costume once you strip away the YAML. They're all a little bit right. That's the problem — Linux isn't one skill, it's a pile of skills, and most people learn just enough to get by until something breaks at 3 AM and forces them to dig deeper.

This article is about that deeper layer. Not the "here are fifty commands to memorize" kind of Linux content — you can find that anywhere — but the stuff that explains *why* your pods keep getting OOMKilled, why something that runs fine on your laptop falls over in production, and why "just restart it" is sometimes the right call and sometimes just delaying a bigger problem.

## Why Linux Still Matters When You're Running Kubernetes

It's easy to think Kubernetes and managed cloud services made Linux knowledge optional. You write a Deployment file, set some resource limits, and let the orchestrator handle the rest. In practice, that only goes so far. Kubernetes doesn't invent anything new under the hood — it's managing the same namespaces, cgroups, and process trees the kernel has had for years. When a container gets killed for using too much memory, that's the kernel's OOM killer doing its job. Kubernetes is just the messenger.

So when something breaks, you're not really debugging Kubernetes. You're debugging Linux, with Kubernetes sitting in the middle. Engineers who get this fix things in minutes. Everyone else restarts pods and hopes for the best.

## Every Process Has a Parent — Except One

Every process on Linux has a parent, except PID 1, which is the ancestor of everything else. That sounds like trivia until you're staring at a zombie process inside a container and realize the reason is that your app isn't PID 1 — some init wrapper is, and it's not cleaning up its child processes properly.

```
PID 1 (init/systemd)
 └── PID 842 (containerd-shim)
      └── PID 850 (your app entrypoint)
           └── PID 851 (worker process, forked)
                └── PID 852 (zombie — parent exited without wait())
```

This is why tools like `tini` and `dumb-init` show up as the entrypoint in so many production Dockerfiles. Their entire job is to clean up zombie children — something PID 1 is supposed to do, and something your app almost certainly wasn't built to do.

Here's a quick way to check for this locally:

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

Nothing fancy. Just a reminder that you can check the process table before assuming a memory leak is the culprit.

## Memory: Where Everyone Gets Confused

If there's one Linux thing that trips up even senior engineers, it's how memory gets counted. `free -h` shows "used" memory that includes buffers and cache — stuff the kernel will happily hand back the moment something else needs it. New engineers see a number near 100% and panic. The number you actually want is `available`, not `used`.

Inside a container, it gets messier. `cgroup` limits control what your container is allowed to use, but a lot of language runtimes — old JVMs especially — ignore cgroup limits by default and read `/proc/meminfo` instead, which reports the *host's* total memory, not the container's. That's how you end up with a Java process running a heap size bigger than the container's actual memory ceiling, slowly building toward an OOM kill that looks mysterious until you know where to look.

| Symptom | Likely Cause | Where to Check |
|---|---|---|
| Container OOMKilled despite low reported usage | cgroup memory limit hit, cache counted against limit | `cat /sys/fs/cgroup/memory.max` (or v1 equivalent) |
| JVM crashes with OutOfMemoryError under low limits | Heap sized against host memory, not container limit | JVM flags, `-XX:+UseContainerSupport` |
| `free -h` shows high usage but app runs fine | Page cache inflating "used" | Look at `available` column instead |
| Gradual memory growth over days | Possible leak, or unbounded cache/connection pool | `pmap`, heap dumps, or app-level metrics |

None of this is obscure. It's just not the kind of thing a Kubernetes tutorial teaches, because those tutorials assume you already get how memory works underneath.

## systemd: You're Using It Whether You Like It or Not

Whatever you think of how big systemd has gotten, it's the init system running on most production Linux boxes today. It's worth understanding instead of treating it as a black box you `systemctl restart` and walk away from.

A well-written unit file tells you a lot about how a service is supposed to behave — whether it restarts on failure, how long it waits, what it needs before it starts. Here's a typical one for a background worker:

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

The part people skip over is `Requires=` versus `After=`. `After=` only controls order — it doesn't check that the dependency is actually running. `Requires=` makes sure the dependency exists and is active, and if it fails, this unit fails too. Mixing these two up is a common reason a service starts "successfully" against a database that isn't actually ready yet, then spends its first few seconds crash-looping while retry logic catches up.

## Networking Basics That Save You Hours

You don't need to be a network engineer to run production systems, but you need to be comfortable with a few basics. When one service can't reach another, the network itself is almost never actually broken. The real question is which of four things is wrong: DNS, routing, a firewall rule, or the app not listening where you think it is.

That last one gets people all the time. An app bound to `127.0.0.1` inside a container can't be reached from outside that container, even though `curl localhost:8080` from inside works fine. The fix is almost always binding to `0.0.0.0`, but getting there means checking `ss -tlnp` or `netstat -tlnp` and actually looking at which address the socket is bound to, not just which port.

```bash
# Is anything actually listening, and on which interface?
ss -tlnp | grep 8080

# Can you resolve the service name from inside the pod/container?
nslookup my-service.default.svc.cluster.local

# Is there a route, or does it just look like there should be one?
ip route get 10.0.4.15
```

Three commands, and together they tell you which layer is actually broken instead of a vague "networking issue" that gets punted to whoever owns the VPC.

## File Descriptors and "Too Many Open Files"

This one gets its own section because it's common and easy to fix once you know what's going on. Every open file, socket, and pipe uses up a file descriptor, and both the process and the whole system have a cap on how many can be open at once. A connection pool that isn't closing connections, or a service under heavy load opening way more sockets than it should, will eventually hit that cap and start throwing `EMFILE` errors that don't look anything like a resource limit problem.

Checking your current limits is easy:

```bash
ulimit -n                 # soft limit for current shell
cat /proc/<pid>/limits    # hard and soft limits for a running process
ls /proc/<pid>/fd | wc -l # how many are actually open right now
```

Bumping the limit is often the fast fix, and sometimes it's the right one. But think before you do it out of habit — a file descriptor leak that gets hidden by a higher ulimit doesn't go away. It just takes longer to show up again, usually during your next traffic spike.

## Putting It Together

None of this replaces knowing Kubernetes or your cloud platform — that stuff still matters a lot. But there's a reason experienced engineers keep coming back to Linux basics when things get hard to debug. Everything you work with — containers, pods, serverless functions — is built on the same handful of kernel pieces: processes, namespaces, cgroups, file descriptors, and the network stack. Knowing those pieces doesn't make the higher-level tools pointless. It just makes you a lot faster at figuring out which layer actually broke.

Next time something fails in a way that doesn't match the error message, drop down a level. Check the process tree. Check the real memory numbers, not just the headline percentage. Check what the socket is actually bound to. More often than you'd think, the answer was sitting in `/proc` the whole time.

---

*Found this useful? More production-focused DevOps writing like this lives at [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — practical breakdowns, not tutorials.*
