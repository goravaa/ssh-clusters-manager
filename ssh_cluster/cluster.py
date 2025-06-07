# ssh_cluster/cluster.py
from __future__ import annotations

"""
High-level, thread-safe SSH cluster orchestration built on Paramiko.

External surface:
    └─ SSHCluster([...]).put("local.tar", "/tmp/local.tar")
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from typing import Dict, Iterable, List, Mapping, Optional
from pathlib import Path
import os
import time
import paramiko

from .types import (
    CommandEnv,
    HostInfo,
    PathLike,
    Result,
    SSHConnectionError,
)

import logging
logger = logging.getLogger("sshmanager.cluster")

__all__ = ["SSHCluster"]

# ---------------------------------------------------------------------------#
# Internal -- single-host wrapper
# ---------------------------------------------------------------------------#

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

class _SSHClient:
    """Thin wrapper around a single Paramiko client."""

    def __init__(self, info: HostInfo, timeout: int | float | None) -> None:
        self.info = info
        self._cli = paramiko.SSHClient()
        self._cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            logger.debug(f"Connecting to {info.hostname}:{info.port} as {info.username}")
            self._cli.connect(
                hostname=info.hostname,
                port=info.port,
                username=info.username,
                password=info.password,
                key_filename=info.key_filename,
                timeout=timeout,
            )
            logger.info(f"Connected to {info.hostname}")
        except Exception as exc:
            logger.error(f"SSH connection failed for {info.hostname}: {exc}")
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
            logger.debug(f"Executing on {self.info.hostname}: {cmd}")
            _stdin, stdout, stderr = self._cli.exec_command(cmd, timeout=timeout)
            rc = stdout.channel.recv_exit_status()
            result = Result(
                success=rc == 0,
                exit_code=rc,
                stdout=stdout.read().decode(),
                stderr=stderr.read().decode(),
                elapsed=time.perf_counter() - start,
            )
            logger.info(f"Executed command on {self.info.hostname}: {result.short()}")
            return result
        except Exception as exc:
            logger.error(f"Execution error on {self.info.hostname}: {exc}")
            return Result(success=False, error=str(exc), elapsed=time.perf_counter() - start)

    # --------------------------------------------------------------- put/get -
    def put(self, local: PathLike, remote: str) -> Result:
        start = time.perf_counter()
        try:
            logger.debug(f"Uploading {local} to {self.info.hostname}:{remote}")
            with self._cli.open_sftp() as sftp:
                sftp.put(str(local), remote)
            result = Result(success=True, elapsed=time.perf_counter() - start)
            logger.info(f"Uploaded {local} to {self.info.hostname}:{remote} ({result.short()})")
            return result
        except Exception as exc:
            logger.error(f"PUT error on {self.info.hostname}: {exc}")
            return Result(success=False, error=str(exc), elapsed=time.perf_counter() - start)

    def get(self, remote: str, local: PathLike) -> Result:
        start = time.perf_counter()
        try:
            logger.debug(f"Downloading {self.info.hostname}:{remote} to {local}")
            with self._cli.open_sftp() as sftp:
                sftp.get(remote, str(local))
            result = Result(success=True, elapsed=time.perf_counter() - start)
            logger.info(f"Downloaded {self.info.hostname}:{remote} to {local} ({result.short()})")
            return result
        except Exception as exc:
            logger.error(f"GET error on {self.info.hostname}: {exc}")
            return Result(success=False, error=str(exc), elapsed=time.perf_counter() - start)

    def put_dir(
        self,
        local_dir: PathLike,
        remote_dir: str,
        skip_size_mb: float = None,
        skip_pattern: str = None,
        overwrite: bool = False,
        show_progress: bool = True,
    ) -> Result:
        start = time.perf_counter()
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
            elapsed = time.perf_counter() - start
            return Result(
                success=(counters['n_errors'] == 0),
                stdout=f"Uploaded: {counters['n_files']}, Skipped: {counters['n_skipped']}, Errors: {counters['n_errors']}",
                elapsed=elapsed,
                error=None if counters['n_errors'] == 0 else f"{counters['n_errors']} files failed",
            )
        except Exception as e:
            return Result(success=False, error=str(e), elapsed=time.perf_counter() - start)

    def get_dir(
        self,
        remote_dir: str,
        local_dir: PathLike,
        skip_size_mb: float = None,
        skip_pattern: str = None,
        overwrite: bool = False,
        show_progress: bool = True,
    ) -> Result:
        start = time.perf_counter()
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
            elapsed = time.perf_counter() - start
            return Result(
                success=(counters['n_errors'] == 0),
                stdout=f"Downloaded: {counters['n_files']}, Skipped: {counters['n_skipped']}, Errors: {counters['n_errors']}",
                elapsed=elapsed,
                error=None if counters['n_errors'] == 0 else f"{counters['n_errors']} files failed",
            )
        except Exception as e:
            return Result(success=False, error=str(e), elapsed=time.perf_counter() - start)

    def close(self) -> None: 
        """Close underlying SSH connection."""
        logger.debug(f"Closing connection to {self.info.hostname}")
        try:
            self._cli.close()
        except Exception:
            pass

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

        logger.info(f"Initializing SSHCluster with {len(self._hosts)} hosts")
        self._connect_all()  # also registers clean-up

    # ----------------------------------------------------------- internals
    def _connect_all(self) -> None:
        for host in self._hosts:
            attempt = 0
            while True:
                try:
                    logger.debug(f"Connecting to {host.hostname} (attempt {attempt+1})")
                    cli = _SSHClient(host, timeout=self._timeout)
                    self._clients[host.hostname] = cli
                    break
                except SSHConnectionError as exc:
                    logger.warning(f"Connection failed to {host.hostname}: {exc}")
                    if attempt >= self._retry:
                        raise
                    attempt += 1
                    time.sleep(2 ** attempt)
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
        logger.info(f"Running '{fn_name}' in parallel on {len(self._clients)} hosts")
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
        logger.info(f"Running command on cluster: '{command}'")
        return self._parallel("exec", command, timeout, env)

    def put(self, local: PathLike, remote: str) -> Dict[str, Result]:
        """Upload *local* file/dir to *remote* path on every host."""
        logger.info(f"Uploading {local} to {remote} on all hosts")
        return self._parallel("put", local, remote)

    def get(self, remote: str, local: PathLike) -> Dict[str, Result]:
        """Download *remote* file/dir from every host."""
        logger.info(f"Downloading {remote} to {local} from all hosts")
        return self._parallel("get", remote, local)

    def put_dir(
        self,
        local_dir: PathLike,
        remote_dir: str,
        skip_size_mb: float = None,
        skip_pattern: str = None,
        overwrite: bool = False,
        show_progress: bool = True,
    ) -> Dict[str, Result]:
        """Upload an entire directory recursively to every host."""
        logger.info(f"Uploading directory {local_dir} to {remote_dir} on all hosts")
        return self._parallel(
            "put_dir",
            local_dir,
            remote_dir,
            skip_size_mb,
            skip_pattern,
            overwrite,
            show_progress,
        )

    def get_dir(
        self,
        remote_dir: str,
        local_dir: PathLike,
        skip_size_mb: float = None,
        skip_pattern: str = None,
        overwrite: bool = False,
        show_progress: bool = True,
    ) -> Dict[str, Result]:
        """Download an entire directory recursively from every host."""
        logger.info(f"Downloading directory {remote_dir} to {local_dir} from all hosts")
        return self._parallel(
            "get_dir",
            remote_dir,
            local_dir,
            skip_size_mb,
            skip_pattern,
            overwrite,
            show_progress,
        )

    # Convenience ----------------------------------------------------------
    def __getitem__(self, hostname: str) -> _SSHClient:
        return self._clients[hostname]

    def hosts(self) -> List[str]:
        return list(self._clients.keys())
