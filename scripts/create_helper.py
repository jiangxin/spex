"""Helper utilities for spec creation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from common import DEFAULT_SPEX_BRANCH_PREFIX

USAGE = """\
Usage: spex create-helper <subcommand> [options]

Subcommands:
  precheck    Validate branch creation feasibility

Options:
  -h, --help  Show this help message and exit
"""


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
