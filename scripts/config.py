"""TOML-based configuration loader for spex."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TypedDict

import tomllib


class SpexConfig(TypedDict, total=False):
    """TypedDict for spex configuration keys."""

    spex_root: str
    create_branch: bool
    main_branch_name: str
    submit_method: str


_DEFAULTS: SpexConfig = {
    "spex_root": ".spex",
    "create_branch": False,
    "main_branch_name": "",
    "submit_method": "merge",
}

_SENTINEL = object()
_worktree_root_cache: dict = {}
_config_cache: dict | None = None


def _get_worktree_root(workdir: str | Path | None = None) -> Path | None:
    """Return the git worktree root, or None if not inside a repo. Cached."""
    key = str(Path(workdir).resolve()) if workdir else None
    cached = _worktree_root_cache.get(key, _SENTINEL)
    if cached is not _SENTINEL:
        return cached
    cmd = ["git", "rev-parse", "--show-toplevel"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
    value = Path(result.stdout.strip()).resolve() if result.returncode == 0 else None
    _worktree_root_cache[key] = value
    return value


def _find_spex_tomls(
    worktree_root: Path | None, workdir: str | Path | None = None
) -> list[Path]:
    """Discover .spex.toml files in priority order (highest first).

    Walk from a starting directory upward to filesystem root, collecting
    existing .spex.toml files. When inside a git repo, start from
    worktree_root; otherwise start from workdir (or cwd).
    Then check ~/.spex.toml as a fallback.
    """
    candidates: list[Path] = []
    visited: set[Path] = set()

    if worktree_root is not None:
        start = worktree_root.resolve()
    else:
        start = Path(workdir).resolve() if workdir else Path.cwd().resolve()

    current = start
    while True:
        toml_path = current / ".spex.toml"
        if toml_path.is_file():
            candidates.append(toml_path)
            visited.add(toml_path.resolve())
        parent = current.parent
        if parent == current:
            break
        current = parent

    home_toml = (Path.home() / ".spex.toml").resolve()
    if home_toml.is_file() and home_toml not in visited:
        candidates.append(home_toml)

    return candidates


def _load_toml_config(path: Path) -> dict | None:
    """Read a single TOML file. Return None if missing or unparseable."""
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts. Keys in *override* take precedence."""
    merged = base.copy()
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def _merge_configs(spex_tomls: list[Path]) -> dict:
    """Merge TOML configs. spex_tomls is highest-priority-first."""
    merged: dict = {}
    for path in reversed(spex_tomls):
        data = _load_toml_config(path)
        if data is not None:
            merged = _deep_merge(merged, data)
    return merged


def load_config(workdir: str | Path | None = None) -> dict:
    """Main entry point: resolve spex configuration with caching."""
    global _config_cache

    if _config_cache is not None:
        return _config_cache

    worktree_root = _get_worktree_root(workdir)
    spex_tomls = _find_spex_tomls(worktree_root, workdir)
    merged = _merge_configs(spex_tomls)

    result: dict = {**_DEFAULTS, **merged}

    env_spex_root = os.environ.get("SPEX_ROOT")
    if env_spex_root:
        result["spex_root"] = env_spex_root

    _config_cache = result
    return _config_cache


def get_worktree_root(workdir: str | Path | None = None) -> Path | None:
    """Public wrapper for _get_worktree_root."""
    return _get_worktree_root(workdir)


def get_spex_tomls(workdir: str | Path | None = None) -> list[Path]:
    """Return the discovered TOML config paths (highest priority first)."""
    worktree_root = _get_worktree_root(workdir)
    return _find_spex_tomls(worktree_root, workdir)


def clear_config_cache() -> None:
    """Clear the module-level configuration and worktree root caches."""
    global _config_cache, _worktree_root_cache
    _config_cache = None
    _worktree_root_cache = {}
