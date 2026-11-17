"""Read Git configuration snapshots using Git's own configuration parser."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitConfigError(RuntimeError):
    """A Git configuration snapshot could not be loaded."""


_cache: dict[Path, dict[str, list[str | None]]] = {}


def clear_cache() -> None:
    """Discard snapshots for all directories."""
    _cache.clear()


def _normalize_key(key: str) -> str:
    section, separator, remainder = key.partition(".")
    subsection, dot, variable = remainder.rpartition(".")
    return section.lower() + separator + subsection + dot + variable.lower()


def _parse_snapshot(output: bytes) -> dict[str, list[str | None]]:
    entries: dict[str, list[str | None]] = {}
    if not output:
        return entries
    fields = output.split(b"\0")
    if fields[-1] or len(fields) % 2 != 1:
        raise GitConfigError("Invalid Git configuration snapshot")
    for scope, record in zip(fields[0:-1:2], fields[1::2]):
        if scope not in {b"system", b"global", b"local", b"worktree", b"command"}:
            raise GitConfigError("Invalid Git configuration snapshot")
        key, separator, value = record.partition(b"\n")
        if not key:
            raise GitConfigError("Invalid Git configuration snapshot")
        entries.setdefault(_normalize_key(os.fsdecode(key)), []).append(
            os.fsdecode(value) if separator else None
        )
    return entries


def _snapshot(cwd: str | Path | None) -> dict[str, list[str | None]]:
    directory = Path.cwd().resolve() if cwd is None else Path(cwd).resolve()
    if directory not in _cache:
        try:
            result = subprocess.run(
                ["git", "config", "--null", "--show-scope", "--includes", "--list"],
                cwd=directory,
                capture_output=True,
                check=False,
            )
        except OSError:
            raise GitConfigError("Could not run Git configuration query") from None
        if result.returncode:
            raise GitConfigError("Git configuration query failed")
        _cache[directory] = _parse_snapshot(result.stdout)
    return _cache[directory]


def get(
    key: str, cwd: str | Path | None = None, *, default: str | None = None,
) -> str | None:
    """Return the last value for key, or default for an absent key."""
    values = _snapshot(cwd).get(_normalize_key(key))
    return values[-1] if values else default


def get_all(key: str, cwd: str | Path | None = None) -> list[str | None]:
    """Return all values in Git read order; None denotes a valueless entry."""
    return list(_snapshot(cwd).get(_normalize_key(key), ()))
