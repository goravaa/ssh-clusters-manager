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
"""

from pathlib import Path
from time import perf_counter
from typing import Optional, Mapping
import os

import paramiko
import logging

from .types import (
    CommandEnv,
    HostInfo,
    PathLike,
    Result,
    SSHConnectionError,
)

logger = logging.getLogger("sshmanager.connection")

__all__ = ["SSHConnection"]


def _mkdir_p_sftp(sftp, remote_path):
    """Recursively create directories on remote host with SFTP."""
    parts = Path(remote_path).parts
    cur = ""
    for part in parts:
        cur = os.path.join(cur, part)
        if not cur or cur == "/":
            continue
        try:
            sftp.stat(cur)
        except IOError:
            try:
                sftp.mkdir(cur)
            except Exception:
                pass

class SSHConnection:
    """Thin, safe wrapper around a Paramiko `SSHClient` for one host."""

    def __init__(
        self,
        info: HostInfo,
        *,
        connect_timeout: float | int | None = 10,
    ) -> None:
        self.info = info
        self._cli = paramiko.SSHClient()
        self._cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        attempt = 1
        try:
            logger.debug(
                f"Connecting to {info.hostname}:{info.port} as {info.username}"
            )
            self._cli.connect(
                hostname=info.hostname,
                port=info.port,
                username=info.username,
                password=info.password,
                key_filename=info.key_filename,
                timeout=connect_timeout,
            )
            logger.info(f"Connected to {info.hostname} on attempt {attempt}")
        except Exception as exc:
            logger.error(f"Connection failed for {info.hostname}: {exc}")
            self.close()
            raise SSHConnectionError(str(exc)) from exc

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
            logger.debug(f"Executing on {self.info.hostname}: {command}")
            stdin, stdout, stderr = self._cli.exec_command(command, timeout=timeout)
            rc = stdout.channel.recv_exit_status()
            result = Result(
                success=rc == 0,
                exit_code=rc,
                stdout=stdout.read().decode(),
                stderr=stderr.read().decode(),
                elapsed=perf_counter() - start,
            )
            logger.info(
                f"Executed command on {self.info.hostname}: {command} "
                f"({result.short()})"
            )
            return result
        except Exception as exc:  # noqa: BLE001  (broad but wrapped)
            logger.error(
                f"Execution failed on {self.info.hostname}: {exc} (cmd: {command})"
            )
            return Result(success=False, error=str(exc), elapsed=perf_counter() - start)

    def put(self, local: PathLike, remote: str) -> Result:
        start = perf_counter()
        try:
            logger.debug(f"Uploading {local} to {self.info.hostname}:{remote}")
            with self._cli.open_sftp() as sftp:
                sftp.put(str(local), remote)
            result = Result(success=True, elapsed=perf_counter() - start)
            logger.info(
                f"Uploaded {local} to {self.info.hostname}:{remote} ({result.short()})"
            )
            return result
        except Exception as exc:
            logger.error(
                f"PUT failed on {self.info.hostname}: {exc} (local: {local}, remote: {remote})"
            )
            return Result(success=False, error=str(exc), elapsed=perf_counter() - start)

    def get(self, remote: str, local: PathLike) -> Result:
        start = perf_counter()
        try:
            logger.debug(f"Downloading {self.info.hostname}:{remote} to {local}")
            Path(local).parent.mkdir(parents=True, exist_ok=True)
            with self._cli.open_sftp() as sftp:
                sftp.get(remote, str(local))
            result = Result(success=True, elapsed=perf_counter() - start)
            logger.info(
                f"Downloaded {self.info.hostname}:{remote} to {local} ({result.short()})"
            )
            return result
        except Exception as exc:
            logger.error(
                f"GET failed on {self.info.hostname}: {exc} (remote: {remote}, local: {local})"
            )
            return Result(success=False, error=str(exc), elapsed=perf_counter() - start)

    def put_dir(
        self,
        local_dir: PathLike,
        remote_dir: str,
        skip_size_mb: float = None,
        skip_pattern: str = None,
        overwrite: bool = False,
        show_progress: bool = True,
    ) -> Result:
        start = perf_counter()
        local_dir = Path(local_dir)
        counters = {'n_files': 0, 'n_skipped': 0, 'n_errors': 0}
        try:
            with self._cli.open_sftp() as sftp:
                for root, dirs, files in os.walk(local_dir):
                    rel_root = Path(root).relative_to(local_dir)
                    remote_root = str(Path(remote_dir) / rel_root)
                    _mkdir_p_sftp(sftp, remote_root)
                    for fname in files:
                        local_path = Path(root) / fname
                        remote_path = str(Path(remote_root) / fname)

                        # Skip by pattern
                        if skip_pattern and local_path.match(skip_pattern):
                            if show_progress:
                                logger.info(f"Skipping {local_path} (pattern: {skip_pattern})")
                            counters['n_skipped'] += 1
                            continue

                        # Skip by size
                        if skip_size_mb and local_path.stat().st_size > skip_size_mb * 1024 * 1024:
                            if show_progress:
                                logger.info(f"Skipping {local_path} (size > {skip_size_mb}MB)")
                            counters['n_skipped'] += 1
                            continue

                        # Skip if remote exists (and not overwrite)
                        try:
                            rstat = sftp.stat(remote_path)
                            if not overwrite and rstat.st_size == local_path.stat().st_size:
                                if show_progress:
                                    logger.info(f"Skipping {local_path} (already exists, same size)")
                                counters['n_skipped'] += 1
                                continue
                        except Exception:
                            pass  # File does not exist or can't stat

                        # Upload
                        try:
                            if show_progress:
                                logger.info(f"Uploading {local_path} -> {remote_path}")
                            sftp.put(str(local_path), remote_path)
                            counters['n_files'] += 1
                        except Exception as e:
                            logger.error(f"Error uploading {local_path}: {e}")
                            counters['n_errors'] += 1
            elapsed = perf_counter() - start
            return Result(
                success=(counters['n_errors'] == 0),
                stdout=f"Uploaded: {counters['n_files']}, Skipped: {counters['n_skipped']}, Errors: {counters['n_errors']}",
                elapsed=elapsed,
                error=None if counters['n_errors'] == 0 else f"{counters['n_errors']} files failed",
            )
        except Exception as e:
            return Result(success=False, error=str(e), elapsed=perf_counter() - start)

    def get_dir(
        self,
        remote_dir: str,
        local_dir: PathLike,
        skip_size_mb: float = None,
        skip_pattern: str = None,
        overwrite: bool = False,
        show_progress: bool = True,
    ) -> Result:
        start = perf_counter()
        local_dir = Path(local_dir)
        counters = {'n_files': 0, 'n_skipped': 0, 'n_errors': 0}
        try:
            with self._cli.open_sftp() as sftp:
                def _recursive_download(sftp, remote_dir, local_dir):
                    Path(local_dir).mkdir(parents=True, exist_ok=True)
                    for entry in sftp.listdir_attr(remote_dir):
                        rpath = os.path.join(remote_dir, entry.filename)
                        lpath = Path(local_dir) / entry.filename
                        if entry.st_mode & 0o40000:  # directory
                            _recursive_download(sftp, rpath, lpath)
                        else:
                            # Skip by pattern
                            if skip_pattern and lpath.match(skip_pattern):
                                if show_progress:
                                    logger.info(f"Skipping {rpath} (pattern: {skip_pattern})")
                                counters['n_skipped'] += 1
                                continue
                            # Skip by size
                            if skip_size_mb and entry.st_size > skip_size_mb * 1024 * 1024:
                                if show_progress:
                                    logger.info(f"Skipping {rpath} (size > {skip_size_mb}MB)")
                                counters['n_skipped'] += 1
                                continue
                            # Skip if local exists (and not overwrite)
                            if lpath.exists() and not overwrite and lpath.stat().st_size == entry.st_size:
                                if show_progress:
                                    logger.info(f"Skipping {rpath} (already downloaded, same size)")
                                counters['n_skipped'] += 1
                                continue
                            # Download
                            try:
                                if show_progress:
                                    logger.info(f"Downloading {rpath} -> {lpath}")
                                sftp.get(rpath, str(lpath))
                                counters['n_files'] += 1
                            except Exception as e:
                                logger.error(f"Error downloading {rpath}: {e}")
                                counters['n_errors'] += 1

                _recursive_download(sftp, remote_dir, local_dir)
            elapsed = perf_counter() - start
            return Result(
                success=(counters['n_errors'] == 0),
                stdout=f"Downloaded: {counters['n_files']}, Skipped: {counters['n_skipped']}, Errors: {counters['n_errors']}",
                elapsed=elapsed,
                error=None if counters['n_errors'] == 0 else f"{counters['n_errors']} files failed",
            )
        except Exception as e:
            return Result(success=False, error=str(e), elapsed=perf_counter() - start)

    def close(self) -> None:  # noqa: D401
        """Close the underlying SSH connection (idempotent)."""
        logger.debug(f"Closing SSH connection to {self.info.hostname}")
        try:
            self._cli.close()
            logger.info(f"Closed connection to {self.info.hostname}")
        except Exception:  # pragma: no cover
            logger.warning(f"Exception when closing SSH connection to {self.info.hostname}")

    def __enter__(self) -> "SSHConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        """Always close connection on block exit."""
        self.close()
