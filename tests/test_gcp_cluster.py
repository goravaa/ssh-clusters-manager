import os
import pytest
import yaml
from pathlib import Path

from ssh_cluster.types import HostInfo, SSHConnectionError
from ssh_cluster.cluster import SSHCluster

# ─── Helpers ─────────────────────────────────────────────────────────────

def load_hosts_from_yaml(path: Path) -> list[HostInfo]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a YAML list of hosts")
    return [HostInfo.from_mapping(entry) for entry in data]

# ─── Fixture ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def real_hosts() -> list[HostInfo]:
    # Enable real SSH tests by setting:
    #   CMD:      set SSHMANAGER_RUN_REAL=1
    #   PowerShell: $Env:SSHMANAGER_RUN_REAL = '1'
    if not os.getenv("SSHMANAGER_RUN_REAL"):
        pytest.skip("Skipping real-SSH tests (set SSHMANAGER_RUN_REAL=1)")

    # Locate hosts.yml relative to this test file (two levels up)
    repo_root = Path(__file__).resolve().parents[1]
    hosts_file = repo_root / "hosts.yml"

    # Debug: print where it's looking (uncomment below if needed)
    # print(f"Looking for hosts.yml at {hosts_file} (exists: {hosts_file.exists()})", flush=True)
    if not hosts_file.exists():
        pytest.skip(f"No hosts.yml found at {hosts_file}")

    return load_hosts_from_yaml(hosts_file)

# ─── Tests ────────────────────────────────────────────────────────────────

def test_run_command_on_all_hosts(real_hosts):
    """
    Run `hostname && uptime` on each host and print output.
    """
    try:
        cluster = SSHCluster(real_hosts, connect_timeout=5)
    except SSHConnectionError as e:
        pytest.fail(f"Connection failed: {e}")

    results = cluster.run("hostname && uptime")
    expected = {h.hostname for h in real_hosts}
    assert set(results) == expected

    for host, res in results.items():
        print(f"===== Host: {host} =====", flush=True)
        print(f"STDOUT:\n{res.stdout.strip()}", flush=True)
        print(f"STDERR:\n{res.stderr.strip()}", flush=True)
        assert res.success, f"{host} failed: {res.stderr or res.error}"


def test_put_and_get_on_all_hosts(real_hosts, tmp_path: Path):
    """
    Upload a small file to /tmp, then download it back and print results.
    """
    cluster = SSHCluster(real_hosts)

    # create local file
    local = tmp_path / "hello.txt"
    local.write_text("hello from pytest\n", encoding="utf-8")

    # upload
    put_results = cluster.put(str(local), "/tmp/hello.txt")
    assert all(r.success for r in put_results.values())

    # download
    download_dir = tmp_path / "download"
    download_dir.mkdir()
    get_results = cluster.get("/tmp/hello.txt", str(download_dir / "out.txt"))
    assert all(r.success for r in get_results.values())

    for host, _ in get_results.items():
        data = (download_dir / "out.txt").read_text(encoding="utf-8")
        print(f"Downloaded from {host}: {data.strip()}", flush=True)
        assert "hello from pytest" in data
