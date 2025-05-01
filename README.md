# ssh-clusters-manager

[![PyPI version](https://img.shields.io/pypi/v/ssh-clusters-manager.svg)](https://pypi.org/project/ssh-clusters-manager/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**ssh-clusters-manager** is a lightweight Python library that runs **SSH commands and SFTP transfers in parallel** across many hosts.  
Perfect for fast automation scripts, GPU-benchmark fleets, or any task that needs the same action blasted to multiple servers—without dragging in a heavyweight toolchain.

---

## ✨ Features

| Capability              | Details                                                                                     |
|-------------------------|----------------------------------------------------------------------------------------------|
| **Parallel exec**       | `cluster.run("…")` executes on all hosts concurrently (ThreadPool)                           |
| **Parallel SFTP**       | `cluster.put` / `cluster.get` upload & download files or directories on every host           |
| **YAML / JSON configs** | `SSHCluster.from_yaml("hosts.yml")` or `SSHCluster.from_json("hosts.json")`                  |
| **Strong typing**       | `HostInfo`, `Result` dataclasses with rich helpers                                           |
| **Pure-unit tests**     | Paramiko fully mocked → no SSH needed for CI                                                 |
| **Opt-in integration**  | Real SSH tests to GCP / EC2 etc. when `$SSHMANAGER_RUN_REAL=1`                               |
| **Tiny footprint**      | < 400 LOC (+ Paramiko, PyYAML)                                                               |

---

## 📦 Install

```bash
pip install ssh-clusters-manager
```

<details>
<summary>Poetry users</summary>

```bash
poetry add ssh-clusters-manager
```
</details>

---

## ⚡ Quickstart

### 1 · Create `hosts.yml`

```yaml
- hostname: 34.30.202.192
  username: garvw
  key_filename: ~/.ssh/google_compute_engine

- hostname: 34.29.157.176
  username: garvw
  key_filename: ~/.ssh/google_compute_engine
```

### 2 · Run a command on all servers

```python
from ssh_cluster.cluster import SSHCluster

cluster = SSHCluster.from_yaml("hosts.yml")
results = cluster.run("hostname && uptime")

for host, res in results.items():
    print(f"{host}: {res.short()}")
```

### 3 · Upload / download files (parallel SFTP)

```python
# upload to every host
cluster.put("local.txt", "/tmp/remote.txt")

# download back under a new name
cluster.get("/tmp/remote.txt", "downloaded.txt")
```

---

## 🧩 API Glance

```python
from ssh_cluster.types import HostInfo
from ssh_cluster.cluster import SSHCluster

hosts = [
    HostInfo("10.0.0.1", username="ubuntu", key_filename="~/.ssh/id_rsa"),
    HostInfo.from_mapping(
        {"hostname": "10.0.0.2", "username": "root", "password": "s3cr3t"}
    ),
]

cluster = SSHCluster(hosts, max_workers=8, retry=1)

# run
out = cluster.run("df -h")

# sftp
cluster.put("app.tar.gz", "/tmp/app.tar.gz")
cluster.get("/etc/hosts", "backup/hosts.txt")
```

**`Result` fields:** `success · stdout · stderr · exit_code · elapsed · error`.

---

## 🧪 Tests

### Unit (mocked)

```bash
poetry run pytest tests/test_cluster_unit.py -q -s
```

### Integration (real SSH)

```bash
# Windows CMD
set SSHMANAGER_RUN_REAL=1

# PowerShell
$Env:SSHMANAGER_RUN_REAL = '1'

# Linux / macOS (bash, zsh)
export SSHMANAGER_RUN_REAL=1

# then run the real-SSH integration tests
poetry run pytest tests/test_gcp_cluster.py -q -s

```

Requires a reachable `hosts.yml` in the repo root.

---

## 🤝 Contributing

1. **Fork** → `git checkout -b feat/my-feature`  
2. Add code **and tests**  
3. `poetry run pytest`  
4. Open a **PR** to `main`

---

## 📜 License

MIT — do what you like, credit appreciated.  
See [`LICENSE`](LICENSE).

---

## 🔗 Links

* **PyPI** <https://pypi.org/project/ssh-clusters-manager/>  
* **Author** Gaurav Yadav (<garv.works@outlook.com>)
