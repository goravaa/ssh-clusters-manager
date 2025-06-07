# SSHManager

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

A lightweight Python library for managing and executing commands across multiple remote servers over SSH in parallel.

---

`SSHManager` provides a simple and intuitive interface for automating tasks on one or many remote machines simultaneously. It's designed to be easy to integrate into any project, offering abstractions for single hosts, clusters of hosts, and even groups of clusters.

## Features

-   🚀 **Parallel Execution**: Run commands and file operations on multiple hosts at once.
-   🎛️ **Cluster Abstraction**: Group hosts into a `SSHCluster` to manage them as a single unit.
-   🛰️ **Single-Host Control**: Operate on individual servers with the `SSHConnection` class when needed.
-   💻 **Remote Command Execution**: Execute any shell command and get structured results per host.
-   📁 **File & Directory Transfers**: Recursively upload/download files and entire directories (`put`, `get`, `put_dir`, `get_dir`).
-   🔑 **Flexible Authentication**: Supports both password and SSH private key authentication.
-   📝 **Strongly Typed**: Built with `dataclass` models for clear and predictable interfaces.
-   🪵 **Simple Logging**: Uses the standard Python `logging` module, which is easily configurable by the user.

## Installation

`SSHManager` relies on the `paramiko` library as its SSH backend.

1.  **Install the dependency:**
    ```bash
    pip install paramiko
    ```

2.  **Add the library to your project:**
    This library is not on PyPI. To use it, simply copy the `sshmanager` directory into your project's source tree.

## Core Concepts

-   **HostInfo**: A `dataclass` that holds all the connection details for a single host (hostname, port, username, credentials, etc.).
-   **Result**: A `dataclass` that captures the outcome of an operation (command execution or file transfer), including stdout, stderr, exit code, and success status.
-   **SSHConnection**: The low-level class for managing a connection and operations on a single host.
-   **SSHCluster**: The primary interface for parallel operations. It manages a pool of `SSHConnection` objects for a list of hosts.
-   **ClusterManager**: An optional high-level utility to manage multiple named clusters for more complex workflows.

## Quick Usage

Here are some common examples to get you started.

### 1. Define Hosts and Create a Cluster

First, define your target machines using `HostInfo`. You can mix and match password and key-based authentication.

```python
from sshmanager.cluster import SSHCluster
from sshmanager.types import HostInfo

# Define hosts with different authentication methods
hosts = [
    HostInfo(hostname="1.2.3.4", username="root", password="your_secure_password"),
    HostInfo(hostname="server.example.com", username="admin", key_filename="~/.ssh/id_rsa"),
    HostInfo(hostname="1.2.3.6", username="user", port=2222, password="another_password"),
]

# Create a cluster instance
cluster = SSHCluster(hosts)
```

### 2. Run Commands in Parallel

Execute a command across all hosts in the cluster. The results are returned as a dictionary mapping each host's IP/hostname to its `Result` object.

```python
# Run a command on all hosts
results = cluster.run("uname -a")

# Process the results
print("--- System Information ---")
for host, res in results.items():
    if res.success:
        print(f"✅ {host}: {res.stdout.strip()}")
    else:
        print(f"❌ {host}: Failed with error: {res.stderr.strip()}")
```

### 3. Upload and Download Files

Transfer files to and from all remote machines.

```python
# Upload a single local file to a remote destination on all hosts
cluster.put("local_script.sh", "/usr/local/bin/run.sh")

# Download a single file from all hosts to a local directory
# The filename will be prefixed with the host's IP to avoid collisions
cluster.get("/var/log/app.log", "logs/")
```

### 4. Transfer Directories Recursively

You can also transfer entire directory trees.

```python
# Upload a local directory to a remote location
cluster.put_dir("local_configs/", "/etc/app_configs/")

# Download a remote directory from all hosts
cluster.get_dir("/var/www/html", "backup/www/")
```

### 5. Advanced: Single-Host Connection

For tasks that don't require parallelism, you can work with a single host.

```python
from sshmanager.connection import SSHConnection
from sshmanager.types import HostInfo

host_info = HostInfo(hostname="1.2.3.4", username="root", password="your_secure_password")

with SSHConnection(host_info) as conn:
    res = conn.exec("hostname && uptime")
    if res.success:
        print(res.stdout)
```

## API Reference

### `HostInfo` Dataclass

Defines the parameters for a connection.

-   `hostname` (str): The server hostname or IP address.
-   `port` (int, optional): The SSH port. Defaults to `22`.
-   `username` (str, optional): The user to connect as. Defaults to the current user.
-   `password` (str, optional): The user's password for authentication.
-   `key_filename` (str, optional): Path to the private SSH key for authentication.
-   `label` (str, optional): A custom name or label for the host.

### `Result` Dataclass

Captures the result of an operation on a single host.

-   `success` (bool): `True` if the operation completed successfully, `False` otherwise.
-   `stdout` (str): The standard output from a command.
-   `stderr` (str): The standard error from a command.
-   `exit_code` (int): The exit code of the command (e.g., `0` for success).
-   `elapsed` (float): The time taken for the operation in seconds.
-   `error` (Exception): The exception object if one was raised during the operation.

## Logging

The library uses the root logger named `"sshmanager"`. You can easily configure its verbosity and output destination using Python's standard `logging` module.

For example, to enable detailed `DEBUG` level logging:

```python
import logging

# Configure logging to show all debug messages from the library
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Your SSHManager code here...
```

To see only informational messages and errors, use `logging.INFO`.

## Contributing

Contributions are welcome! If you find a bug or have a feature request, please open an issue. If you'd like to contribute code, please open a pull request.
