# ssh_cluster/connection.py
from __future__ import annotations

"""
Single-host SSH helper used internally by SSHCluster, but you can import and
use it stand-alone:

    >>> from ssh_cluster.connection import SSHConnection
    >>> from ssh_cluster.types import HostInfo
    >>> conn = SSHConnection(HostInfo("1.2.3.4", "ec2-user"))
    >>> r = conn.exec("hostname && uptime")
    >>> print(r.stdout)

The class is:

  • Fully typed  (PEP 484) — IDE auto-completion friendly
  • Context-manager aware        (with SSHConnection(...) as c:)
  • Cleanly converts env vars    {'FOO': 'bar'} → "FOO='bar' CMD"
  • Handles timeouts and returns Result objects instead of raw Paramiko streams
  • Wraps Paramiko-only errors into SSHConnectionError for uniform handling
"""

from pathlib import Path
from time import perf_counter
from typing import Optional

import paramiko

from .types import (
    CommandEnv,
    HostInfo,
    PathLike,
    Result,
    SSHConnectionError,
)

__all__ = ["SSHConnection"]


class SSHConnection:
    """Thin, safe wrapper around a Paramiko `SSHClient` for one host."""

    # ------------------------------------------------------------------ init
    def __init__(
        self,
        info: HostInfo,
        *,
        connect_timeout: float | int | None = 10,
    ) -> None:
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
                timeout=connect_timeout,
            )
        except Exception as exc:
            self.close()
            raise SSHConnectionError(str(exc)) from exc

    # ------------------------------------------------- public API helpers --
    def exec(
        self,
        command: str,
        *,
        timeout: float | int | None = None,
        env: Optional[CommandEnv] = None,
    ) -> Result:
        """
        Run *command* and return a :class:`Result`.

        Environment vars (if provided) are prepended as `VAR='val' ... CMD`.
        """
        start = perf_counter()
        try:
            if env:
                exports = " ".join(f"{k}='{v}'" for k, v in env.items()) + " "
                command = exports + command

            stdin, stdout, stderr = self._cli.exec_command(command, timeout=timeout)
            rc = stdout.channel.recv_exit_status()

            return Result(
                success=rc == 0,
                exit_code=rc,
                stdout=stdout.read().decode(),
                stderr=stderr.read().decode(),
                elapsed=perf_counter() - start,
            )
        except Exception as exc:  # noqa: BLE001  (broad but wrapped)
            return Result(success=False, error=str(exc), elapsed=perf_counter() - start)

    # ----------------------------------------------------- SFTP wrappers ---
    def put(self, local: PathLike, remote: str) -> Result:
        start = perf_counter()
        try:
            with self._cli.open_sftp() as sftp:
                sftp.put(str(local), remote)
            return Result(success=True, elapsed=perf_counter() - start)
        except Exception as exc:
            return Result(success=False, error=str(exc), elapsed=perf_counter() - start)

    def get(self, remote: str, local: PathLike) -> Result:
        start = perf_counter()
        try:
            Path(local).parent.mkdir(parents=True, exist_ok=True)
            with self._cli.open_sftp() as sftp:
                sftp.get(remote, str(local))
            return Result(success=True, elapsed=perf_counter() - start)
        except Exception as exc:
            return Result(success=False, error=str(exc), elapsed=perf_counter() - start)

    # ------------------------------------------------------------------ util
    def close(self) -> None:  # noqa: D401
        """Close the underlying SSH connection (idempotent)."""
        try:
            self._cli.close()
        except Exception:  # pragma: no cover
            pass

    # ---------------------------------------------------- context manager --
    def __enter__(self) -> "SSHConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        """Always close connection on block exit."""
        self.close()
