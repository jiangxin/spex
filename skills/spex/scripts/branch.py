"""Branch management utilities for spex."""

from __future__ import annotations

import subprocess
import unicodedata
from pathlib import Path

from config import clear_git_config_cache


def _strip_refs_prefix(name: str) -> str:
    """Strip refs/heads/ prefix if present, returning a short branch name."""
    if name.startswith("refs/heads/"):
        return name[len("refs/heads/"):]
    return name


def get_current_branch(cwd: str | Path | None = None) -> str:
    """Return the current git branch name in short format (no refs/heads/ prefix).

    Read the full symbolic ref to support unborn branches and avoid
    ambiguous short names when a tag shares the branch name.
    Raises RuntimeError on detached HEAD.
    """
    result = subprocess.run(
        ["git", "symbolic-ref", "HEAD"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Currently in detached HEAD state, no branch name."
        )
    return _strip_refs_prefix(result.stdout.strip())


def list_local_branch_refs() -> set[str] | None:
    """Return local refs in the current repository, or None on query failure."""
    try:
        result = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname)", "refs/heads/"],
            capture_output=True,
            text=True,
            errors="surrogateescape",
        )
    except OSError:
        return None
    if result.returncode or result.stderr:
        return None
    return set(result.stdout.rstrip("\n").split("\n")) if result.stdout else set()


def normalize_ref_alias(ref: str) -> str:
    """Group possible filesystem aliases for verification by Git."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", ref).casefold())


def branch_exists(
    branch_name: str,
    cwd: str | Path | None = None,
    *,
    local_refs: set[str] | None = None,
    normalized_refs: set[str] | None = None,
) -> bool:
    """Check if a local git branch exists."""
    branch_name = _strip_refs_prefix(branch_name)
    ref = f"refs/heads/{branch_name}"
    if local_refs is not None and not any(op in branch_name for op in ("~", "^", ":", "@{")):
        if ref in local_refs:
            return True
        if normalized_refs is None or normalize_ref_alias(ref) not in normalized_refs:
            return False
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.returncode == 0


def resolve_default_branch(
    candidates: list[str] | None = None,
    fallback: str = "main",
    cwd: str | Path | None = None,
) -> str:
    """Resolve the default branch by probing candidates in order.

    Returns the first candidate that exists, or ``fallback`` if none
    exist.
    """
    if candidates is None:
        candidates = ["main", "master"]
    for name in candidates:
        if branch_exists(name, cwd=cwd):
            return name
    return fallback


def create_and_switch_branch(
    branch_name: str,
    cwd: str | Path | None = None,
    base: str | None = None,
) -> None:
    """Create a new local branch and switch to it.

    Uses ``git switch -c`` instead of ``git branch`` so that it works on
    unborn branches (fresh ``git init`` repos with no commits) where
    ``git branch`` fails with "not a valid object name: 'master'".
    When ``base`` is provided, the new branch starts from that ref
    (``git switch -c <name> <base>``); otherwise from current HEAD.
    Raises subprocess.CalledProcessError on failure.
    """
    branch_name = _strip_refs_prefix(branch_name)
    cmd = ["git", "switch", "-c", branch_name]
    if base:
        cmd.append(base)
    subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    clear_git_config_cache()


def switch_branch(branch_name: str, cwd: str | Path | None = None) -> None:
    """Switch to the given branch. Raises subprocess.CalledProcessError on failure."""
    branch_name = _strip_refs_prefix(branch_name)
    subprocess.run(
        ["git", "switch", branch_name],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    clear_git_config_cache()


def set_branch_description(
    branch: str, description: str, cwd: str | Path | None = None,
) -> None:
    """Set the git branch description. Branch must be short format (no refs/heads/)."""
    branch = _strip_refs_prefix(branch)
    subprocess.run(
        ["git", "config", f"branch.{branch}.description", description],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    clear_git_config_cache(local_only=True, cwd=cwd)


def merge_branch(
    target: str, source: str, cwd: str | Path | None = None,
) -> None:
    """Merge source branch into target. Raises CalledProcessError on conflict.

    If HEAD is already on ``target``, skip the switch. This allows merging
    inside a worktree that already has the target branch checked out when
    another worktree holds the source branch.
    """
    target = _strip_refs_prefix(target)
    try:
        current = get_current_branch(cwd=cwd)
    except RuntimeError:
        current = None
    if current != target:
        subprocess.run(
            ["git", "switch", target],
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
        clear_git_config_cache()
    subprocess.run(
        ["git",
         "-c", "merge.branchdesc=true",
         "-c", "merge.log=true",
         "merge", source,
         "--no-ff",
         "--no-edit"],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )


