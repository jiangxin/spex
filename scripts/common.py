#!/usr/bin/env python3
"""Shared utilities for the Spex skill."""

import os
import subprocess
from datetime import datetime
from pathlib import Path

SPEC_FILE = "spec.md"
TODO_FILE = "todo.json"
DEFAULT_SPECS_ROOT_DIR = ".specs"
TEMPLATE_DIR = "templates"

_spec_root_cache: dict[str | None, str] = {}


def clear_specs_root_cache():
    """Clear the spec_root cache. Useful for testing."""
    _spec_root_cache.clear()


def _ensure_gitignore(repo_root: Path, entry: str):
    """Ensure entry is listed in .gitignore.

    Uses git check-ignore to check if entry is already ignored.
    If not, appends it to .gitignore.
    """
    # Check if entry is already ignored using git check-ignore
    result = subprocess.run(
        ["git", "check-ignore", "-q", entry],
        cwd=repo_root,
        capture_output=True
    )
    if result.returncode == 0:
        # Entry is already ignored
        return

    # Entry is not ignored, add it to .gitignore
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if content and not content.endswith("\n"):
            content += "\n"
        content += entry + "\n"
        gitignore.write_text(content)
    else:
        gitignore.write_text(entry + "\n")


def _ensure_repo_specs_dir(repo_root: Path, specs_dir: str):
    """Create specs_root directory if not exists and add to .gitignore.

    Called only from the fallback branch (case 3) of get_specs_root().
    """
    specs_path = repo_root / Path(specs_dir)
    if not specs_path.exists():
        specs_path.mkdir(parents=True, exist_ok=True)
        # Add trailing slash for directory entry in .gitignore
        gitignore_entry = specs_dir.rstrip("/") + "/"
        _ensure_gitignore(repo_root, gitignore_entry)


def get_specs_root(workdir=None):
    """Return the spec root directory path.

    Resolution order:
    1. Environment variable SPECS_ROOT.
    2. Git config key specs.rootdir.
    3. Default: .specs inside the git toplevel.

    Args:
        workdir: The working directory for git lookup. Defaults to cwd.

    Returns:
        Absolute path to the spec root directory.
    """
    cache_key = workdir
    if cache_key in _spec_root_cache:
        return _spec_root_cache[cache_key]

    # 1. Check environment variable
    env_root = os.environ.get("SPECS_ROOT")
    if env_root:
        specs_root = str(Path(env_root).resolve())
        _spec_root_cache[cache_key] = specs_root
        return specs_root

    # 2. Check git config
    cmd = ["git", "config", "--get", "specs.rootdir"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=workdir
    )
    if result.returncode == 0 and result.stdout.strip():
        git_root = result.stdout.strip()
        specs_root = str(Path(git_root).resolve())
        _spec_root_cache[cache_key] = specs_root
        return specs_root

    # 3. Fallback: compute from git toplevel
    cmd = ["git", "rev-parse", "--show-toplevel"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=workdir
    )
    if result.returncode != 0:
        raise RuntimeError("Not inside a git repository")

    repo_root = Path(result.stdout.strip()).resolve()
    specs_root = str(repo_root / DEFAULT_SPECS_ROOT_DIR)
    _ensure_repo_specs_dir(repo_root, DEFAULT_SPECS_ROOT_DIR)
    _spec_root_cache[cache_key] = specs_root
    return specs_root


def get_specs_dir(workdir=None):
    """Return the specs directory: <spec_root>/specs/."""
    return str(Path(get_specs_root(workdir)) / "specs")


def get_archives_dir(workdir=None):
    """Return the archives directory: <spec_root>/archives/."""
    return str(Path(get_specs_root(workdir)) / "archives")


def local_iso_timestamp() -> str:
    """Return current local time as ISO 8601 with timezone offset."""
    now = datetime.now().astimezone()
    base = now.strftime("%Y-%m-%dT%H:%M:%S")
    offset = now.strftime("%z")
    return f"{base}{offset[:3]}:{offset[3:]}"


def get_spec_template(workdir=None) -> str:
    """Return spec template path with fallback to built-in template.

    Lookup order:
    1. <spec_root>/templates/spec.md (user custom template)
    2. <skill_path>/templates/spec.md (built-in template)

    Returns:
        Absolute path to template file.
    """
    # 1. Check user custom template
    specs_root = Path(get_specs_root(workdir))
    custom_template = specs_root / TEMPLATE_DIR / SPEC_FILE

    if custom_template.exists():
        return str(custom_template)

    # 2. Fallback to built-in template
    skill_path = Path(__file__).resolve().parent.parent
    builtin_template = skill_path / TEMPLATE_DIR / SPEC_FILE

    if not builtin_template.exists():
        raise FileNotFoundError(
            f"Built-in template not found at {builtin_template}"
        )

    return str(builtin_template)


if __name__ == "__main__":
    print(get_specs_root())
