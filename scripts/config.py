"""TOML-based configuration loader for spex."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
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

@dataclass
class SpexContext:
    """Resolved spex configuration context."""

    spex_tomls: list[Path]
    config: dict
    spex_root: str
    spex_roots: list[str]
    worktree_root: Path | None

_SENTINEL = object()
_worktree_root_cache: dict = {}
_config_cache: dict | None = None
_context_cache: SpexContext | None = None


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

    _config_cache = result
    return _config_cache


def get_worktree_root(workdir: str | Path | None = None) -> Path | None:
    """Public wrapper for _get_worktree_root."""
    return _get_worktree_root(workdir)


def get_spex_tomls(workdir: str | Path | None = None) -> list[Path]:
    """Return the discovered TOML config paths (highest priority first)."""
    worktree_root = _get_worktree_root(workdir)
    return _find_spex_tomls(worktree_root, workdir)


def _resolve_spex_roots(
    spex_tomls: list[Path],
    worktree_root: Path | None,
    workdir: str | Path | None = None,
) -> list[str]:
    """Resolve spex_root to a list of directory paths using per-level configs.

    Each .spex.toml that sets spex_root governs its own directory and all
    child directories below it. When walking upward from start, the effective
    spex_root at each level is determined by the nearest .spex.toml at or
    above that level.

    Same-level rule: if the directory being checked is the same directory
    where the governing .spex.toml lives, the candidate path is added
    unconditionally (even if it doesn't exist yet).
    """
    if worktree_root is not None:
        start = worktree_root.resolve()
    else:
        start = Path(workdir).resolve() if workdir else Path.cwd().resolve()

    # Build list of directories from start to filesystem root
    path_dirs: list[Path] = []
    current = start
    while True:
        path_dirs.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Map toml directories to their index in path_dirs (only if they set spex_root)
    path_set = {d: i for i, d in enumerate(path_dirs)}
    toml_at: dict[int, str] = {}  # index -> spex_root value
    unmapped_tomls: list[tuple[Path, str]] = []  # (toml_dir, spex_root) for off-path tomls

    for toml_path in spex_tomls:
        toml_dir = toml_path.parent.resolve()
        data = _load_toml_config(toml_path)
        sr = (data or {}).get("spex_root")
        if sr is None:
            continue
        if toml_dir in path_set:
            toml_at[path_set[toml_dir]] = sr
        else:
            unmapped_tomls.append((toml_dir, sr))

    # Sweep from root-end to start-end computing (effective_spex_root, same_level)
    n = len(path_dirs)
    governing: list[tuple[str, bool]] = [("", False)] * n
    current_effective = _DEFAULTS["spex_root"]
    for i in range(n - 1, -1, -1):
        if i in toml_at:
            current_effective = toml_at[i]
            governing[i] = (current_effective, True)
        else:
            governing[i] = (current_effective, False)

    # Build results
    results: list[str] = []
    visited: set[str] = set()

    for i, d in enumerate(path_dirs):
        spex_root_val, same_level = governing[i]
        expanded = Path(spex_root_val).expanduser()

        if expanded.is_absolute():
            candidate = expanded
        else:
            candidate = d / spex_root_val

        resolved_str = str(candidate.resolve())
        if resolved_str not in visited:
            if same_level or candidate.is_dir():
                results.append(resolved_str)
                visited.add(resolved_str)

    # Handle tomls not on the path (e.g. home fallback when ~ is not an ancestor)
    for toml_dir, sr in unmapped_tomls:
        expanded = Path(sr).expanduser()
        candidate = expanded if expanded.is_absolute() else toml_dir / sr
        resolved_str = str(candidate.resolve())
        if resolved_str not in visited:
            results.append(resolved_str)
            visited.add(resolved_str)

    # Always append ~/<default_spex_root> as final fallback
    home_default = str((Path.home() / _DEFAULTS["spex_root"]).resolve())
    if home_default not in visited:
        results.append(home_default)

    return results


def resolve_spex_root_and_roots(
    workdir: str | Path | None = None,
) -> tuple[str, list[str]]:
    """Return (primary_spex_root, all_spex_roots) based on per-level config.

    The primary root is the first (highest-priority) entry in the roots list.
    """
    worktree_root = get_worktree_root(workdir)
    spex_tomls = _find_spex_tomls(worktree_root, workdir)
    roots = _resolve_spex_roots(spex_tomls, worktree_root, workdir)
    if roots:
        return (roots[0], roots)
    return ("", [])


def get_context(workdir: str | Path | None = None) -> SpexContext:
    """Return a resolved SpexContext, cached after first call.

    Aggregates worktree root, discovered TOML paths, merged config, and
    resolved spex_root/spex_roots into a single object.
    """
    global _context_cache

    if _context_cache is not None:
        return _context_cache

    worktree_root = _get_worktree_root(workdir)
    spex_tomls = _find_spex_tomls(worktree_root)
    config = load_config(workdir)
    spex_root, spex_roots = resolve_spex_root_and_roots(workdir)

    _context_cache = SpexContext(
        spex_tomls=spex_tomls,
        config=config,
        spex_root=spex_root,
        spex_roots=spex_roots,
        worktree_root=worktree_root,
    )
    return _context_cache


def clear_config_cache() -> None:
    """Clear the module-level configuration and worktree root caches."""
    global _config_cache, _worktree_root_cache, _context_cache
    _config_cache = None
    _worktree_root_cache = {}
    _context_cache = None
