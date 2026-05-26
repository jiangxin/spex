"""Branch management utilities for spex."""

from __future__ import annotations

import re
import subprocess


def _strip_refs_prefix(name: str) -> str:
    """Strip refs/heads/ prefix if present, returning a short branch name."""
    if name.startswith("refs/heads/"):
        return name[len("refs/heads/"):]
    return name


def get_current_branch() -> str:
    """Return the current git branch name in short format (no refs/heads/ prefix)."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stderr)
    branch_name = result.stdout.strip()
    if branch_name == "HEAD":
        raise RuntimeError("Currently in detached HEAD state, no branch name.")
    return branch_name


def strip_date_prefix(topic_name: str) -> str:
    """Remove the YYYY-MM-DD-HH-MM- datetime prefix from a topic name."""
    return re.sub(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-", "", topic_name)


def branch_exists(branch_name: str) -> bool:
    """Check if a local git branch exists."""
    branch_name = _strip_refs_prefix(branch_name)
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch_name}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def create_branch(branch_name: str) -> None:
    """Create a new local branch. Raises subprocess.CalledProcessError on failure."""
    branch_name = _strip_refs_prefix(branch_name)
    subprocess.run(
        ["git", "branch", branch_name],
        capture_output=True,
        text=True,
        check=True,
    )


def switch_branch(branch_name: str) -> None:
    """Switch to the given branch. Raises subprocess.CalledProcessError on failure."""
    branch_name = _strip_refs_prefix(branch_name)
    subprocess.run(
        ["git", "switch", branch_name],
        capture_output=True,
        text=True,
        check=True,
    )


def set_branch_description(branch: str, description: str) -> None:
    """Set the git branch description. Branch must be short format (no refs/heads/)."""
    branch = _strip_refs_prefix(branch)
    subprocess.run(
        ["git", "config", f"branch.{branch}.description", description],
        capture_output=True,
        text=True,
        check=True,
    )
