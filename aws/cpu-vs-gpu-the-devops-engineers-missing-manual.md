# CPU Architecture, Evolution & GPU Comparison: A DevOps Engineer's Deep Dive

> **Audience:** DevOps / Platform Engineers working with application infrastructure, ML workloads, and cloud compute  
> **Goal:** Understand CPU internals, how they've evolved over decades, how your Python/Java app *actually* uses it, and why GPUs are built around a fundamentally different way of computing.

CPU vs GPU for DevOps Engineers — covers CPU pipeline internals, Python GIL + asyncio, Java JIT, full request lifecycle, Kubernetes throttling, GPU CUDA architecture, and when to use which. With real benchmarks, perf commands, and AWS instance selection guidance.
---

## Table of Contents

1. [What Is a CPU, Really?](#1-what-is-a-cpu-really)
2. [The CPU Evolution Timeline](#2-the-cpu-evolution-timeline)
3. [CPU Core Internals — The Pipeline](#3-cpu-core-internals--the-pipeline)
4. [How Your Python/Java App Actually Uses the CPU](#4-how-your-pythonjava-app-actually-uses-the-cpu)
5. [A Full Request Lifecycle: DB Fetch → Business Logic → Frontend Response](#5-a-full-request-lifecycle-db-fetch--business-logic--frontend-response)
6. [CPU Bottlenecks DevOps Engineers Hit in Production](#6-cpu-bottlenecks-devops-engineers-hit-in-production)
7. [Enter the GPU — A Fundamentally Different Machine](#7-enter-the-gpu--a-fundamentally-different-machine)
8. [CPU vs GPU: The Architecture Comparison](#8-cpu-vs-gpu-the-architecture-comparison)
9. [Why Modern AI/ML Models Need GPUs](#9-why-modern-aiml-models-need-gpus)
10. [Practical DevOps Implications: When to Use What](#10-practical-devops-implications-when-to-use-what)
11. [Kubernetes & Cloud: CPU and GPU Resource Management](#11-kubernetes--cloud-cpu-and-gpu-resource-management)
12. [Key Metrics to Monitor](#12-key-metrics-to-monitor)
13. [Glossary](#13-glossary)

---

## 1. What Is a CPU, Really?

A **Central Processing Unit (CPU)** is the general-purpose brain of a computer. It is designed to execute a **sequence of diverse instructions** — arithmetic, logic, control flow, I/O — as fast as possible, one (or a few) at a time.

The key design philosophy of a CPU is **latency optimization**: make *any single task* complete as fast as possible.

```
┌─────────────────────────────────────────────────────┐
│                     CPU Die                         │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │  Core 0  │  │  Core 1  │  │   Last Level     │  │
│  │ (complex)│  │ (complex)│  │   Cache (LLC)    │  │
│  └──────────┘  └──────────┘  │   (shared)       │  │
│  ┌──────────┐  ┌──────────┐  └──────────────────┘  │
│  │  Core 2  │  │  Core 3  │                         │
│  │ (complex)│  │ (complex)│  ┌──────────────────┐  │
│  └──────────┘  └──────────┘  │  Memory Controller│  │
│                               └──────────────────┘  │
└─────────────────────────────────────────────────────┘
```

Each core is deeply complex with branch predictors, out-of-order execution engines, speculative execution units, and multi-level caches — all designed to make a *single thread* run blazingly fast.

---

## 2. The CPU Evolution Timeline

### 1970s — The Beginning: Single-Cycle, Simple

- **Intel 4004 (1971):** 4-bit, 740 KHz, 2,300 transistors. One instruction per clock, no pipeline.
- **Intel 8086 (1978):** 16-bit, up to 10 MHz. Introduced the x86 ISA still alive today.
- **Key constraint:** Clock speed = performance. One transistor toggle per cycle.

### 1980s — Pipelining: Do Multiple Things at Once

- **Intel 80486 (1989):** First x86 with an on-chip FPU and a **5-stage pipeline**.
- A pipeline splits instruction execution into stages (Fetch → Decode → Execute → Memory → Writeback) so multiple instructions overlap.
- **RISC vs CISC debate:** RISC (ARM, MIPS) used simpler instructions for better pipelining; CISC (x86) translated complex instructions internally.

```
Without Pipeline:        | I1 |    | I1 |    | I1 |
With 5-Stage Pipeline:   | F  | D  | E  | M  | W  |  ← I1
                              | F  | D  | E  | M  | W  |  ← I2
                                   | F  | D  | E  | M  | W  |  ← I3
```

### 1990s — Superscalar & Out-of-Order Execution

- **Intel Pentium (1993):** First superscalar x86 — two integer pipelines in parallel.
- **Intel Pentium Pro (1995):** Introduced **Out-of-Order Execution (OoOE)**. The CPU reorders instructions dynamically to avoid waiting on slow operations (like memory reads).
- **Branch Prediction** matured: CPU *guesses* the result of an `if` statement and pre-executes ahead. If wrong, it flushes and retries (branch misprediction penalty).
- Clock speeds climbed from 66 MHz → 300+ MHz.

### 2000s — The GHz Race Hits a Wall

- **Intel Pentium 4 (Netburst):** Pushed to 3.8 GHz with a deep 31-stage pipeline. More stages = higher clock, but also more penalty on branch mispredictions.
- **The Power Wall:** Power consumption ∝ frequency³. At ~4 GHz, chips were consuming 100W+ and throttling from heat. The "GHz race" ended around 2004.
- **The shift:** Industry pivoted from *faster single cores* to *more cores*.

### 2005–2010 — Multi-Core Era Begins

- **Intel Core Duo (2006):** Two physical cores on one die.
- **AMD Phenom (2007):** Four cores natively.
- **Key insight for DevOps:** Adding cores doesn't automatically speed up a single-threaded app. It helps with *concurrent workloads* — like a web server handling 1,000 simultaneous requests.
- **Amdahl's Law** becomes relevant:

```
Speedup = 1 / (S + (1-S)/N)

Where:
  S = fraction of work that is serial (cannot be parallelized)
  N = number of cores/processors

If 20% of your code is serial:
  Max speedup with infinite cores = 1 / 0.20 = 5x — no matter how many cores you add.
```

### 2010s — Efficiency, Caches, and Heterogeneous Compute

- **Intel Sandy Bridge / Ivy Bridge:** Integrated GPU on-die, improved cache hierarchy.
- **Intel Haswell (2013):** Introduced **AVX2** — 256-bit SIMD (Single Instruction, Multiple Data) — the CPU could now multiply 8 floats simultaneously.
- **Hyperthreading matured:** One physical core presents as 2 logical cores to the OS, sharing execution units. Useful for I/O-heavy workloads but not for pure compute.
- **ARM rises (mobile):** Apple A-series, Qualcomm Snapdragon focused on perf-per-watt.

### 2020s — Chiplets, Efficiency Cores, and the AI Era

- **AMD Ryzen (Zen architecture):** **Chiplet design** — multiple smaller dies connected via high-speed interconnects (Infinity Fabric). Dramatically improves yields and allows mixing components.
- **Apple M1/M2/M3:** Unified memory architecture — CPU and GPU share the same physical DRAM with massive bandwidth (up to 800 GB/s on M2 Ultra). Big deal for ML inference on-device.
- **Intel Alder Lake (2021):** **Hybrid cores** — Performance-cores (P-cores) for latency-sensitive tasks + Efficiency-cores (E-cores) for background work. The OS scheduler (Thread Director) routes work appropriately.
- **AMD EPYC Genoa (2022):** 96 cores, 192 threads, 384 MB L3 cache. Designed for cloud-scale workloads.
- **Key 2020s trend:** CPUs are now deeply heterogeneous — multiple core types, integrated AI accelerators (e.g., Apple Neural Engine, Intel AMX), and tight integration with memory.

---

## 3. CPU Core Internals — The Pipeline

Understanding what happens inside a single core is critical for diagnosing performance issues.

```
┌─────────────────────────────────────────────────────────────────┐
│                        CPU Core (Modern)                        │
│                                                                 │
│  ┌─────────┐  ┌─────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │  L1-I   │  │  L1-D   │  │ Branch       │  │  L2 Cache   │  │
│  │  Cache  │  │  Cache  │  │ Predictor    │  │  (private)  │  │
│  │ (~32KB) │  │ (~48KB) │  │              │  │  (256KB-1MB)│  │
│  └────┬────┘  └────┬────┘  └──────┬───────┘  └─────────────┘  │
│       │            │              │                             │
│  ┌────▼────────────▼──────────────▼───────────────────────┐    │
│  │              Front End (Fetch & Decode)                 │    │
│  │  Fetch → Predecode → Decode → Rename/Allocate           │    │
│  └─────────────────────────┬───────────────────────────────┘    │
│                            │                                    │
│  ┌─────────────────────────▼───────────────────────────────┐    │
│  │         Out-of-Order Engine (Scheduler / ROB)           │    │
│  │   Reorder Buffer: holds in-flight instructions           │    │
│  │   Dispatch to execution units based on data readiness    │    │
│  └──┬────────┬────────┬────────┬────────┬──────────────────┘    │
│     │        │        │        │        │                       │
│  ┌──▼──┐  ┌──▼──┐  ┌──▼──┐  ┌──▼──┐  ┌──▼──────────────────┐  │
│  │ ALU │  │ ALU │  │ FPU │  │ AGU │  │  Load/Store Unit    │  │
│  │(int)│  │(int)│  │(flt)│  │(adr)│  │  (memory access)    │  │
│  └─────┘  └─────┘  └─────┘  └─────┘  └────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### The Memory Hierarchy — The Most Critical Factor for Performance

This is where most production performance issues originate:

| Level | Size | Latency | Bandwidth |
|-------|------|---------|-----------|
| Registers | ~1 KB | ~0.3 ns (1 cycle) | ~10 TB/s |
| L1 Cache | 32–64 KB/core | ~1 ns (4 cycles) | ~4 TB/s |
| L2 Cache | 256 KB–1 MB/core | ~4 ns (12 cycles) | ~2 TB/s |
| L3 Cache | 8–64 MB (shared) | ~10 ns (40 cycles) | ~1 TB/s |
| DRAM | 32–512 GB | ~60–80 ns (200+ cycles) | ~50–100 GB/s |
| NVMe SSD | TBs | ~100 µs (100,000 ns) | ~7 GB/s |
| Network (local) | — | ~100 µs–1 ms | ~10–100 Gb/s |

> **DevOps insight:** When you see high CPU usage but low actual throughput, the CPU is often *stalled waiting for memory*. Tools like `perf stat` will show `cache-misses` and `instructions per cycle (IPC)` — an IPC below 1.0 on a modern CPU suggests memory-bound behavior.

---

## 4. How Your Python/Java App Actually Uses the CPU

### Python's Execution Model

Python is an **interpreted language** with a **Global Interpreter Lock (GIL)**.

```
Your Python Source (.py)
         │
         ▼
  CPython Compiler
         │  (at import/run time)
         ▼
   Bytecode (.pyc)   ← stored in __pycache__
         │
         ▼
  CPython VM (interpreter loop)
         │  executes bytecode instructions one-by-one
         ▼
  C Extensions / OS Calls
  (numpy, psycopg2, socket, etc.)
         │
         ▼
       CPU
```

**The GIL — Python's Most Famous CPU Constraint:**

```python
import threading

counter = 0

def increment():
    global counter
    for _ in range(1_000_000):
        counter += 1  # NOT thread-safe without GIL - but GIL makes this slower!

t1 = threading.Thread(target=increment)
t2 = threading.Thread(target=increment)
t1.start(); t2.start()
t1.join(); t2.join()

# Result: counter may not be 2,000,000
# The GIL prevents true parallelism for CPU-bound Python threads.
# For CPU-bound work, use multiprocessing.Process instead.
```

**What releases the GIL?**
- Any blocking I/O (network, disk, database queries) — the GIL releases while waiting
- C extensions that explicitly release it (NumPy, psycopg2 during query execution)
- `time.sleep()`

This is why Python async I/O (`asyncio`) and threading work well for I/O-bound work (like database calls), but you need `multiprocessing` or C extensions for CPU-bound work.

### Java's Execution Model

Java compiles to **bytecode** run on the **JVM**, but with a key advantage over Python:

```
Your Java Source (.java)
         │
         ▼
  javac compiler
         │
         ▼
   JVM Bytecode (.class)
         │
         ▼
  JIT Compiler (JVM)          ← This is key
  ┌──────────────────────────────────────┐
  │ Interprets bytecode initially        │
  │ Profiles hot code paths (hotspots)   │
  │ Compiles hot paths to native machine │
  │ code (x86/ARM) at runtime            │
  └──────────────────────────────────────┘
         │
         ▼
   Native Machine Code → CPU
```

Java's JIT means that after warmup (typically 10,000–100,000 invocations of a method), hot code runs at near-native speed. This is why JVM applications have slower startup but excellent steady-state throughput — critical context for Kubernetes pod startup probes and warmup strategies.

---

## 5. A Full Request Lifecycle: DB Fetch → Business Logic → Frontend Response

Let's trace a real mid-tier API call at the CPU instruction level.

### The Application: A REST API

```
[React Frontend]
       │  HTTP GET /api/users/42/orders
       ▼
[Load Balancer / Nginx]
       │
       ▼
[Python (FastAPI) or Java (Spring Boot) Server]   ← Our focus
       │  JDBC / psycopg2 / SQLAlchemy
       ▼
[PostgreSQL Database]
```

### Python (FastAPI) Example

```python
# app/routers/orders.py
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

app = FastAPI()

@app.get("/api/users/{user_id}/orders")
async def get_user_orders(user_id: int, db: AsyncSession = Depends(get_db)):
    # ── PHASE 1: Request parsing ──────────────────────────────
    # CPU work: parse HTTP headers, route matching, JSON schema validation
    # Very fast — microseconds, L1/L2 cache hits
    
    # ── PHASE 2: Database query ──────────────────────────────
    # CPU sends query to DB driver
    # GIL is RELEASED here — CPU is free to handle other requests
    result = await db.execute(
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(50)
    )
    # CPU is IDLE during network round-trip to PostgreSQL (~1-50ms)
    # asyncio event loop runs OTHER coroutines during this wait
    orders = result.scalars().all()
    
    # ── PHASE 3: Business logic ──────────────────────────────
    # CPU-bound: transform, filter, compute totals
    # GIL is HELD — pure Python execution
    processed_orders = []
    for order in orders:
        total = sum(item.price * item.qty for item in order.items)
        processed_orders.append({
            "id": order.id,
            "total": total,
            "status": compute_status(order),  # business logic
            "items": [serialize_item(i) for i in order.items]
        })
    
    # ── PHASE 4: Serialize & respond ────────────────────────
    # CPU work: dict → JSON bytes (Pydantic/orjson)
    # Memory: serialize to heap, then send via kernel socket buffer
    return processed_orders
```

### What the CPU Does at Each Phase

```
Phase 1: Request Parsing
─────────────────────────────────────────────────────────
Nginx → kernel TCP stack → Python process (via WSGI/ASGI)
CPU ops: string parsing, hash table lookups (headers), 
         regex matching (routing), function dispatch
Memory: L1/L2 cache hits for hot code paths
Time: ~50–500 µs

Phase 2: Database I/O
─────────────────────────────────────────────────────────
1. Python builds query string (CPU: string concat, formatting)
2. psycopg2/asyncpg serializes to PostgreSQL wire protocol
3. syscall: send() → kernel copies data to socket buffer
4. ── CPU IS NOW WAITING (or handling other requests) ──
5. Network RTT to DB: 0.1ms (local) to 5ms (same AZ cloud)
6. PostgreSQL executes query: index scan, heap fetch
7. Network RTT back
8. Python receives bytes, deserializes wire protocol → Python objects
CPU ops on return: malloc for Python objects, reference counting

Phase 3: Business Logic
─────────────────────────────────────────────────────────
Pure Python execution on received data:
- List comprehensions → bytecode LOAD/STORE ops
- Arithmetic → ALU instructions (fast, register-based)
- Object attribute access → dictionary hash lookups
- Function calls → stack frame allocation (heap/stack)
GIL is HELD the entire time
CPU time: proportional to data size — typically 1–50ms for 50 orders

Phase 4: Serialization
─────────────────────────────────────────────────────────
dict/list → JSON string → bytes
orjson (Rust-based): releases GIL, uses SIMD for fast serialization
syscall: send() to client socket buffer → TCP stack → client
```

### Java (Spring Boot) Equivalent — JVM Threading Model

```java
// OrderController.java
@RestController
@RequestMapping("/api")
public class OrderController {

    @Autowired
    private OrderRepository orderRepo;  // Spring Data JPA

    @GetMapping("/users/{userId}/orders")
    public ResponseEntity<List<OrderDTO>> getUserOrders(@PathVariable Long userId) {
        
        // ── PHASE 1: Spring MVC dispatches to THIS thread ──────
        // Thread: from Tomcat thread pool (default: 200 threads)
        // Each thread has its own JVM stack (~512KB–1MB)
        
        // ── PHASE 2: Database query (BLOCKING in default Spring MVC) ──
        // This thread BLOCKS here — it holds its stack memory and OS thread
        // while waiting for the DB response
        // (Unlike Python async, Java Spring MVC blocks the thread)
        List<Order> orders = orderRepo.findByUserIdOrderByCreatedAtDesc(userId);
        // For non-blocking: use Spring WebFlux + R2DBC
        
        // ── PHASE 3: Business logic (JIT-compiled to native code) ──
        // After ~10k invocations, JIT compiles this to optimized x86
        // JVM can inline, vectorize, and optimize aggressively
        List<OrderDTO> result = orders.stream()
            .map(order -> {
                BigDecimal total = order.getItems().stream()
                    .map(i -> i.getPrice().multiply(BigDecimal.valueOf(i.getQty())))
                    .reduce(BigDecimal.ZERO, BigDecimal::add);
                return new OrderDTO(order.getId(), total, computeStatus(order));
            })
            .collect(Collectors.toList());
        
        // ── PHASE 4: Jackson serialization → HTTP response ──
        return ResponseEntity.ok(result);
    }
}
```

**Key CPU difference — Java vs Python for this workload:**

| Aspect | Python (FastAPI async) | Java (Spring MVC) |
|--------|----------------------|-------------------|
| Concurrency model | Single thread, event loop | Thread-per-request (blocking) |
| CPU during DB wait | Free to run other coroutines | Thread blocked, OS sleeps it |
| Business logic speed | Bytecode interpreted (slow) | JIT-compiled near-native (fast) |
| Memory per request | Low (shared event loop) | High (~1MB stack per thread) |
| Warmup behavior | Immediate (interpreted) | Slow start → faster steady state |
| GIL impact | Limits CPU-bound parallelism | No GIL — true parallelism |
| Ideal workload | I/O-heavy, many concurrent users | CPU-heavy, computationally complex logic |

---

## 6. CPU Bottlenecks DevOps Engineers Hit in Production

### Bottleneck 1: CPU Throttling in Kubernetes

```yaml
# This is a common misconfiguration
resources:
  requests:
    cpu: "100m"    # 0.1 CPU = 10% of one core
  limits:
    cpu: "200m"    # Throttled to 20% of one core

# Result: Your Python/Java app runs, but CPU is throttled by the
# Linux CFS (Completely Fair Scheduler). Latency spikes occur even
# at low utilization because the pod is THROTTLED, not busy.
```

**Diagnosis:**
```bash
# Check throttling
kubectl top pod <pod-name>

# Inside the container or via cAdvisor metrics:
cat /sys/fs/cgroup/cpu/cpu.stat
# Look for: throttled_time (nanoseconds throttled)

# Prometheus query:
rate(container_cpu_cfs_throttled_seconds_total[5m]) /
rate(container_cpu_cfs_periods_total[5m])
# If > 25%, you have a throttling problem
```

### Bottleneck 2: GC Pressure (Java)

JVM Garbage Collection is CPU-intensive and causes **stop-the-world pauses**:

```bash
# Enable GC logging (Java 11+)
java -Xmx4g \
     -XX:+UseG1GC \
     -Xlog:gc*:file=/var/log/app/gc.log:time,uptime:filecount=5,filesize=20m \
     -jar app.jar

# Key metrics to monitor:
# - GC pause time (target: <10ms for G1, <1ms for ZGC)
# - GC overhead: CPU% spent in GC (alert if >5% sustained)
# - Old gen occupancy triggering full GCs
```

### Bottleneck 3: Python CPU-Bound Work Blocking the Event Loop

```python
# BAD: This blocks the entire asyncio event loop
@app.get("/compute")
async def bad_endpoint():
    result = heavy_computation(data)  # Blocks for 500ms!
    return result

# GOOD: Run CPU-bound work in a thread pool
import asyncio
from concurrent.futures import ProcessPoolExecutor

executor = ProcessPoolExecutor(max_workers=4)

@app.get("/compute")
async def good_endpoint():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, heavy_computation, data)
    return result
```

### Bottleneck 4: Context Switching

When you have more threads than cores, the OS constantly **context switches** — saving and restoring CPU state (registers, stack pointer, etc.).

```bash
# Monitor context switches
vmstat 1          # cs column = context switches per second
pidstat -w -p <pid> 1  # per-process voluntary/involuntary switches

# High involuntary switches = too many threads competing for cores
# Rule of thumb for CPU-bound work: threads ≈ CPU cores
# Rule of thumb for I/O-bound work: threads can exceed cores significantly
```

---

## 7. Enter the GPU — A Fundamentally Different Machine

The GPU was born to render graphics: take millions of pixels and apply the same shader calculation to each one simultaneously.

**The fundamental insight:** Graphics (and later ML) workloads are **embarrassingly parallel** — the same operation repeated on thousands/millions of independent data points.

```
CPU Design Philosophy:          GPU Design Philosophy:
─────────────────────           ─────────────────────
Minimize LATENCY                Maximize THROUGHPUT
of any single task              of many identical tasks

"Get one task done              "Get a million tasks done
 as fast as possible"            simultaneously"
```

### GPU Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    NVIDIA H100 GPU (2022)                        │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                    GPC (Graphics Processing Cluster)     │    │
│  │  ┌──────────────────────────────────────────────────┐    │    │
│  │  │               SM (Streaming Multiprocessor) x132 │    │    │
│  │  │  ┌───────────┐  ┌───────────┐  ┌───────────┐    │    │    │
│  │  │  │  CUDA     │  │  CUDA     │  │  Tensor   │    │    │    │
│  │  │  │  Core x64 │  │  Core x64 │  │  Core x4  │    │    │    │
│  │  │  │ (FP32)    │  │  (INT32)  │  │(matrix op)│    │    │    │
│  │  │  └───────────┘  └───────────┘  └───────────┘    │    │    │
│  │  │  ┌─────────────────────────────────────────┐    │    │    │
│  │  │  │  Shared Memory / L1 Cache (256 KB/SM)   │    │    │    │
│  │  │  └─────────────────────────────────────────┘    │    │    │
│  │  └──────────────────────────────────────────────────┘    │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                 L2 Cache (50 MB)                         │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │          HBM3 Memory (80 GB, 3.35 TB/s bandwidth)        │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘

Total: 16,896 CUDA Cores + 528 Tensor Cores
```

### The CUDA Programming Model

GPUs execute code in a hierarchy:

```
Grid (entire GPU job)
  └── Blocks (run on one SM, share memory)
        └── Warps (32 threads executing SAME instruction)
              └── Threads (individual execution units)

// Simple CUDA kernel: add two arrays element-by-element
__global__ void vector_add(float *a, float *b, float *c, int n) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < n) {
        c[idx] = a[idx] + b[idx];  // Each thread handles ONE element
    }
}

// Launch: 1 million elements, 256 threads per block
int blocks = (1000000 + 255) / 256;  // = 3907 blocks
vector_add<<<blocks, 256>>>(a, b, c, 1000000);
// GPU launches 1,000,000 threads simultaneously
```

**SIMT — Single Instruction, Multiple Threads:**  
A warp (32 threads) executes the *exact same instruction* at the *exact same time*, just on different data. This is the GPU's superpower — and also its constraint (divergent branches within a warp cause serialization).

---

## 8. CPU vs GPU: The Architecture Comparison

| Dimension | CPU (e.g., AMD EPYC 9654) | GPU (e.g., NVIDIA H100) |
|-----------|--------------------------|------------------------|
| **Cores** | 96 cores | 16,896 CUDA cores + 528 Tensor cores |
| **Clock Speed** | 2.4–3.7 GHz | 1.8 GHz (lower, but massively parallel) |
| **Memory** | 6 TB DDR5 addressable | 80 GB HBM3 (on-device only) |
| **Memory Bandwidth** | ~460 GB/s | 3,350 GB/s |
| **FP32 Throughput** | ~7 TFLOPS | 67 TFLOPS |
| **FP16 (ML) Throughput** | ~14 TFLOPS | 989 TFLOPS (Tensor Cores) |
| **Cache** | 384 MB L3 (shared) | 50 MB L2 |
| **Power** | 360W TDP | 700W TDP |
| **Task type** | Serial, diverse, latency-sensitive | Parallel, homogeneous, throughput-sensitive |
| **Branching** | Excellent (branch predictor) | Poor (warp divergence costly) |
| **Memory latency** | ~60 ns DRAM | ~80 ns HBM (hidden by parallelism) |
| **Programming model** | Threads, processes, async | CUDA/ROCm kernels, grids, warps |
| **Best for** | Web servers, databases, business logic, OS | ML training, inference, rendering, simulations |

### The "Roofline Model" — Understanding Compute Limits

For any workload, performance is limited by either compute or memory bandwidth:

```
Performance
    │    /  ← Memory-bound (slope = bandwidth)
    │   /
    │  /
    │ /_________________ ← Compute-bound (ceiling = TFLOPS)
    │/
    └──────────────────────────
         Arithmetic Intensity
         (FLOPs / bytes loaded)

Arithmetic Intensity = Total FLOPs / Total Memory Traffic

Matrix multiply (LLM attention): ~300 FLOPs/byte → Compute-bound on GPU ✓
BERT tokenization: ~1 FLOPs/byte → Memory-bound even on GPU
REST API business logic: irregular access patterns → CPU wins ✓
```

---

## 9. Why Modern AI/ML Models Need GPUs

### The Matrix Multiplication at the Heart of Everything

Transformer models (GPT, BERT, LLaMA) are fundamentally chains of **matrix multiplications**:

```
Attention(Q, K, V) = softmax(QKᵀ / √d_k) · V

For GPT-4 (estimated):
- ~220 billion parameters
- Each forward pass (inference): ~440 billion FP16 multiply-accumulate ops
- At 1000 tokens: ~440 × 10¹² × 1000 ops
```

**CPU inference time (approximate, AMD EPYC, FP32):**
```
440 TFLOP / 7 TFLOPS = ~63 seconds per token  ← unusable
```

**GPU inference time (NVIDIA H100, FP16 Tensor Cores):**
```
440 TFLOP / 989 TFLOPS = ~0.44 seconds per token  ← still slow for large models
```

This is why production LLM serving uses **multiple H100s with NVLink** (900 GB/s GPU-to-GPU bandwidth) and **FP8 quantization** to push throughput further.

### Memory Bandwidth Is the Real Bottleneck for Inference

```
Model size = parameters × bytes per parameter
LLaMA-3 70B in FP16 = 70 × 10⁹ × 2 bytes = 140 GB

For autoregressive inference (1 token at a time):
- Must load all 140 GB of weights for each token
- H100 HBM bandwidth: 3.35 TB/s
- Minimum time per token: 140 GB / 3.35 TB/s = 42 ms
- → ~24 tokens/second maximum (single GPU)

This is why batching matters:
- Batch of 32 requests: still loads weights once, generates 32 tokens
- Effective throughput: 32 × 24 = 768 tokens/second
```

### GPU Memory Hierarchy Matters for DevOps

```
VRAM (HBM) → L2 Cache → L1/Shared Memory → Registers
  80 GB        50 MB        256 KB/SM         ~64KB/SM

Key: If your model doesn't fit in VRAM, it must be split across GPUs
(tensor parallelism) or offloaded to CPU RAM (much slower).

Common DevOps mistake: Deploying a 13B model on a 16GB VRAM card:
  13B params × 2 bytes (FP16) = 26 GB  ← doesn't fit!
  Solution: 4-bit quantization: 13B × 0.5 bytes = 6.5 GB ✓
  (with quality tradeoff)
```

---

## 10. Practical DevOps Implications: When to Use What

### Decision Framework

```
                    Is the work parallel?
                   /                      \
                 No                       Yes
                  |                        |
         Serial / branchy          Are data elements
         control flow?             independent?
                  |               /              \
           USE CPU          Yes (embarrassingly    No (data dependencies)
                            parallel)                     |
                                 |                  USE CPU or
                            USE GPU                 distributed CPU
```

### Workload Classification

| Workload | Use | Why |
|----------|-----|-----|
| Web API (FastAPI, Spring Boot) | CPU | Serial request handling, branchy business logic |
| Database (PostgreSQL, MySQL) | CPU | Complex query planning, random I/O, ACID transactions |
| Nginx / Load Balancing | CPU | Low core count, high memory bandwidth needed |
| ML Training (Transformers) | GPU | Matrix ops, massively parallel gradient computation |
| ML Inference (LLMs) | GPU (or specialized) | High FLOP/s and memory bandwidth needed |
| Video transcoding | GPU | Embarrassingly parallel pixel operations |
| Data pipeline (Spark ETL) | CPU (many cores) | Columnar ops benefit from CPU SIMD, not GPU |
| Redis / Caching | CPU (single thread) | In-memory ops, network I/O bound |
| Prometheus / Metrics | CPU | Time-series math, not matrix ops |

### Cloud Instance Selection Guide

**CPU-Optimized (your API server):**
```
AWS:   c7g (Graviton3 ARM) — best perf/$ for web workloads
       c7i (Intel Sapphire Rapids) — AVX-512 for vectorizable workloads
GCP:   c3-highcpu (Intel Sapphire Rapids)
Azure: Fsv3-series
```

**Memory-Optimized (database, JVM with large heap):**
```
AWS:   r7g (Graviton3) — 512 GB RAM, good for PostgreSQL, ElasticSearch
GCP:   m3-ultramem — up to 12 TB RAM
```

**GPU (ML inference):**
```
AWS:   p4d.24xlarge (8× A100 80GB), p5.48xlarge (8× H100)
       g5.xlarge (A10G 24GB) — cost-effective for smaller models
GCP:   a3-highgpu (8× H100)
Azure: ND H100 v5-series

On-prem: NVIDIA DGX H100 (8× H100, NVLink)
```

---

## 11. Kubernetes & Cloud: CPU and GPU Resource Management

### CPU Resource Management

```yaml
# Production-grade CPU configuration
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
spec:
  template:
    spec:
      containers:
      - name: api
        image: myapp:latest
        resources:
          requests:
            cpu: "500m"      # 0.5 CPU — what the scheduler reserves
            memory: "512Mi"
          limits:
            cpu: "2000m"     # 2 CPU — max burst
            memory: "1Gi"
        # IMPORTANT: For latency-sensitive services, set requests == limits
        # to get Guaranteed QoS class (no throttling from CFS)
```

**CPU Pinning for latency-critical workloads:**
```yaml
# Enable CPU Manager static policy in kubelet
# --cpu-manager-policy=static
# Then request integer CPUs with Guaranteed QoS:
resources:
  requests:
    cpu: "2"      # Integer = eligible for CPU pinning
    memory: "1Gi"
  limits:
    cpu: "2"      # Must equal requests for Guaranteed QoS
    memory: "1Gi"
# Result: Pod gets exclusive access to 2 physical cores
# No context switching from other pods on those cores
```

### GPU Resource Management

```yaml
# GPU workload deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-inference
spec:
  template:
    spec:
      containers:
      - name: inference
        image: vllm/vllm-openai:latest
        resources:
          limits:
            nvidia.com/gpu: "1"   # Request 1 full GPU
          requests:
            nvidia.com/gpu: "1"
        env:
        - name: NVIDIA_VISIBLE_DEVICES
          value: "all"
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
      nodeSelector:
        accelerator: nvidia-h100  # Target specific GPU nodes
```

**Multi-Instance GPU (MIG) — H100/A100 only:**
```bash
# Split one H100 into 7 independent GPU instances
nvidia-smi mig -cgi 9,9,9,9,9,9,9 -C
# Each instance: ~10 GB VRAM, ~1/7th compute
# Kubernetes sees 7 separate GPU devices per physical H100

# Useful for: running 7 smaller models on one expensive H100
# Kubernetes resource: nvidia.com/mig-1g.10gb: "1"
```

### Monitoring CPU and GPU in Production

```bash
# CPU monitoring
kubectl top nodes                          # Node-level CPU
kubectl top pods --containers             # Container-level
kubectl exec -it <pod> -- top -H          # Thread-level

# CPU flame graphs (find where your Python/Java is spending cycles)
kubectl exec -it <pod> -- py-spy top --pid 1  # Python
kubectl exec -it <pod> -- async-profiler       # Java

# GPU monitoring
nvidia-smi dmon -s pucvmet               # Per-GPU metrics stream
nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu \
           --format=csv -l 1

# Key GPU metrics:
# - GPU Utilization %: compute SM busy (target: >80% for training)
# - Memory Used/Total: VRAM utilization
# - SM Active %: fraction of SMs doing work
# - Tensor Core Utilization: for ML workloads, want this HIGH
# - PCIe/NVLink bandwidth: data transfer between CPU↔GPU or GPU↔GPU
```

---

## 12. Key Metrics to Monitor

### CPU Health Metrics

| Metric | Tool | Alert Threshold |
|--------|------|-----------------|
| CPU Utilization | `top`, Prometheus `node_exporter` | >85% sustained |
| CPU Throttling | cAdvisor, `cpu.stat` | >25% throttled periods |
| Context Switches | `vmstat`, `pidstat` | Baseline + 3σ |
| IPC (Instructions/Cycle) | `perf stat` | <1.0 suggests memory-bound |
| Cache Miss Rate | `perf stat` | >5% LLC miss rate is concerning |
| Load Average | `uptime`, `top` | >2× CPU count (sustained) |
| Run Queue Length | `vmstat` (r column) | > CPU count |

### GPU Health Metrics

| Metric | Tool | Alert Threshold |
|--------|------|-----------------|
| GPU Utilization | `nvidia-smi`, DCGM | <70% during inference (underutilized) |
| VRAM Utilization | `nvidia-smi` | >95% (risk OOM) |
| GPU Temperature | `nvidia-smi` | >85°C |
| Power Draw | `nvidia-smi` | Near TDP sustained |
| PCIe Bandwidth | DCGM | Check for CPU↔GPU bottleneck |
| XID Errors | `dmesg`, DCGM | Any XID error = investigate immediately |
| SM Utilization | DCGM `DCGM_FI_DEV_GPU_UTIL` | <50% for inference = batching issue |

---

## 13. Glossary

| Term | Definition |
|------|-----------|
| **ALU** | Arithmetic Logic Unit — performs integer math and logic operations |
| **FPU** | Floating Point Unit — handles decimal/floating point arithmetic |
| **IPC** | Instructions Per Cycle — higher is better; limited by pipeline stalls |
| **Out-of-Order Execution** | CPU reorders instructions to avoid waiting on slow operations |
| **Branch Prediction** | CPU guesses conditional branch outcomes to keep pipeline full |
| **SIMD** | Single Instruction, Multiple Data — one instruction operates on multiple data elements (AVX2, AVX-512) |
| **SIMT** | Single Instruction, Multiple Threads — GPU's version, executes same instruction across 32 threads (a warp) |
| **CUDA Core** | Basic GPU compute unit — executes FP32 or INT32 operations |
| **Tensor Core** | Specialized GPU unit for matrix multiply-accumulate (FP16/BF16/FP8) — key for AI |
| **HBM** | High Bandwidth Memory — GPU memory stacked on the die, very high bandwidth (~3+ TB/s) |
| **NVLink** | NVIDIA's GPU-to-GPU interconnect — much faster than PCIe for multi-GPU |
| **Warp** | 32 GPU threads executing in lockstep — the fundamental execution unit |
| **GIL** | Python's Global Interpreter Lock — prevents true thread-level CPU parallelism in CPython |
| **JIT** | Just-In-Time compilation — JVM compiles hot bytecode to native machine code at runtime |
| **CFS** | Linux Completely Fair Scheduler — distributes CPU time, enforces container CPU limits |
| **MIG** | Multi-Instance GPU — hardware partitioning of A100/H100 into isolated GPU slices |
| **Roofline Model** | Performance model showing whether a workload is compute-bound or memory-bandwidth-bound |
| **PCIe** | Peripheral Component Interconnect Express — bus connecting CPU and GPU (bottleneck for data transfer) |
| **TDP** | Thermal Design Power — the heat a cooler must dissipate; approximates max power draw |
| **Amdahl's Law** | Theoretical speedup limit of parallelization given a serial fraction of work |

---

## Further Reading

- [Intel 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
- [NVIDIA H100 Architecture Whitepaper](https://resources.nvidia.com/en-us-tensor-core)
- [Python GIL Deep Dive — David Beazley](https://dabeaz.com/python/UnderstandingGIL.pdf)
- [Brendan Gregg's Systems Performance (Book)](https://www.brendangregg.com/systems-performance-2nd-edition-book.html)
- [CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-c-programming-guide/)
- [Kubernetes CPU Management Policies](https://kubernetes.io/docs/tasks/administer-cluster/cpu-management-policies/)
- [DCGM — GPU Monitoring for Kubernetes](https://developer.nvidia.com/dcgm)

---

*Authored for DevOps / Platform engineers bridging traditional application infrastructure and modern AI/ML workloads.*  
*Last updated: 2025*
