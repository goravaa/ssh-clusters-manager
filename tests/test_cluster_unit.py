"""
Pure-unit tests: patch paramiko.SSHClient so no real SSH is required.
"""

from pathlib import Path
from typing import Dict

import pytest
from ssh_cluster.cluster import SSHCluster
from ssh_cluster.types import HostInfo, Result

# ------------------------------------------------------------------ fixtures
@pytest.fixture()
def fake_hosts() -> list[HostInfo]:
    return [
        HostInfo(hostname="hostA", username="user"),
        HostInfo(hostname="hostB", username="user"),
    ]


@pytest.fixture()
def monkey_paramiko(mocker):
    """Replace paramiko.SSHClient with a fast fake."""
    class _Dummy:
        def __init__(self, *a, **kw):
            self.cmd_log: list[str] = []

        # ---- the three methods cluster.py currently calls
        def set_missing_host_key_policy(self, _): ...

        def connect(self, *a, **kw): ...

        def exec_command(self, cmd, timeout=None):
            self.cmd_log.append(cmd)
            # stdin is unused → return None placeholder
            return (
                None,
                _IO(b"OK\n"),          # stdout
                _IO(b""),              # stderr
            )

        def open_sftp(self):
            return _SFTP()

        def close(self): ...

    class _IO:
        def __init__(self, data: bytes):
            self._data = data
            self.channel = self  # cheap hack so recv_exit_status is available

        def read(self) -> bytes:
            return self._data

        def recv_exit_status(self) -> int:
            return 0  # success

    class _SFTP:
        def put(self, *_): ...
        def get(self, *_): ...
        def __enter__(self): return self
        def __exit__(self, *a): ...

    mocker.patch("ssh_cluster.connection.paramiko.SSHClient", _Dummy)
    mocker.patch("ssh_cluster.cluster.paramiko.SSHClient", _Dummy)
    return _Dummy  # if caller wants to inspect

# ------------------------------------------------------------------ tests
def test_parallel_run_returns_results(fake_hosts, monkey_paramiko):
    cluster = SSHCluster(fake_hosts)
    results: Dict[str, Result] = cluster.run("echo hi")

    assert set(results) == {"hostA", "hostB"}
    assert all(r.success and r.stdout.strip() == "OK" for r in results.values())


def test_put_and_get(fake_hosts, monkey_paramiko, tmp_path: Path):
    cluster = SSHCluster(fake_hosts)
    # .put() mocked away -> should report success
    res_put = cluster.put("dummy.txt", "/tmp/dummy.txt")
    assert all(r.success for r in res_put.values())

    # .get() mocked away -> writes nothing but returns success
    res_get = cluster.get("/tmp/dummy.txt", tmp_path / "out.txt")
    assert all(r.success for r in res_get.values())
