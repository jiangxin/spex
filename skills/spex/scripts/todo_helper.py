#!/usr/bin/env python3
"""CRUD and transaction operations for JSON todo files."""

from __future__ import annotations

import json
import os
import string
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from cli import ArgumentParser
from common import (
    atomic_write_json,
    filter_completed_todos,
    load_and_validate_todo_json,
    local_iso_timestamp,
    logger,
    resolve_spec_dir,
    validate_unique_ids,
)

REQUIRED_FIELDS = ("id", "name", "details", "completed_at", "commit_title")

_SKIP_COMMIT_FALSE = "false"
_SKIP_COMMIT_AUTO = "auto"
_SKIP_COMMIT_TRUE = "true"
_SKIP_COMMIT_VALUES = (
    _SKIP_COMMIT_FALSE, _SKIP_COMMIT_AUTO, _SKIP_COMMIT_TRUE,
)


def normalize_skip_commit(value=None):
    """Normalize skip_commit to 'false'|'auto'|'true'.

    Missing/None/false/False/"false" → "false".
    "auto" → "auto".
    true/True/"true" → "true".
    Any other value exits with code 1.
    """
    if value is None or value is False or value == _SKIP_COMMIT_FALSE:
        return _SKIP_COMMIT_FALSE
    if value is True or value == _SKIP_COMMIT_TRUE:
        return _SKIP_COMMIT_TRUE
    if value == _SKIP_COMMIT_AUTO:
        return _SKIP_COMMIT_AUTO
    logger.error(
        "Error: invalid skip_commit value %r;"
        " expected false, auto, or true.",
        value,
    )
    sys.exit(1)


def _resolve_completed_at(value):
    """Resolve the special value 'now' to a local ISO timestamp."""
    if isinstance(value, str) and value.lower() == "now":
        return local_iso_timestamp()
    return value


# ---------------------------------------------------------------------------
# JSON file loading
# ---------------------------------------------------------------------------

def load_todo_json(path):
    """Load todo entries from a JSON file.

    Returns an empty list when the file does not exist or is empty.
    """
    path = Path(path)
    if not path.is_file():
        return []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    return load_and_validate_todo_json(path, allow_empty=True)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_validate(todo_path):
    """Validate todo file format and check for duplicate IDs."""
    data = load_todo_json(todo_path)
    validate_unique_ids(data)
    for i, item in enumerate(data):
        for field in REQUIRED_FIELDS:
            if field not in item:
                logger.error(
                    "Error: item[%d]: missing required field"
                    " '%s'.", i, field,
                )
                sys.exit(1)
        if "skip_commit" in item:
            normalize_skip_commit(item["skip_commit"])
    logger.info("OK")


def cmd_append(todo_path, args):
    """Append a new entry to the todo file."""
    if args.details_from_stdin:
        details = sys.stdin.read()
    elif args.details is not None:
        details = args.details
    else:
        logger.error(
            "Error: --details or --details-from-stdin required.",
        )
        sys.exit(1)

    data = load_todo_json(todo_path)

    for item in data:
        if isinstance(item, dict) and item.get("id") == args.id:
            logger.error(
                "Error: duplicate id '%s'.", args.id,
            )
            sys.exit(1)

    entry = {
        "id": args.id,
        "name": args.step_name,
        "details": details,
        "completed_at": _resolve_completed_at(args.completed_at),
        "commit_title": args.commit_title,
    }
    skip_commit = getattr(args, "skip_commit", None)
    if skip_commit is not None:
        normalized = normalize_skip_commit(skip_commit)
        # Omit key for default false so files stay compact.
        if normalized != _SKIP_COMMIT_FALSE:
            entry["skip_commit"] = normalized
    data.append(entry)
    atomic_write_json(todo_path, data)
    logger.info("Appended '%s'.", args.id)


def _short_head_sha() -> str:
    """Return short HEAD sha, or empty string when unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _sha_from_commit_title(commit_title) -> str:
    """Extract leading short sha from persisted ``%h: %s`` commit_title."""
    prefix = str(commit_title).split(":", 1)[0].strip()
    if (
        4 <= len(prefix) <= 40
        and all(c in string.hexdigits for c in prefix)
    ):
        return prefix
    return ""


def _emit_todo_edit_apply_anchor(todo_path, args, item) -> None:
    """Emit APPLY anchors for commit-title / completed_at edits."""
    from debug_log import emit_apply_task

    # todo.json lives directly under the spec directory.
    spec_dir = Path(todo_path).parent

    if args.completed_at is not None and item.get("completed_at"):
        emit_apply_task(spec_dir, "done", id=args.id)
        return

    if (
        args.commit_title is not None
        and str(args.commit_title).strip()
        and not item.get("completed_at")
    ):
        # Prefer sha already persisted in commit_title over probing HEAD.
        sha = (
            _sha_from_commit_title(args.commit_title)
            or _short_head_sha()
        )
        emit_apply_task(spec_dir, "committed", id=args.id, sha=sha)


def cmd_edit(todo_path, args):
    """Edit an existing entry by ID."""
    details = args.details
    if args.details_from_stdin:
        details = sys.stdin.read()

    if args.completed_at is not None:
        args.completed_at = _resolve_completed_at(args.completed_at)

    data = load_todo_json(todo_path)

    found = False
    updated_item = None
    for item in data:
        if isinstance(item, dict) and item.get("id") == args.id:
            if args.step_name is not None:
                item["name"] = args.step_name
            if details is not None:
                item["details"] = details
            if args.completed_at is not None:
                item["completed_at"] = args.completed_at
            if args.commit_title is not None:
                item["commit_title"] = args.commit_title
            skip_commit = getattr(args, "skip_commit", None)
            if skip_commit is not None:
                normalized = normalize_skip_commit(skip_commit)
                if normalized == _SKIP_COMMIT_FALSE:
                    item.pop("skip_commit", None)
                else:
                    item["skip_commit"] = normalized
            found = True
            updated_item = item
            break

    if not found:
        logger.error(
            "Error: id '%s' not found.", args.id,
        )
        sys.exit(1)

    atomic_write_json(todo_path, data)
    logger.info("Updated '%s'.", args.id)
    if updated_item is not None:
        _emit_todo_edit_apply_anchor(todo_path, args, updated_item)


def cmd_remove(todo_path, args):
    """Remove an entry by ID."""
    data = load_todo_json(todo_path)

    new_data = [
        item for item in data
        if not (isinstance(item, dict) and item.get("id") == args.id)
    ]

    if len(new_data) == len(data):
        logger.error(
            "Error: id '%s' not found.", args.id,
        )
        sys.exit(1)

    atomic_write_json(todo_path, new_data)
    logger.info("Removed '%s'.", args.id)


def cmd_remove_undone(todo_path):
    """Remove incomplete entries, preserving completed entries in order."""
    data = load_todo_json(todo_path)
    completed = filter_completed_todos(data)
    removed = len(data) - len(completed)
    if removed:
        atomic_write_json(todo_path, completed)
        logger.info("Removed %d unfinished step(s).", removed)


def _start_transaction(todo_path, backup_path):
    """Publish a complete snapshot without replacing an existing backup."""
    try:
        snapshot = todo_path.read_bytes()
    except FileNotFoundError:
        snapshot = b""

    with tempfile.NamedTemporaryFile(
        dir=backup_path.parent, prefix=f".{backup_path.name}.",
    ) as temporary:
        if snapshot.decode("utf-8", errors="surrogateescape").strip():
            temporary.write(snapshot)
            temporary.flush()
        os.link(temporary.name, backup_path)


def cmd_transaction(todo_path, action):
    """Start, commit, or roll back a todo file transaction."""
    backup_path = todo_path.with_name(f"{todo_path.name}.lock")
    try:
        if action == "start":
            _start_transaction(todo_path, backup_path)
        elif action == "commit":
            backup_path.unlink()
        elif backup_path.stat().st_size:
            backup_path.replace(todo_path)
        else:
            todo_path.unlink(missing_ok=True)
            backup_path.unlink()
    except OSError as exc:
        logger.error(
            "Error: cannot %s todo transaction using '%s': %s",
            action, backup_path, exc,
        )
        sys.exit(1)


def _wrap_field(label, text, indent, width=10**9):
    """Wrap a sub-bullet field."""
    prefix = f"{indent}- {label}: "
    cont = " " * len(prefix)
    result = []
    for i, paragraph in enumerate(text.split("\n")):
        if i == 0:
            result.append(textwrap.fill(
                paragraph, width=width,
                initial_indent=prefix,
                subsequent_indent=cont,
            ))
        else:
            result.append(textwrap.fill(
                paragraph, width=width,
                initial_indent=cont,
                subsequent_indent=cont,
            ) if paragraph.strip() else cont.rstrip())
    return "\n".join(result)


def _format_block_details(text, indent, width=10**9):
    """Format multi-line details using block scalar syntax."""
    content_indent = " " * (len(indent) + 4)
    lines = [f"{indent}- details: |"]
    for paragraph in text.split("\n"):
        if paragraph.strip():
            lines.append(textwrap.fill(
                paragraph, width=width,
                initial_indent=content_indent,
                subsequent_indent=content_indent,
            ))
        else:
            lines.append("")
    return "\n".join(lines)


def _format_markdown(data, width=0):
    """Format todo entries as markdown.

    width=0 disables wrapping (lines may exceed 80 chars).
    """
    w = width if width > 0 else 10**9
    lines = []
    for idx, item in enumerate(data, 1):
        step_id = item.get("id", "")
        completed = bool(item.get("completed_at"))
        icon = "✅" if completed else "🔲"
        prefix = f"{idx}. "
        indent = " " * len(prefix)
        lines.append(f"{prefix}{icon} {step_id}")

        name = item.get("name", "")
        if name:
            lines.append(f"{indent}- name: {name}")

        details = item.get("details", "")
        if details:
            if "\n" in details:
                lines.append(
                    _format_block_details(details, indent, w),
                )
            else:
                lines.append(
                    _wrap_field("details", details, indent, w),
                )

        completed_at = item.get("completed_at", "")
        if completed_at:
            lines.append(f"{indent}- completed_at: {completed_at}")

        commit_title = item.get("commit_title", "")
        if commit_title:
            lines.append(
                _wrap_field("commit_title", commit_title, indent, w),
            )

        if "skip_commit" in item:
            skip_commit = normalize_skip_commit(item["skip_commit"])
            if skip_commit != _SKIP_COMMIT_FALSE:
                lines.append(f"{indent}- skip_commit: {skip_commit}")

    return "\n".join(lines)


def cmd_show(todo_path, args):
    """Display entries with optional filtering and format."""
    data = load_todo_json(todo_path)

    if args.step_id:
        data = [
            item for item in data
            if isinstance(item, dict) and item.get("id") == args.step_id
        ]
        if not data:
            logger.error(
                "Error: id '%s' not found.", args.step_id,
            )
            sys.exit(1)
    elif args.done:
        data = [
            item for item in data
            if isinstance(item, dict) and item.get("completed_at")
        ]
    elif args.undone:
        data = [
            item for item in data
            if isinstance(item, dict) and not item.get("completed_at")
        ]

    if args.fmt == "markdown":
        print(_format_markdown(data, width=80 if args.wrap else 0))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _resolve_todo_path(args):
    """Resolve the JSON todo file path from parsed global arguments."""
    if args.todo_file:
        return Path(args.todo_file)
    return resolve_spec_dir(args.name) / "todo.json"


_LOCATOR_FLAGS_WITH_VALUE = ("--todo-file",)
# Subcommand options that take a value. Their next argv token must
# not be classified as a hoistable locator, even when it looks like
# a flag (e.g. ``--commit-title --name``).
_VALUE_TAKING_SUB_FLAGS = frozenset({
    "--id",
    "--step-name",
    "--details",
    "--completed-at",
    "--commit-title",
    "--format",
})


def _hoist_locator_flags(argv):
    """Move locator flags before the subcommand for argparse.

    Agents sometimes place ``--todo-file``
    after the subcommand; argparse only accepts parent options before
    it. Hoisting keeps mutual exclusivity and existing parse paths.

    Value-taking subcommand flags keep their following token so a
    value that literally equals a locator flag is not stolen.
    """
    argv = list(argv)
    hoisted = []
    remaining = []
    i = 0
    n = len(argv)
    while i < n:
        arg = argv[i]
        if arg in _LOCATOR_FLAGS_WITH_VALUE:
            # Only hoist when a value token follows; leave bare
            # --todo-file in place so argparse reports
            # the real missing-argument error instead of rewriting
            # the subcommand into the flag value.
            if i + 1 < n and not argv[i + 1].startswith("-"):
                hoisted.append(arg)
                hoisted.append(argv[i + 1])
                i += 2
            else:
                remaining.append(arg)
                i += 1
            continue
        if arg.startswith("--todo-file="):
            hoisted.append(arg)
            i += 1
            continue
        if arg in _VALUE_TAKING_SUB_FLAGS:
            remaining.append(arg)
            i += 1
            # Consume the value even when it looks like an option
            # (argparse accepts that for unknown-to-subparser tokens).
            if i < n:
                remaining.append(argv[i])
                i += 1
            continue
        if arg.startswith("--") and "=" in arg:
            flag, _sep, _val = arg.partition("=")
            if flag in _VALUE_TAKING_SUB_FLAGS:
                remaining.append(arg)
                i += 1
                continue
        remaining.append(arg)
        i += 1
    if remaining and not remaining[0].startswith("-"):
        remaining[0] = remaining[0].replace("_", "-")
    return hoisted + remaining


def _build_parser():
    """Build the top-level parser with subcommand sub-parsers."""
    parser = ArgumentParser(
        prog="spex todo-helper",
        description=(
            "Operate on todo files"
            " (validate, append, edit, remove, remove-undone, show, transaction)."
        ),
    )
    parser.add_argument(
        "--todo-file",
        help=(
            "Direct path to todo file"
            " (accepted before or after the subcommand)"
        ),
    )

    subs = parser.add_subparsers(dest="subcmd", title="Subcommands")

    # validate
    p_validate = subs.add_parser(
        "validate",
        description=(
            "Validate todo file format and check"
            " for duplicate IDs."
        ),
        help="Validate todo file format and check duplicate IDs",
    )

    # append
    p_append = subs.add_parser(
        "append",
        description="Append a new entry to the todo file.",
        help="Append a new entry",
    )
    p_append.add_argument(
        "--id", required=True, help="Task ID",
    )
    p_append.add_argument(
        "--step-name", required=True, help="Task name",
    )
    p_append.add_argument(
        "--details", default=None, help="Task details text",
    )
    p_append.add_argument(
        "--details-from-stdin", action="store_true",
        help="Read details from stdin",
    )
    p_append.add_argument(
        "--completed-at", default="",
        help="Completion timestamp (or 'now')",
    )
    p_append.add_argument(
        "--commit-title", default="",
        help="Commit title for the task",
    )
    p_append.add_argument(
        "--skip-commit",
        choices=list(_SKIP_COMMIT_VALUES),
        default=None,
        help=(
            "Skip commit mode: false (default, omit key),"
            " auto, or true (lowercase strings only)"
        ),
    )

    # edit
    p_edit = subs.add_parser(
        "edit",
        description="Edit an existing entry by ID.",
        help="Edit an existing entry by ID",
    )
    p_edit.add_argument(
        "--id", required=True, help="Task ID to edit",
    )
    p_edit.add_argument(
        "--step-name", default=None, help="New task name",
    )
    p_edit.add_argument(
        "--details", default=None, help="New details text",
    )
    p_edit.add_argument(
        "--details-from-stdin", action="store_true",
        help="Read details from stdin",
    )
    p_edit.add_argument(
        "--completed-at", default=None,
        help="Completion timestamp (or 'now')",
    )
    p_edit.add_argument(
        "--commit-title", default=None,
        help="Commit title for the task",
    )
    p_edit.add_argument(
        "--skip-commit",
        choices=list(_SKIP_COMMIT_VALUES),
        default=None,
        help=(
            "Skip commit mode: false (clears key),"
            " auto, or true (lowercase strings only)"
        ),
    )

    # remove
    p_remove = subs.add_parser(
        "remove",
        description="Remove an entry by ID.",
        help="Remove an entry by ID",
    )
    p_remove.add_argument(
        "--id", required=True, help="Task ID to remove",
    )

    p_remove_undone = subs.add_parser(
        "remove-undone",
        help="Remove all unfinished steps",
    )

    # show
    p_show = subs.add_parser(
        "show",
        description=(
            "Display entries with filtering and format options."
        ),
        help="Display entries with filtering and format options",
    )
    show_filter = p_show.add_mutually_exclusive_group()
    show_filter.add_argument(
        "--done", action="store_true",
        help="Show only completed entries",
    )
    show_filter.add_argument(
        "--undone", action="store_true",
        help="Show only incomplete entries",
    )
    p_show.add_argument(
        "--id", dest="step_id", default=None,
        help=(
            "Show a single entry by ID "
            "(ignores --done/--undone if set)"
        ),
    )
    p_show.add_argument(
        "--format", dest="fmt",
        choices=["json", "markdown"], default="json",
        help="Output format (default: json)",
    )
    wrap_group = p_show.add_mutually_exclusive_group()
    wrap_group.add_argument(
        "--wrap", action="store_true", default=False,
        help="Wrap long lines at 80 columns",
    )
    wrap_group.add_argument(
        "--no-wrap", dest="wrap", action="store_false",
        help="Do not wrap lines (default)",
    )

    p_transaction = subs.add_parser(
        "transaction",
        description=(
            "Start by backing up the todo file to a .lock file,"
            " commit by deleting the backup, or roll back using the backup."
        ),
        help="Start, commit, or roll back a todo transaction",
    )
    p_transaction.add_argument("action", choices=["start", "commit", "rollback"])

    for subparser in (
        p_validate, p_append, p_edit, p_remove, p_remove_undone, p_show, p_transaction,
    ):
        subparser.add_argument(
            "name", nargs="?", metavar="<spec-name>",
            help="Spec name (omit when using --todo-file)",
        )

    return parser


def _parse_args(parser, argv):
    args = parser.parse(_hoist_locator_flags(argv))
    if args.subcmd:
        if (args.name is None) == (args.todo_file is None):
            parser.error("Provide exactly one of <spec-name> or --todo-file.")
        if args.name == "" or args.todo_file == "":
            parser.error("<spec-name> and --todo-file must be nonempty when provided.")
    return args


def main(argv=None):
    """Parse args, resolve todo path, route to subcommand."""
    parser = _build_parser()
    if argv is None:
        argv = sys.argv[1:]
    args = _parse_args(parser, argv)

    if not args.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(0)

    todo_path = _resolve_todo_path(args)

    if args.subcmd == "validate":
        cmd_validate(todo_path)
    elif args.subcmd == "append":
        cmd_append(todo_path, args)
    elif args.subcmd == "edit":
        cmd_edit(todo_path, args)
    elif args.subcmd == "remove":
        cmd_remove(todo_path, args)
    elif args.subcmd == "remove-undone":
        cmd_remove_undone(todo_path)
    elif args.subcmd == "show":
        cmd_show(todo_path, args)
    elif args.subcmd == "transaction":
        cmd_transaction(todo_path, args.action)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
