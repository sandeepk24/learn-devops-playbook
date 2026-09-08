# SQLite for DevOps — Part 2: Security, Vulnerabilities, and Production-Readiness

> **Learn DevOps Playbook** — production-grade references for engineers who'd rather fix it than Google it.

**Series:** SQLite for DevOps (Part 2 of 2)
**Prerequisite:** Part 1 (architecture, install, concurrency).

---

## TL;DR

SQLite's security model is **the filesystem** — there is no built-in authentication, no authorization, no encryption, and no network attack surface. That's not a weakness per se; it's a *different threat model*. Your job is to know which threats SQLite eliminates (network attacks, auth bypass, privilege escalation in a DB server) and which it pushes onto **you** (file permissions, input validation, encryption-at-rest, untrusted-data handling).

Yes, you can run it in production. Yes, even in secure/regulated environments — *if* you treat the DB file with the same rigor you'd treat any sensitive file on disk.

---

## 1. The Security Model — Said Plainly

Because SQLite is a library, not a server, the entire client-server attack surface **does not exist**:

- No listening port → **no remote network attacks** against the DB.
- No authentication system → **no credential theft, no brute-force, no auth bypass CVEs**.
- No privileged daemon → **no `postgres`-user RCE escalating to host compromise via the DB process**.

What you get *instead* is a file. And a file's security is governed by:

1. **Filesystem permissions** (who can read/write the `.db`).
2. **Encryption at rest** (the OS/disk, or a SQLite encryption extension).
3. **What your application does** with the data (the real attack surface).

> **Reframe for seniors:** SQLite doesn't make your system more or less secure — it *relocates* the security boundary from "the database server's auth layer" to "the host's filesystem and your app code." If your filesystem and app are hardened, SQLite is often a *smaller* attack surface than a networked DB.

---

## 2. Does It Pose Security Issues? — Honest Inventory

### 2.1 No access control (by design)
Anyone (any process/user) who can read the file can read **every row** — there are no table-level grants, no row-level security, no "read-only user." Mitigation is entirely filesystem-level:

```bash
# DB owned by the service account, readable/writable by no one else
sudo chown appuser:appuser /var/lib/myapp/app.db
sudo chmod 600 /var/lib/myapp/app.db          # -rw-------
# WAL/SHM sidecar files inherit the same scrutiny:
sudo chmod 600 /var/lib/myapp/app.db-wal /var/lib/myapp/app.db-shm 2>/dev/null || true
```

Run the app as a **non-root, dedicated service account**. In containers, mount the DB on a volume owned by that UID, and never bake a *sensitive* DB into an image layer (image layers are extractable by anyone with the image).

### 2.2 No encryption at rest (in the public-domain build)
The stock SQLite engine writes **plaintext** to disk. Strings, including secrets you unwisely stored, are visible with `strings app.db`. Options:

- **Encrypt the volume** (LUKS, AWS EBS encryption, etc.) — usually the right DevOps answer.
- **Encryption extension** — SQLite's official **SEE** (commercial), or open-source **SQLCipher** (page-level AES). With SQLCipher you `PRAGMA key='...'` before any query; the whole file is AES-encrypted.
- **Don't store secrets in it.** Secrets belong in Secrets Manager / Vault, not a `.db`.

### 2.3 SQL injection — *still your problem*
Embedding the engine does **not** save you from injection. If you build SQL with string formatting, you're vulnerable exactly as you would be with Postgres.

```python
# ❌ NEVER — classic injection
svc = request_param
cur.execute(f"SELECT * FROM deploys WHERE service = '{svc}'")

# ✅ ALWAYS — parameter binding; the driver escapes safely
cur.execute("SELECT * FROM deploys WHERE service = ?", (svc,))
```

> **Subtle SQLite-specific risk:** never load **untrusted SQL** or untrusted `.db` files. Opening a maliciously crafted database file, or running attacker-supplied SQL, is the single largest source of SQLite CVEs (see §3). A `.db` file is *executable surface*, not inert data.

### 2.4 Extensions & untrusted databases
- **Disable extension loading** unless you explicitly need it — a loaded extension is arbitrary native code.
- Treat any `.db` from outside your trust boundary as hostile input. The parser holds up well but historically *every* serious SQLite CVE has involved either malicious SQL or a malformed database file.

```python
conn = sqlite3.connect("app.db")
conn.enable_load_extension(False)   # default in CPython, but be explicit in security reviews
```

### 2.5 Backups & data exfiltration
A SQLite "backup" is a **copy of the entire file** — there's no granular access boundary. Anyone who exfiltrates the file has 100% of the data. Encrypt backups, restrict their storage, and audit who can read the backup location.

---

## 3. Vulnerabilities & CVEs — What You're Actually Exposed To

SQLite is mature and audited, but it is *not* CVE-free. Knowing the **shape** of its vulnerabilities tells you exactly how to defend.

### 3.1 The pattern of SQLite CVEs
Historically, nearly all impactful SQLite CVEs share a precondition: **the attacker controls the SQL or the database file.** Notable examples (look up current details for your version):

- **"Magellan" (CVE-2018-20346 and related)** — heap overflows reachable through SQLite's FTS (full-text search), exploitable when an app lets attackers run arbitrary SQL (famously relevant to browsers via WebSQL).
- Various **memory-safety bugs** (use-after-free, out-of-bounds reads) in the query optimizer, window functions, or when parsing **malformed database files**.

The takeaway is consistent: **if untrusted parties cannot supply SQL or a database file to your engine, your realistic exposure is small.**

### 3.2 The version-pinning trap (this is the one that gets DevOps teams)
Recall from Part 1: language runtimes **bundle their own SQLite engine.** This fragments your patch surface:

- Patching the OS `libsqlite3` via `apt`/`dnf` does **not** patch the copy compiled into your Python, your Node, your browser, or any statically linked binary.
- A vulnerability scanner reading OS package metadata may report "patched" while your **Python's embedded `sqlite_version` is still vulnerable.**

**Audit every embedded copy:**

```python
import sqlite3
print("Engine SQLite version:", sqlite3.sqlite_version)  # this is what an attacker hits
```

```bash
# OS copy
sqlite3 --version
# Find statically/dynamically linked copies in containers
find / -name 'libsqlite3*' 2>/dev/null
ldd $(which python3) | grep -i sqlite || echo "sqlite is statically bundled in this build"
```

> **Action item:** Add `sqlite3.sqlite_version` to your service's `/healthz` or build manifest, and diff it against the SQLite release notes / NVD when CVEs drop. Treat the *embedded* version as the source of truth, not the OS package.

### 3.3 Keeping current
- Track [sqlite.org/news.html](https://www.sqlite.org/news.html) and the [CVE list](https://www.sqlite.org/cves.html) — SQLite publishes its own CVE page.
- Pin and bump deliberately; rebuild images to pick up patched embedded engines (a `python:3.12-slim` rebuild pulls a newer bundled SQLite).
- For statically linked Go/Rust binaries using SQLite, a fix means **recompiling** — there's no shared library to patch.

---

## 4. Can You Use It In Production? — Yes, With Conditions

SQLite explicitly markets an **"Appropriate Uses"** position, and it runs in production in *billions* of devices. The question isn't "is it production-grade?" (it is) — it's **"is it the right fit for *this* workload?"**

### ✅ Strong production fit
- **Single-node** apps and internal tools.
- **Read-heavy** workloads; writes from **one** process.
- **Embedded/edge** state, sidecars, CLI tools, config stores.
- Workloads where **operational simplicity** is worth more than horizontal scale.
- Data that fits comfortably on one host's disk (SQLite handles many GBs to low-TBs fine).

### ⚠️ Re-evaluate before committing
- Modest multi-writer needs → consider WAL + a single writer process serializing writes.
- Need durability/HA on one node → pair with **Litestream** (streams WAL to S3 for point-in-time restore) or **LiteFS**.

### ❌ Wrong tool — use Postgres/Dynamo/etc.
- Multiple **hosts** writing the same data concurrently.
- Need for horizontal write scaling, replicas with failover, or cross-node transactions.
- Network filesystem storage (NFS/EFS) as the DB location — locking is unreliable; **expect corruption.**
- Fine-grained, per-user DB-level access control requirements.

---

## 5. Hardening Checklist for Secure / Regulated Environments

If you're in a hardened or compliance-bound environment, this is your go-live gate:

| Control | Action |
|---|---|
| **Least privilege** | App runs as dedicated non-root UID; DB file `chmod 600`, owned by that UID |
| **Encryption at rest** | Volume encryption (LUKS/EBS) and/or SQLCipher; never plaintext secrets in the DB |
| **No untrusted input** | Parameterized queries only; never open untrusted `.db` files or run untrusted SQL |
| **Extensions off** | `enable_load_extension(False)` unless explicitly required and reviewed |
| **Patch the *embedded* engine** | Track `sqlite3.sqlite_version`; rebuild to absorb CVE fixes; recompile static binaries |
| **No network FS** | Local disk / EBS only — never NFS/EFS for the live DB |
| **Backups** | Use `.backup`/`VACUUM INTO` (consistent online copy); encrypt and access-restrict backups |
| **Integrity checks** | Periodic `PRAGMA integrity_check;` in monitoring |
| **Durability** | `journal_mode=WAL`, `synchronous=NORMAL` (or `FULL` for max durability), `busy_timeout` set |
| **Auditing** | Log access to the DB file at the OS level; ship to SIEM if required |

### Safe online backup (don't just `cp` a live WAL DB)

```bash
# Consistent snapshot while the DB is in use
sqlite3 app.db ".backup '/backups/app-$(date +%F).db'"
# or, compacted copy
sqlite3 app.db "VACUUM INTO '/backups/app-compact.db';"
```

```python
# Programmatic consistent backup via the online backup API
import sqlite3
src = sqlite3.connect("app.db")
dst = sqlite3.connect("/backups/app.db")
with dst:
    src.backup(dst)          # atomic, consistent, safe while src is live
dst.close(); src.close()
```

---

## 6. Decision Framework (Print This)

```
Is the data written by more than one HOST concurrently?
        │
   ┌────┴────┐
  YES        NO
   │          │
   │     Does it need HA / failover / horizontal scale?
   │          │
   │     ┌────┴────┐
   │    YES        NO
   │     │          │
   ▼     ▼          ▼
 Use a server DB    Is storage a network FS (NFS/EFS)?
 (Postgres/Dynamo)        │
                     ┌────┴────┐
                    YES        NO
                     │          │
                     ▼          ▼
              Use server DB   ✅ SQLite is a great fit
                              (WAL + hardening + backups)
```

---

## Cheatsheet — Part 2 (Security)

```python
# Secure-by-default connection
import sqlite3
conn = sqlite3.connect("app.db", timeout=30)
conn.enable_load_extension(False)               # no arbitrary native code
for p in ("journal_mode=WAL","synchronous=NORMAL",
          "busy_timeout=5000","foreign_keys=ON"):
    conn.execute(f"PRAGMA {p};")

# Parameterized queries ONLY
conn.execute("SELECT * FROM t WHERE k = ?", (user_value,))

# Check the engine version you're actually exposed to
print(sqlite3.sqlite_version)
```

```bash
chmod 600 app.db                          # least privilege
sqlite3 app.db "PRAGMA integrity_check;"  # corruption / tamper check
sqlite3 app.db ".backup '/secure/backup.db'"   # consistent backup
strings app.db | head                     # prove to yourself it's plaintext (then encrypt the volume)
```

---

## The One-Paragraph Answer to "Is SQLite Secure?"

SQLite has **no network attack surface, no auth to bypass, and no privileged daemon to exploit** — which eliminates whole classes of vulnerabilities that plague database servers. In exchange, it gives you **zero built-in access control or encryption**, so security becomes a *filesystem and application* discipline: lock the file down to a non-root service account, encrypt the volume, never store secrets in it, use parameterized queries, refuse untrusted SQL/DB files, disable extensions, and — critically — **patch the embedded engine, not just the OS package**. Get those right and SQLite is a perfectly defensible, often *simpler-to-secure* choice for single-node, read-heavy production workloads.

---

*Found this useful? Star the repo, open an issue with your own SQLite war stories, or PR a correction. Field Notes get better when practitioners push back.*
