"""Git worktree helpers for spex feature checkouts."""

from __future__ import annotations

import subprocess
from pathlib import Path

from branch import branch_exists
from common import logger, same_path


def _strip_refs_prefix(name: str) -> str:
    """Strip refs/heads/ prefix if present."""
    if name.startswith("refs/heads/"):
        return name[len("refs/heads/"):]
    return name


def worktree_root() -> Path:
    """Return ``~/.spex/worktree`` (singular directory name)."""
    return Path.home() / ".spex" / "worktree"


def resolve_spex_worktree_path(
    main_worktree: str | Path,
    spec_name: str,
) -> Path:
    """Resolve ``~/.spex/worktree/<repo_basename>/<spec_name>``."""
    basename = Path(main_worktree).resolve().name
    return worktree_root() / basename / spec_name


def _parse_worktree_list(
    cwd: str | Path | None = None,
) -> list[dict[str, str]]:
    """Parse ``git worktree list --porcelain`` into entry dicts."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "detached":
            current["detached"] = "1"
        elif line == "bare":
            current["bare"] = "1"
    if current:
        entries.append(current)
    return entries


def add_worktree(
    path: str | Path,
    branch: str,
    *,
    base: str | None = None,
    cwd: str | Path | None = None,
) -> None:
    """Create a linked worktree at ``path`` for ``branch``.

    If the branch does not exist, create it with ``-b`` (optionally
    from ``base``). If it already exists, check it out in the new
    worktree. Raises ``subprocess.CalledProcessError`` on failure.
    """
    path = Path(path)
    branch = _strip_refs_prefix(branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    if branch_exists(branch, cwd=cwd):
        cmd = ["git", "worktree", "add", str(path), branch]
    else:
        cmd = ["git", "worktree", "add", "-b", branch, str(path)]
        if base:
            cmd.append(base)
    subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    logger.info("Added worktree '%s' for branch '%s'", path, branch)


def remove_worktree(
    path: str | Path,
    *,
    force: bool = False,
    cwd: str | Path | None = None,
) -> None:
    """Remove a linked worktree. No-op if path is not registered."""
    path = Path(path)
    if not is_registered_worktree(path, cwd=cwd):
        return
    cmd = ["git", "worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(str(path))
    subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    logger.info("Removed worktree '%s'", path)


def checkout_commit(path: str | Path, commit: str) -> None:
    """Check out ``commit`` in ``path`` (detached HEAD)."""
    subprocess.run(
        ["git", "checkout", commit],
        capture_output=True,
        text=True,
        check=True,
        cwd=path,
    )
    logger.info("Checked out '%s' in '%s' (detached)", commit, path)


def find_worktree_for_branch(
    branch: str,
    cwd: str | Path | None = None,
) -> Path | None:
    """Return the worktree path that has ``branch`` checked out, or None."""
    branch = _strip_refs_prefix(branch)
    want = f"refs/heads/{branch}"
    for entry in _parse_worktree_list(cwd=cwd):
        if entry.get("branch") == want:
            return Path(entry["path"])
    return None


def is_registered_worktree(
    path: str | Path,
    cwd: str | Path | None = None,
) -> bool:
    """Return True if ``path`` appears in ``git worktree list``."""
    for entry in _parse_worktree_list(cwd=cwd):
        if same_path(entry["path"], path):
            return True
    return False
