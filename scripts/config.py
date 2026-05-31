"""TOML-based configuration loader for spex."""

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict


class SpexConfig(TypedDict, total=False):
    """TypedDict for spex configuration keys."""

    spex_root: str
    branch_management: bool
    main_branch_name: str
    submit_method: str

_CONFIG_SCHEMA: list[tuple[str, str | bool, str]] = [
    ("spex_root", ".spex", "Root directory for spec storage"),
    ("branch_management", True, "Create and manage branches for specs"),
    ("main_branch_name", "", "Restrict spec creation to this branch"),
    ("submit_method", "merge", "How to submit completed work: merge or pr"),
]

_DEFAULTS: SpexConfig = {k: v for k, v, _ in _CONFIG_SCHEMA}

@dataclass
class SpexContext:
    """Resolved spex configuration context."""

    spex_tomls: list[Path]
    config: dict
    spex_root: str
    spex_roots: list[str]
    top_workdir: Path | None
    main_worktree: Path | None

_SENTINEL = object()
_top_workdir_cache: dict = {}
_main_worktree_cache: dict = {}
_config_cache: dict | None = None
_context_cache: SpexContext | None = None
_spex_config_file_override: str | None = None


def set_spex_config_file(path: str | None) -> None:
    """Set an explicit config file path (from --spex-config-file CLI flag)."""
    global _spex_config_file_override
    _spex_config_file_override = path

def _get_main_worktree(workdir: str | Path | None = None) -> Path | None:
    """Return the git main worktree, or None if not inside a repo. Cached.

    Handles linked worktrees and submodules: when .git is a file, resolves
    back to the main worktree via ``git worktree list --porcelain``.
    """
    key = str(Path(workdir).resolve()) if workdir else None
    cached = _main_worktree_cache.get(key, _SENTINEL)
    if cached is not _SENTINEL:
        return cached

    top_workdir = _get_top_workdir(workdir)
    if top_workdir is None:
        _main_worktree_cache[key] = None
        return None

    dot_git = top_workdir / ".git"

    if dot_git.is_dir():
        _main_worktree_cache[key] = top_workdir
        return top_workdir

    # .git is a file → linked worktree or submodule
    list_cwd: str | Path | None = workdir

    super_result = subprocess.run(
        ["git", "rev-parse", "--show-superproject-working-tree"],
        capture_output=True, text=True, cwd=workdir,
    )
    if super_result.returncode == 0 and super_result.stdout.strip():
        list_cwd = super_result.stdout.strip()

    wt_result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True, cwd=list_cwd,
    )
    value: Path | None = None
    if wt_result.returncode == 0:
        for line in wt_result.stdout.splitlines():
            if line.startswith("worktree "):
                value = Path(line[len("worktree "):]).resolve()
                break

    _main_worktree_cache[key] = value
    return value

def _get_top_workdir(workdir: str | Path | None = None) -> Path | None:
    """Return the git top workdir, or None if not inside a repo. Cached."""
    key = str(Path(workdir).resolve()) if workdir else None
    cached = _top_workdir_cache.get(key, _SENTINEL)
    if cached is not _SENTINEL:
        return cached
    cmd = ["git", "rev-parse", "--show-toplevel"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
    value = Path(result.stdout.strip()).resolve() if result.returncode == 0 else None
    _top_workdir_cache[key] = value
    return value


def _find_spex_tomls(
    main_worktree: Path | None, workdir: str | Path | None = None
) -> list[Path]:
    """Discover .spex.toml files in priority order (highest first).

    Walk from a starting directory upward to filesystem root, collecting
    existing .spex.toml files. When inside a git repo, start from
    main_worktree; otherwise start from workdir (or cwd).
    Then check ~/.spex.toml as a fallback.

    If --spex-config-file or SPEX_CONFIG_FILE is set, skip discovery and
    return only that file. Raises FileNotFoundError if it doesn't exist.
    """
    config_file = _spex_config_file_override or os.environ.get("SPEX_CONFIG_FILE")
    if config_file:
        p = Path(config_file).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(
                f"Specified spex config file does not exist: {config_file}"
            )
        return [p]

    candidates: list[Path] = []
    visited: set[Path] = set()

    if main_worktree is not None:
        start = main_worktree.resolve()
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
            merged = _deep_merge(merged, data.get("spex", {}))
    return merged


def load_config(workdir: str | Path | None = None) -> dict:
    """Main entry point: resolve spex configuration with caching."""
    global _config_cache

    if _config_cache is not None:
        return _config_cache

    main_wt = _get_main_worktree(workdir)
    spex_tomls = _find_spex_tomls(main_wt, workdir)
    merged = _merge_configs(spex_tomls)

    result: dict = {**_DEFAULTS, **merged}

    _config_cache = result
    return _config_cache


def get_top_workdir(workdir: str | Path | None = None) -> Path | None:
    """Public wrapper for _get_top_workdir."""
    return _get_top_workdir(workdir)


def get_main_worktree(workdir: str | Path | None = None) -> Path | None:
    """Public wrapper for _get_main_worktree."""
    return _get_main_worktree(workdir)


def get_spex_tomls(workdir: str | Path | None = None) -> list[Path]:
    """Return the discovered TOML config paths (highest priority first)."""
    main_wt = _get_main_worktree(workdir)
    return _find_spex_tomls(main_wt, workdir)


def _resolve_spex_roots(
    spex_tomls: list[Path],
    main_worktree: Path | None,
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
    if main_worktree is not None:
        start = main_worktree.resolve()
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
        sr = (data or {}).get("spex", {}).get("spex_root")
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
    main_wt = _get_main_worktree(workdir)
    spex_tomls = _find_spex_tomls(main_wt, workdir)
    roots = _resolve_spex_roots(spex_tomls, main_wt, workdir)
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

    top_workdir = _get_top_workdir(workdir)
    main_worktree = _get_main_worktree(workdir)
    spex_tomls = _find_spex_tomls(main_worktree, workdir)
    config = load_config(workdir)
    spex_root, spex_roots = resolve_spex_root_and_roots(workdir)

    _context_cache = SpexContext(
        spex_tomls=spex_tomls,
        config=config,
        spex_root=spex_root,
        spex_roots=spex_roots,
        top_workdir=top_workdir,
        main_worktree=main_worktree,
    )
    return _context_cache


def generate_default_toml() -> str:
    """Generate a TOML string with all config defaults as commented-out entries."""
    return generate_updated_toml({})


def _render_toml_value(value) -> str:
    """Render a Python value as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def generate_updated_toml(user_config: dict) -> str:
    """Generate a TOML string preserving user-set values from an existing config.

    Keys present in user_config are rendered uncommented with the user's value.
    Keys absent from user_config are rendered as commented-out defaults.
    Keys in user_config that are not in the schema are ignored.
    """
    lines = ["[spex]"]
    for i, (key, default, comment) in enumerate(_CONFIG_SCHEMA):
        if i > 0:
            lines.append("")
        lines.append(f"# {comment}")
        if key in user_config:
            rendered = _render_toml_value(user_config[key])
            lines.append(f"{key} = {rendered}")
        else:
            rendered = _render_toml_value(default)
            lines.append(f"# {key} = {rendered}")
    return "\n".join(lines) + "\n"


def safe_update_toml(toml_path):
    """Safe-update a single .spex.toml with the latest config schema.

    Reads the existing file, preserves user-set keys, and regenerates with
    the full schema. New keys appear as commented-out defaults.

    Returns True if the file was modified.
    """
    existing = _load_toml_config(toml_path)
    user_config = (existing or {}).get("spex", {})
    new_content = generate_updated_toml(user_config)
    if not toml_path.is_file():
        return False
    old_content = toml_path.read_text(encoding="utf-8")
    if new_content != old_content:
        toml_path.write_text(new_content, encoding="utf-8")
        return True
    return False


def get_effective_user_config(workdir: str | Path | None = None) -> dict:
    """Return merged user-set config values (without defaults) for a workdir.

    Discovers .spex.toml files relative to workdir and merges their [spex]
    tables. Only explicitly set keys are included — commented-out defaults
    are not. Use this to create a new project-level .spex.toml that inherits
    parent settings.
    """
    main_wt = _get_main_worktree(workdir)
    spex_tomls = _find_spex_tomls(main_wt, workdir)
    return _merge_configs(spex_tomls)


def clear_config_cache() -> None:
    """Clear the module-level configuration and worktree root caches."""
    global _config_cache, _top_workdir_cache, _main_worktree_cache
    global _context_cache, _spex_config_file_override
    _config_cache = None
    _top_workdir_cache = {}
    _main_worktree_cache = {}
    _context_cache = None
    _spex_config_file_override = None
