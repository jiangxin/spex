#!/usr/bin/env python3
"""Shared utilities for the SDD skill."""

import subprocess
from pathlib import Path


def get_spec_dir(workdir=None):
    """Return the spec directory path.

    Uses `git rev-parse --show-toplevel` to find the git repository root,
    then places the spec directory in its parent as a hidden directory:
    .<repo_basename>.specs

    For example:
        git toplevel = /Users/alice/projects/my-app
        spec_dir = /Users/alice/projects/.my-app.specs

    Args:
        workdir: The working directory for git lookup. Defaults to cwd.

    Returns:
        Absolute path to the spec directory.
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

    spec_dir = parent / f".{dirname}.specs"
    return str(spec_dir)


if __name__ == "__main__":
    print(get_spec_dir())
