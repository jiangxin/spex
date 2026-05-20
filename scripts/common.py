#!/usr/bin/env python3
"""Shared utilities for the SDD skill."""

import os
import subprocess
from datetime import datetime
from pathlib import Path

PROMPT_LOG = "prompt.log"
SPEC_FILE = "spec.md"
TODO_FILE = "todo.json"

_spec_root_cache: dict[str | None, str] = {}


def clear_specs_root_cache():
    """Clear the spec_root cache. Useful for testing."""
    _spec_root_cache.clear()


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
    specs_root = str(repo_root / ".specs")
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


if __name__ == "__main__":
    print(get_specs_root())
