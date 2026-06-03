"""Helper utilities for spec creation."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from cli import ArgumentParser
from common import (
    DEFAULT_SPEX_BRANCH_PREFIX,
    TopicMeta,
    atomic_write_json,
    resolve_topic_dir,
    strip_date_prefix,
    wrap_text,
)

TOPIC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
DATE_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-")
MAX_TOPIC_BYTES = 64


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


def _write_meta(topic_dir, ctx, prompt, timestamp, description=""):
    """Write meta.json into topic_dir with project context and prompt."""
    workdir = str(ctx.top_workdir) if ctx.in_git_workdir() else ""
    main_worktree = str(ctx.main_worktree) if ctx.main_worktree else workdir
    meta = TopicMeta(
        topic=strip_date_prefix(Path(topic_dir).name),
        workdir=workdir,
        main_worktree=main_worktree,
        remote_url=ctx.remote_url,
        branch=ctx.branch,
        user_name=ctx.user_name,
        user_email=ctx.user_email,
        created_at=timestamp,
        prompts=[{"text": prompt, "timestamp": timestamp}] if prompt else [],
        description=wrap_text(description) if description else "",
    )
    meta_path = Path(topic_dir) / "meta.json"
    atomic_write_json(meta_path, meta.to_dict())


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

    ctx = cfg.get_project_context()
    current = validate_create_branch(ctx.config, cwd=ctx.main_worktree)
    if current:
        print(f"Valid: currently on branch '{current}'")


def _do_prepare_spec(args):
    """Create topic directory and return JSON with metadata."""
    import json

    import config as cfg
    from common import get_specs_dir, local_iso_timestamp

    specs_dir = get_specs_dir()
    prompt = "" if sys.stdin.isatty() else sys.stdin.read().strip()

    try:
        topic_name, topic_dir = create_topic(args.topic, specs_dir)
    except (ValueError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    ctx = cfg.get_project_context()
    timestamp = local_iso_timestamp()
    _write_meta(topic_dir, ctx, prompt, timestamp, args.description)

    import prompt as prompt_mod

    result = {
        "topic_name": topic_name,
        "topic_path": str(topic_dir),
        "spec_template": prompt_mod.render_prompt("spec-template", topic_name),
    }
    print(json.dumps(result, indent=2))


def cli_prepare_spec(argv=None):
    """CLI: create topic directory and return JSON with metadata."""
    args = _build_parser().parse(["prepare-spec"] + (argv or []))
    _do_prepare_spec(args)


REQUIRED_FIELDS = ("id", "name", "details", "completed_at", "commit_title")


def _do_post_action(args):
    """Validate todo.json and trigger post-action hook."""
    from common import (
        TopicMeta,
        load_and_validate_todo_json,
        load_meta,
        parse_front_matter_description,
        validate_unique_ids,
    )
    from config import get_project_context

    topic_dir = resolve_topic_dir(args.topic)
    json_path = topic_dir / "todo.json"

    if not json_path.is_file():
        print(f"Error: {json_path} not found.", file=sys.stderr)
        sys.exit(1)

    data = load_and_validate_todo_json(json_path)
    validate_unique_ids(data)
    for i, item in enumerate(data):
        for field in REQUIRED_FIELDS:
            if field not in item:
                print(
                    f"Error: item[{i}]: missing required"
                    f" field '{field}'.",
                    file=sys.stderr,
                )
                sys.exit(1)
    print(f"OK: {len(data)} step(s) validated.")

    # Update description from spec.md front-matter
    spec_path = topic_dir / "spec.md"
    if spec_path.is_file():
        spec_content = spec_path.read_text(encoding="utf-8")
        desc = parse_front_matter_description(spec_content)
        if desc:
            meta_path = topic_dir / "meta.json"
            meta_data = load_meta(topic_dir) or TopicMeta()
            meta_data.description = wrap_text(desc)
            atomic_write_json(meta_path, meta_data.to_dict())

    import hooks

    meta = load_meta(topic_dir)
    topic_name = (meta.topic if meta else "") or (
        strip_date_prefix(topic_dir.name)
    )
    ctx = get_project_context()
    workdir = (meta.workdir if meta else "") or (
        str(ctx.top_workdir) if ctx.in_git_workdir() else None
    )
    done = sum(
        1 for item in data
        if isinstance(item, dict) and item.get("completed_at")
    )
    undone = len(data) - done
    hooks.run_post_action(
        args.event_type,
        {"topic": topic_name, "done": done, "undone": undone},
        workdir or None,
        topic_name,
    )


def cli_post_action(argv=None):
    """CLI: validate todo.json and trigger post-action hook."""
    args = _build_parser().parse(["post-action"] + (argv or []))
    _do_post_action(args)


def _build_parser():
    """Build the top-level parser with subcommand sub-parsers."""
    parser = ArgumentParser(
        prog="spex create-helper",
        description="Helper utilities for spec creation.",
    )
    subs = parser.add_subparsers(dest="subcmd", title="Subcommands")

    subs.add_parser(
        "precheck",
        description="Validate branch creation feasibility.",
        help="Validate branch creation feasibility",
    )

    p_prepare = subs.add_parser(
        "prepare-spec",
        description=(
            "Create topic directory and return JSON metadata."
        ),
        help="Create topic directory and return JSON metadata",
    )
    p_prepare.add_argument(
        "--topic", required=True, help="Topic name",
    )
    p_prepare.add_argument(
        "--description", default="",
        help="Brief description (saved to meta.json)",
    )

    p_post = subs.add_parser(
        "post-action",
        description=(
            "Validate todo.json and run post-action hook."
        ),
        help="Validate todo.json and run post-action hook",
    )
    p_post.add_argument(
        "--topic", required=True, help="Topic name",
    )
    p_post.add_argument(
        "--event-type", default="create",
        help="Hook event type (default: create)",
    )

    return parser


def main(argv=None):
    """Parse args, route to subcommand."""
    parser = _build_parser()
    args = parser.parse(argv)

    if not args.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    if args.subcmd == "precheck":
        cli_create_validate()
    elif args.subcmd == "prepare-spec":
        _do_prepare_spec(args)
    elif args.subcmd == "post-action":
        _do_post_action(args)
