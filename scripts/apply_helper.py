"""Helper utilities for applying specs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from common import DEFAULT_SPEX_BRANCH_PREFIX, strip_date_prefix

USAGE = """\
Usage: spex apply-helper <subcommand> [options]

Subcommands:
  precheck     Validate branch setup for applying a topic
  post-action  Run post-action hook and show hint

Options:
  -h, --help  Show this help message and exit
"""


def _extract_topic_name_for_branch(topic_dir: Path, meta: dict) -> str:
    """Get the topic name to use for branch naming."""
    return meta.get("topic", "") or topic_dir.name


def validate_apply_branch(
    config: dict, topic_dir: Path, cwd: str | Path | None = None,
) -> None:
    """Perform branch setup for applying a topic spec.

    Steps:
    1. If all topic tasks are completed, error and exit.
    2. If branch_management is False in config, return immediately.
    3. If meta.json has spex_branch, ensure current branch matches it;
       switch if not (exit on failure).
    4. If meta.json has no spex_branch, try creating a branch using
       spex/<topic-name-without-date-prefix>, then spex/<topic-name-with-date-prefix>.
       Exit on failure if both fail.
    5. On success, switch to the branch, set git branch description from
       the topic's spec description, and persist spex_branch to meta.json.
    """
    import common
    from branch import (
        branch_exists,
        create_branch,
        get_current_branch,
        set_branch_description,
        switch_branch,
    )

    if common.is_topic_completed(topic_dir):
        status = common.format_topic(topic_dir, verbose=2)
        print(f"Error: topic is already completed.\n{status}", file=sys.stderr)
        sys.exit(1)

    if not bool(config["branch_management"]):
        return

    meta = common.load_meta(topic_dir) or {}
    spex_branch = meta.get("spex_branch", "")

    if spex_branch:
        current = get_current_branch(cwd)
        if current != spex_branch:
            if not branch_exists(spex_branch, cwd):
                print(
                    f"Error: spex_branch '{spex_branch}' defined in meta.json "
                    f"does not exist.",
                    file=sys.stderr,
                )
                sys.exit(1)
            try:
                switch_branch(spex_branch, cwd)
            except subprocess.CalledProcessError as e:
                print(
                    f"Error: failed to switch to '{spex_branch}': "
                    f"{e.stderr.strip() or e}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"Switched to branch '{spex_branch}'.")
        return

    topic_name = _extract_topic_name_for_branch(topic_dir, meta)
    short_name = strip_date_prefix(topic_name)

    candidates = [
        f"{DEFAULT_SPEX_BRANCH_PREFIX}{short_name}",
        f"{DEFAULT_SPEX_BRANCH_PREFIX}{topic_name}",
    ]

    created_branch = None
    for candidate in candidates:
        if branch_exists(candidate, cwd):
            created_branch = candidate
            break
        try:
            create_branch(candidate, cwd)
            created_branch = candidate
            break
        except subprocess.CalledProcessError:
            continue

    if created_branch is None:
        print(
            f"Error: failed to create branch. Tried: {', '.join(candidates)}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        switch_branch(created_branch, cwd)
    except subprocess.CalledProcessError as e:
        print(
            f"Error: failed to switch to '{created_branch}': "
            f"{e.stderr.strip() or e}",
            file=sys.stderr,
        )
        sys.exit(1)

    description = common.get_spec_description(topic_dir)
    if description:
        try:
            set_branch_description(created_branch, description, cwd)
        except subprocess.CalledProcessError:
            pass

    meta_path = topic_dir / "meta.json"
    meta["spex_branch"] = created_branch
    common.atomic_write_json(meta_path, meta)

    print(f"Created and switched to branch '{created_branch}'.")


_PRECHECK_USAGE = """\
Usage: spex apply-helper precheck --topic <name>

Validate branch setup for applying a topic.

Options:
  --topic <name>  Topic name (required)
  -h, --help      Show this help message and exit
"""


def cli_precheck(argv=None):
    """CLI: perform branch setup for applying a topic."""
    import common
    import config as cfg
    from cli import ArgumentParser

    parser = ArgumentParser(
        prog="spex apply-helper precheck",
        usage=_PRECHECK_USAGE,
    )
    parser.add_argument("--topic", required=True)
    args = parser.parse(argv)

    ctx = cfg.get_context()
    topic_dir = common.resolve_topic_dir(args.topic)
    validate_apply_branch(ctx.config, topic_dir, cwd=ctx.main_worktree)


_POST_ACTION_USAGE = """\
Usage: spex apply-helper post-action --topic <name>

Run post-action hook and show hint.

Options:
  --topic <name>  Topic name (required)
  -h, --help      Show this help message and exit
"""


def cli_post_action(argv=None):
    """CLI: run post-action hook, and show hint."""
    import common
    import hooks
    from cli import ArgumentParser

    parser = ArgumentParser(
        prog="spex apply-helper post-action",
        usage=_POST_ACTION_USAGE,
    )
    parser.add_argument("--topic", required=True)
    args = parser.parse(argv)

    topic_dir = common.resolve_topic_dir(args.topic)
    topic_name = strip_date_prefix(topic_dir.name)
    meta = common.load_meta(topic_dir)
    spex_branch = meta.get("spex_branch", "") if meta else ""
    if not spex_branch:
        return

    target = meta.get("branch", "main")
    workdir = common.get_current_workdir()

    hooks.run_post_action(
        "apply",
        {
            "topic": topic_name,
            "source_branch": spex_branch,
            "target_branch": target,
        },
        workdir,
        topic_name,
    )

    if hooks.find_hook("post-action", workdir) is None:
        print(
            f"Development completed on topic branch {spex_branch}.\n"
            f"After local code review, run /spex merge to merge into\n"
            f"branch {target}, or create a pull request."
        )


def main(argv=None):
    """Route apply-helper subcommands."""
    if not argv:
        print(USAGE, end="", file=sys.stderr)
        sys.exit(1)

    subcmd = argv[0]
    rest = argv[1:]

    if subcmd in ("-h", "--help"):
        print(USAGE, end="")
        sys.exit(0)
    elif subcmd == "precheck":
        cli_precheck(rest)
    elif subcmd == "post-action":
        cli_post_action(rest)
    else:
        print(f"Error: unknown apply-helper subcommand"
              f" '{subcmd}'", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        sys.exit(1)
