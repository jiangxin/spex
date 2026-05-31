"""Helper utilities for spec creation."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common import (
    DEFAULT_SPEX_BRANCH_PREFIX,
    atomic_write_json,
    strip_date_prefix,
)

TOPIC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
DATE_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-")
MAX_TOPIC_BYTES = 64

USAGE = """\
Usage: spex create-helper <subcommand> [options]

Subcommands:
  precheck    Validate branch creation feasibility

Options:
  -h, --help  Show this help message and exit
"""


def create_topic(topic, specs_dir, auto_prefix=True):
    """Create a topic directory under specs_dir.

    Returns (topic_name, topic_dir) tuple.
    Raises ValueError on invalid input, FileExistsError if topic exists.
    """
    specs_dir = Path(specs_dir)

    if not DATE_PREFIX_PATTERN.match(topic) and auto_prefix:
        prefix = datetime.now().strftime("%Y-%m-%d-%H-%M")
        topic = f"{prefix}-{topic}"

    if not TOPIC_PATTERN.match(topic):
        raise ValueError(
            f"invalid topic name '{topic}'. "
            "Must match YYYY-MM-DD-HH-MM-<name> with [a-z0-9-]."
        )

    if len(topic.encode("utf-8")) > MAX_TOPIC_BYTES:
        raise ValueError(f"topic name '{topic}' exceeds {MAX_TOPIC_BYTES} bytes.")

    topic_dir = specs_dir / topic
    if topic_dir.exists():
        raise FileExistsError(f"'{topic}' already exists, use a different name.")

    specs_dir.mkdir(parents=True, exist_ok=True)
    topic_dir.mkdir()
    return (topic, topic_dir)


def _write_meta(topic_dir, git_info, ctx, prompt, timestamp, description=""):
    """Write meta.json into topic_dir with git info and prompt."""
    workdir = str(ctx.top_workdir) if ctx.top_workdir else git_info.get("workdir", "")
    main_worktree = str(ctx.main_worktree) if ctx.main_worktree else workdir
    meta = {
        "topic": strip_date_prefix(Path(topic_dir).name),
        "workdir": workdir,
        "main_worktree": main_worktree,
        "remote_url": git_info.get("remote_url", ""),
        "branch": git_info.get("branch", ""),
        "user_name": git_info.get("user_name", ""),
        "user_email": git_info.get("user_email", ""),
        "created_at": timestamp,
        "prompts": [prompt] if prompt else [],
    }
    if description:
        meta["description"] = description
    meta_path = Path(topic_dir) / "meta.json"
    atomic_write_json(meta_path, meta)


def validate_create_branch(
    config: dict, cwd: str | Path | None = None,
) -> str:
    """Validate whether branch creation is enabled and feasible.

    Prints errors to stderr and exits on failure.
    Returns the current branch name on success.
    """
    from branch import get_current_branch, switch_branch

    try:
        current = get_current_branch(cwd)
    except subprocess.CalledProcessError as e:
        print(f"Error: cannot determine current branch: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not bool(config["branch_management"]):
        print("Note: branch management is not enabled in .spex.toml, "
              "will not create new branch for spec.", file=sys.stderr)
        return current

    main_branch = config["main_branch_name"]
    if main_branch and current != main_branch:
        print(
            f"Warning: current branch '{current}' does not match "
            f"main_branch_name '{main_branch}'. "
            f"Switching to '{main_branch}'...",
            file=sys.stderr,
        )
        try:
            switch_branch(main_branch, cwd)
        except subprocess.CalledProcessError as e:
            print(
                f"Error: failed to switch to '{main_branch}': "
                f"{e.stderr.strip() or e}",
                file=sys.stderr,
            )
            sys.exit(-1)
        print(f"Switched to branch '{main_branch}'.", file=sys.stderr)
        return main_branch

    if current.startswith(DEFAULT_SPEX_BRANCH_PREFIX):
        print(
            f"Error: current branch '{current}' starts with "
            f"'{DEFAULT_SPEX_BRANCH_PREFIX}'.\n"
            f"Hint: configure 'main_branch_name' in .spex.toml "
            f"to enable automatic branch switching.",
            file=sys.stderr,
        )
        sys.exit(1)

    return current


def cli_create_validate() -> None:
    """CLI: validate branch creation feasibility."""
    import config as cfg

    ctx = cfg.get_context()
    current = validate_create_branch(ctx.config, cwd=ctx.main_worktree)
    if current:
        print(f"Valid: currently on branch '{current}'")


def main(argv=None):
    """Route create-helper subcommands."""
    if not argv:
        print(USAGE, end="", file=sys.stderr)
        sys.exit(1)

    subcmd = argv[0]

    if subcmd in ("-h", "--help"):
        print(USAGE, end="")
        sys.exit(0)
    elif subcmd == "precheck":
        cli_create_validate()
    else:
        print(f"Error: unknown create-helper subcommand"
              f" '{subcmd}'", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        sys.exit(1)
