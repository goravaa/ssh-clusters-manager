from __future__ import annotations

"""ssh_cluster/types.py
========================
Common dataclasses and type aliases shared across the *ssh_cluster* package.
Keeping them in a single module avoids circular-import headaches and ensures
API consistency.
"""

from dataclasses import dataclass
from typing import Mapping, TypedDict, Union

__all__ = [
    "HostInfo",
    "Result",
    "CommandEnv",
    "PathLike",
    "SSHConnectionError",
]

# ---------------------------------------------------------------------------
# Re-usable primitives
# ---------------------------------------------------------------------------

PathLike = str  # at runtime we accept str/Path; pass as str internally
CommandEnv = Mapping[str, str]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SSHConnectionError(Exception):
    """Raised when connection or authentication fails on a single host."""


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class HostInfo:
    """Minimal information required to establish an SSH session."""

    hostname: str
    port: int = 22
    username: str | None = None
    password: str | None = None
    key_filename: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, str]) -> "HostInfo":
        """Coerce a *dict-like* object (JSON/YAML) into :class:`HostInfo`."""
        return cls(
            hostname=data["hostname"],
            port=int(data.get("port", 22)),
            username=data.get("username"),
            password=data.get("password"),
            key_filename=data.get("key_filename"),
        )


@dataclass(slots=True)
class Result:
    """Outcome of a remote operation (exec or SFTP)."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    elapsed: float = 0.0
    timed_out: bool = False
    error: str | None = None  # populated when *success* is False

    # Helpful helpers --------------------------------------------------

    def __bool__(self) -> bool:  # allow ``if result:``
        return self.success

    def short(self) -> str:
        """Single-line summary (useful for logs)."""
        if self.success:
            return f"OK ({self.elapsed:.2f}s)"
        return f"ERR: {self.error or self.stderr.strip()[:60]}…"
