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

_config_cache: dict | None = None


def _get_repo_root(workdir: str | Path | None = None) -> Path | None:
    """Return the git repository root, or None if not inside a repo."""
    cmd = ["git", "rev-parse", "--show-toplevel"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _resolve_spex_path(value: str, repo_root: Path | None = None) -> str:
    """Resolve a path value, expanding ~ and making relative paths absolute."""
    p = Path(value).expanduser()
    if not p.is_absolute():
        base = repo_root if repo_root is not None else Path.cwd()
        p = base / p
    return str(p.resolve())


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


def _find_spex_toml(repo_root: Path | None) -> dict:
    """Search and merge all TOML configs in priority order.

    Priority (lowest to highest):
      1. ~/.spex/config.toml
      2. <repo_root>/.spex.toml
    """
    candidates: list[Path] = []

    candidates.append(Path.home() / ".spex" / "config.toml")

    if repo_root is not None:
        candidates.append(repo_root / ".spex.toml")

    merged: dict = {}
    for path in candidates:
        data = _load_toml_config(path)
        if data is not None:
            merged = _deep_merge(merged, data)

    return merged


def load_config(workdir: str | Path | None = None) -> dict:
    """Main entry point: resolve spex configuration with caching.

    Precedence:
      1. SPEX_ROOT env var (overrides everything for spex_root)
      2. Merged TOML files found by _find_spex_toml
      3. Built-in _DEFAULTS
    """
    global _config_cache

    if _config_cache is not None:
        return _config_cache

    repo_root = _get_repo_root(workdir)
    raw = _find_spex_toml(repo_root)

    result: dict = {**_DEFAULTS, **raw}

    result["spex_root"] = _resolve_spex_path(result["spex_root"], repo_root)

    env_spex_root = os.environ.get("SPEX_ROOT")
    if env_spex_root:
        result["spex_root"] = _resolve_spex_path(env_spex_root)

    _config_cache = result
    return _config_cache


def clear_config_cache() -> None:
    """Clear the module-level configuration cache."""
    global _config_cache
    _config_cache = None
