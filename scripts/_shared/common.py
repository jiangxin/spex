#!/usr/bin/env python3
"""Shared utilities for the SDD skill."""

import subprocess
from pathlib import Path

PROMPT_LOG = "prompt.log"
SPEC_FILE = "spec.md"
TODO_FILE = "todo.json"


def get_spec_root(workdir=None):
    """Return the spec root directory path.

    Uses `git rev-parse --show-toplevel` to find the git repository root,
    then places the spec root in its parent as a hidden directory:
    .<repo_basename>.specs

    For example:
        git toplevel = /Users/alice/projects/my-app
        spec_root = /Users/alice/projects/.my-app.specs

    Args:
        workdir: The working directory for git lookup. Defaults to cwd.

    Returns:
        Absolute path to the spec root directory.
    """
    cmd = ["git", "rev-parse", "--show-toplevel"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=workdir
    )
    if result.returncode != 0:
        raise RuntimeError("Not inside a git repository")

    repo_root = Path(result.stdout.strip()).resolve()
    parent = repo_root.parent
    dirname = repo_root.name

    return str(parent / f".{dirname}.specs")


def get_specs_dir(workdir=None):
    """Return the specs directory: <spec_root>/specs/."""
    return str(Path(get_spec_root(workdir)) / "specs")


def get_archives_dir(workdir=None):
    """Return the archives directory: <spec_root>/archives/."""
    return str(Path(get_spec_root(workdir)) / "archives")


if __name__ == "__main__":
    print(get_spec_root())
