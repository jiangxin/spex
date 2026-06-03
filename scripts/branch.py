"""Branch management utilities for spex."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cli import ArgumentParser
from common import strip_date_prefix


def _strip_refs_prefix(name: str) -> str:
    """Strip refs/heads/ prefix if present, returning a short branch name."""
    if name.startswith("refs/heads/"):
        return name[len("refs/heads/"):]
    return name


def get_current_branch(cwd: str | Path | None = None) -> str:
    """Return the current git branch name in short format (no refs/heads/ prefix)."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    branch_name = result.stdout.strip()
    if branch_name == "HEAD":
        raise RuntimeError("Currently in detached HEAD state, no branch name.")
    return branch_name


def branch_exists(branch_name: str, cwd: str | Path | None = None) -> bool:
    """Check if a local git branch exists."""
    branch_name = _strip_refs_prefix(branch_name)
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch_name}"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.returncode == 0


def create_branch(branch_name: str, cwd: str | Path | None = None) -> None:
    """Create a new local branch. Raises subprocess.CalledProcessError on failure."""
    branch_name = _strip_refs_prefix(branch_name)
    subprocess.run(
        ["git", "branch", branch_name],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )


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


def merge_branch(
    target: str, source: str, cwd: str | Path | None = None,
) -> None:
    """Merge source branch into target. Raises CalledProcessError on conflict."""
    subprocess.run(
        ["git", "switch", target],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
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


def _build_submit_parser() -> ArgumentParser:
    """Build the argument parser for ``spex submit``."""
    parser = ArgumentParser(
        prog="spex submit",
        description="Submit (merge) a spex branch back to the target branch.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--topic",
        required=True,
        help="Topic name to submit",
    )
    return parser


def cli_submit(argv=None) -> None:
    """CLI: submit (merge) a spex branch back to target. Output JSON."""
    import common
    import config as cfg
    import hooks

    parser = _build_submit_parser()
    parsed = parser.parse(argv)
    topic_name = parsed.topic
    ctx = cfg.get_project_context()
    conf = ctx.config
    topic_dir = common.resolve_topic_dir(topic_name)
    meta = common.load_meta(topic_dir)
    source = meta.spex_branch if meta else ""
    target = (meta.branch or "main") if meta else "main"
    method = conf["submit_method"]
    errors: list[str] = []

    if not source:
        errors.append("No spex_branch in topic meta.json")
        print(json.dumps({"action": method, "source": "", "target": target,
                          "errors": errors}))
        sys.exit(1)

    if method == "merge":
        try:
            merge_branch(target, source, cwd=ctx.main_worktree)
        except subprocess.CalledProcessError as e:
            errors.append(f"Merge failed: {e.stderr.strip() or str(e)}")
            print(json.dumps({"action": method, "source": source,
                              "target": target, "errors": errors}))
            sys.exit(1)
    else:
        errors.append(f"submit method '{method}' is not implemented")
        print(json.dumps({"action": method, "source": source,
                          "target": target, "errors": errors}))
        sys.exit(1)

    # Run post-action hook on success
    short_name = strip_date_prefix(topic_dir.name)
    done, total = common.get_todo_progress(topic_dir)
    workdir = ctx.top_workdir
    hooks.run_post_action(
        "submit",
        {
            "topic": short_name,
            "source_branch": source,
            "target_branch": target,
            "action": method,
            "done": done,
            "undone": total - done,
        },
        workdir,
        short_name,
    )

    print(json.dumps({"action": method, "source": source,
                      "target": target, "errors": errors}))
