# ssh_cluster/cluster.py
from __future__ import annotations

"""
High-level, thread-safe SSH cluster orchestration built on Paramiko.

External surface:
    ├─ SSHCluster.from_yaml("hosts.yml").run("uptime")
    └─ SSHCluster([...]).put("local.tar", "/tmp/local.tar")
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

import json
import time

import paramiko
import yaml  # type: ignore

from .types import (
    CommandEnv,
    HostInfo,
    PathLike,
    Result,
    SSHConnectionError,
)

__all__ = ["SSHCluster"]

# ---------------------------------------------------------------------------#
# Internal -- single-host wrapper
# ---------------------------------------------------------------------------#


class _SSHClient:
    """Thin wrapper around a single Paramiko client."""

    def __init__(self, info: HostInfo, timeout: int | float | None) -> None:
        self.info = info
        self._cli = paramiko.SSHClient()
        self._cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            self._cli.connect(
                hostname=info.hostname,
                port=info.port,
                username=info.username,
                password=info.password,
                key_filename=info.key_filename,
                timeout=timeout,
            )
        except Exception as exc:
            raise SSHConnectionError(str(exc)) from exc

    # -------------------------------------------------------------- exec ----
    def exec(
        self,
        cmd: str,
        timeout: int | float | None,
        env: Optional[CommandEnv],
    ) -> Result:
        start = time.perf_counter()
        try:
            if env:
                env_export = " ".join(f"{k}='{v}'" for k, v in env.items()) + " "
                cmd = env_export + cmd
            _stdin, stdout, stderr = self._cli.exec_command(cmd, timeout=timeout)
            rc = stdout.channel.recv_exit_status()
            return Result(
                success=rc == 0,
                exit_code=rc,
                stdout=stdout.read().decode(),
                stderr=stderr.read().decode(),
                elapsed=time.perf_counter() - start,
            )
        except Exception as exc:
            return Result(success=False, error=str(exc), elapsed=time.perf_counter() - start)

    # --------------------------------------------------------------- put/get -
    def put(self, local: PathLike, remote: str) -> Result:
        start = time.perf_counter()
        try:
            with self._cli.open_sftp() as sftp:
                sftp.put(str(local), remote)
            return Result(success=True, elapsed=time.perf_counter() - start)
        except Exception as exc:
            return Result(success=False, error=str(exc), elapsed=time.perf_counter() - start)

    def get(self, remote: str, local: PathLike) -> Result:
        start = time.perf_counter()
        try:
            with self._cli.open_sftp() as sftp:
                sftp.get(remote, str(local))
            return Result(success=True, elapsed=time.perf_counter() - start)
        except Exception as exc:
            return Result(success=False, error=str(exc), elapsed=time.perf_counter() - start)

    def close(self) -> None:  # noqa: D401  (simple)
        """Close underlying SSH connection."""
        self._cli.close()


# ---------------------------------------------------------------------------#
# Public cluster
# ---------------------------------------------------------------------------#


class SSHCluster(ExitStack):
    """Parallel SSH helper."""

    DEFAULT_WORKERS = 12

    # ------------------------------------------------------------------ init
    def __init__(
        self,
        hosts: Iterable[HostInfo | Mapping[str, str]],
        *,
        max_workers: int | None = None,
        connect_timeout: int | float | None = 10,
        retry: int = 0,
    ) -> None:
        super().__init__()
        self._hosts: List[HostInfo] = [
            h if isinstance(h, HostInfo) else HostInfo.from_mapping(h) for h in hosts
        ]
        self._workers = max_workers or min(len(self._hosts), self.DEFAULT_WORKERS)
        self._timeout = connect_timeout
        self._retry = retry
        self._clients: Dict[str, _SSHClient] = {}

        self._connect_all()  # also registers clean-up

    # -------------------------------------------------------------- loaders
    @classmethod
    def from_yaml(cls, file: PathLike, **kw) -> "SSHCluster":
        with open(file, "r", encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh), **kw)

    @classmethod
    def from_json(cls, file: PathLike, **kw) -> "SSHCluster":
        return cls(json.loads(Path(file).read_text("utf-8")), **kw)

    # ----------------------------------------------------------- internals
    def _connect_all(self) -> None:
        for host in self._hosts:
            attempt = 0
            while True:
                try:
                    cli = _SSHClient(host, timeout=self._timeout)
                    self._clients[host.hostname] = cli
                    break
                except SSHConnectionError:
                    if attempt >= self._retry:
                        raise
                    attempt += 1
                    time.sleep(2**attempt)
        # ensure every connection is closed on ExitStack close
        for cli in self._clients.values():
            self.callback(cli.close)

    # -------------------------------------------------------------- helpers
    def _parallel(
        self,
        fn_name: str,
        *args,
        **kw,
    ) -> Dict[str, Result]:
        results: Dict[str, Result] = {}
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            fut_map = {
                pool.submit(getattr(cli, fn_name), *args, **kw): host
                for host, cli in self._clients.items()
            }
            for fut in as_completed(fut_map):
                results[fut_map[fut]] = fut.result()
        return results

    # -------------------------------------------------------------- public -
    def run(
        self,
        command: str,
        *,
        timeout: int | float | None = None,
        env: Optional[CommandEnv] = None,
    ) -> Dict[str, Result]:
        """Execute *command* on all hosts in parallel."""
        return self._parallel("exec", command, timeout, env)

    def put(self, local: PathLike, remote: str) -> Dict[str, Result]:
        """Upload *local* file/dir to *remote* path on every host."""
        return self._parallel("put", local, remote)

    def get(self, remote: str, local: PathLike) -> Dict[str, Result]:
        """Download *remote* file/dir from every host."""
        return self._parallel("get", remote, local)

    # Convenience ----------------------------------------------------------
    def __getitem__(self, hostname: str) -> _SSHClient:
        return self._clients[hostname]

    def hosts(self) -> List[str]:
        return list(self._clients.keys())
