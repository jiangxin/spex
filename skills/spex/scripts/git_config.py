"""Read Git configuration snapshots using Git's own configuration parser."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitConfigError(RuntimeError):
    """A Git configuration snapshot could not be loaded."""


_SCOPES = ("system", "global", "local", "worktree", "command")
_cache: dict[Path, dict[str, dict[str, list[str | None]]]] = {}
_stale_local: set[Path] = set()


def clear_cache() -> None:
    """Discard snapshots for all directories."""
    _cache.clear()
    _stale_local.clear()


def _may_be_repository(directory: Path) -> bool:
    if "GIT_DIR" in os.environ:
        return True
    return any(
        (parent / ".git").exists()
        or ((parent / "HEAD").is_file() and (parent / "objects").is_dir())
        for parent in (directory, *directory.parents)
    )


def invalidate_local(cwd: str | Path | None = None) -> None:
    """Invalidate local layers, including aliases that may share a repository."""
    if "GIT_CONFIG" in os.environ:
        clear_cache()
        return
    directory = _resolve_directory(cwd)
    _stale_local.update(
        cached_directory
        for cached_directory, scopes in _cache.items()
        if (
            "local" in scopes
            or cached_directory == directory
            or _may_be_repository(cached_directory)
        )
    )


def _normalize_key(key: str) -> str:
    section, separator, remainder = key.partition(".")
    subsection, dot, variable = remainder.rpartition(".")
    return section.lower() + separator + subsection + dot + variable.lower()


def _parse_snapshot(output: bytes) -> dict[str, dict[str, list[str | None]]]:
    entries: dict[str, dict[str, list[str | None]]] = {}
    if not output:
        return entries
    fields = output.split(b"\0")
    if fields[-1] or len(fields) % 2 != 1:
        raise GitConfigError("Invalid Git configuration snapshot")
    for scope, record in zip(fields[0:-1:2], fields[1::2]):
        scope_name = os.fsdecode(scope)
        if scope_name not in _SCOPES:
            raise GitConfigError("Invalid Git configuration snapshot")
        key, separator, value = record.partition(b"\n")
        if not key:
            raise GitConfigError("Invalid Git configuration snapshot")
        layer = entries.setdefault(scope_name, {})
        layer.setdefault(_normalize_key(os.fsdecode(key)), []).append(
            os.fsdecode(value) if separator else None
        )
    return entries


def _read_snapshot(
    directory: Path, *, local_only: bool = False,
) -> dict[str, dict[str, list[str | None]]]:
    command = ["git", "config"]
    if local_only:
        command.append("--local")
    command.extend(("--null", "--show-scope", "--includes", "--list"))
    try:
        result = subprocess.run(
            command, cwd=directory, capture_output=True, check=False,
        )
    except OSError:
        raise GitConfigError("Could not run Git configuration query") from None
    if result.returncode:
        raise GitConfigError("Git configuration query failed")
    return _parse_snapshot(result.stdout)


def _has_conditional_include(layer: dict[str, list[str | None]]) -> bool:
    return any(key.startswith("includeif.") and key.endswith(".path") for key in layer)


def _refresh_local(
    directory: Path, scopes: dict[str, dict[str, list[str | None]]],
) -> dict[str, dict[str, list[str | None]]]:
    if "local" not in scopes or any(_has_conditional_include(layer) for layer in scopes.values()):
        return _read_snapshot(directory)
    updated = _read_snapshot(directory, local_only=True)
    local = updated.get("local", {})
    if (
        updated.keys() - {"local"}
        or _has_conditional_include(local)
        or local.get("extensions.worktreeconfig")
        != scopes["local"].get("extensions.worktreeconfig")
    ):
        return _read_snapshot(directory)
    return {**scopes, "local": local}


def _resolve_directory(cwd: str | Path | None) -> Path:
    return Path.cwd().resolve() if cwd is None else Path(cwd).resolve()


def _snapshot(cwd: str | Path | None) -> dict[str, dict[str, list[str | None]]]:
    directory = _resolve_directory(cwd)
    if directory not in _cache:
        _cache[directory] = _read_snapshot(directory)
    elif directory in _stale_local:
        _cache[directory] = _refresh_local(directory, _cache[directory])
        _stale_local.remove(directory)
    return _cache[directory]


def get(
    key: str, cwd: str | Path | None = None, *, default: str | None = None,
) -> str | None:
    """Return the last value for key, or default for an absent key."""
    scopes = _snapshot(cwd)
    normalized = _normalize_key(key)
    for scope in reversed(_SCOPES):
        if values := scopes.get(scope, {}).get(normalized):
            return values[-1]
    return default


def get_all(key: str, cwd: str | Path | None = None) -> list[str | None]:
    """Return all values in Git read order; None denotes a valueless entry."""
    scopes = _snapshot(cwd)
    normalized = _normalize_key(key)
    return [value for scope in _SCOPES for value in scopes.get(scope, {}).get(normalized, ())]
