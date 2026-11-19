#!/usr/bin/env python3
"""CRUD and transaction operations for JSON todo files."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
from argparse import ArgumentTypeError
from pathlib import Path

from acceptance import validate_acceptance_evidence
from cli import ArgumentParser
from common import (
    atomic_write_json,
    filter_completed_todos,
    load_and_validate_todo_json,
    load_meta,
    local_iso_timestamp,
    logger,
    number_todo_items,
    resolve_spec_dir,
    sha_from_commit_title,
    todo_step_label,
    validate_unique_ids,
)
from task_mode import GENERAL

REQUIRED_FIELDS = ("name", "details", "completed_at", "commit_title")

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

def _backup_path(path):
    return path.with_name(f"{path.name}.lock")


def _read_todo(path):
    """Load stored todo entries without changing their IDs.

    Returns an empty list when the file does not exist or is empty.
    """
    path = Path(path)
    if not path.exists():
        return []
    if not path.read_text(encoding="utf-8").strip():
        return []
    data = load_and_validate_todo_json(path, allow_empty=True)
    validate_unique_ids(data, allow_missing=_backup_path(path).exists())
    return data


def load_todo_json(path):
    """Load todo entries with their current positional IDs."""
    return number_todo_items(_read_todo(path))


def _write_todo(path, data):
    if not _backup_path(path).exists():
        number_todo_items(data)
    atomic_write_json(path, data)


def _step_index(data, step_id):
    if not 1 <= step_id <= len(data):
        logger.error("Error: id '%s' not found.", step_id)
        sys.exit(1)
    return step_id - 1


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def validate_todo(todo_path, *, allow_empty=True):
    """Validate the todo list and return its numbered entries."""
    data = load_todo_json(todo_path)
    if not allow_empty and not data:
        logger.error("Error: empty array, nothing to process.")
        sys.exit(1)
    validate_todo_fields(data)
    return data


def validate_todo_fields(data):
    """Validate todo entries independently of their stored IDs."""
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.error("Error: item[%d] is not an object.", i)
            sys.exit(1)
        for field in REQUIRED_FIELDS:
            if field not in item:
                logger.error(
                    "Error: item[%d]: missing required field"
                    " '%s'.", i, field,
                )
                sys.exit(1)
        if "skip_commit" in item:
            normalize_skip_commit(item["skip_commit"])


def cmd_validate(todo_path):
    """Validate the todo list."""
    validate_todo(todo_path)
    logger.info("OK")


def cmd_renumber(todo_path):
    """Replace stored IDs according to the current list order."""
    try:
        if _backup_path(todo_path).exists():
            logger.error("Error: todo transaction is open; use transaction commit to renumber.")
            sys.exit(1)
        data = load_and_validate_todo_json(todo_path, allow_empty=True)
        validate_todo_fields(data)
        atomic_write_json(todo_path, number_todo_items(data))
    except (OSError, UnicodeError) as exc:
        logger.error("Error: cannot renumber todo file '%s': %s", todo_path, exc)
        sys.exit(1)
    logger.info("Renumbered %d step(s).", len(data))


def _is_general_todo(todo_path):
    meta = load_meta(todo_path.resolve().parent)
    return meta is not None and meta.task_mode == GENERAL


def _require_completion_command(todo_path):
    if _is_general_todo(todo_path):
        logger.error("Error: use todo-helper complete to finish a general task with evidence.")
        sys.exit(1)


def _new_todo_entry(todo_path, args):
    """Build an entry from the append or insert options."""
    if args.completed_at:
        _require_completion_command(todo_path)
    if args.details_from_stdin:
        details = sys.stdin.read()
    elif args.details is not None:
        details = args.details
    else:
        logger.error(
            "Error: --details or --details-from-stdin required.",
        )
        sys.exit(1)

    entry = {
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
    return entry


def cmd_append(todo_path, args):
    """Append a new entry to the todo file."""
    entry = _new_todo_entry(todo_path, args)
    data = _read_todo(todo_path)
    data.append(entry)
    _write_todo(todo_path, data)
    logger.info("Appended %s.", todo_step_label(len(data), len(data)))


def cmd_insert(todo_path, args):
    """Insert a new entry before or after an existing position."""
    data = _read_todo(todo_path)
    if args.before is not None:
        index = _step_index(data, args.before)
    else:
        index = _step_index(data, args.after) + 1
    data.insert(index, _new_todo_entry(todo_path, args))
    _write_todo(todo_path, data)
    logger.info("Inserted %s.", todo_step_label(index + 1, len(data)))


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
            sha_from_commit_title(args.commit_title)
            or _short_head_sha()
        )
        emit_apply_task(spec_dir, "committed", id=args.id, sha=sha)


def cmd_edit(todo_path, args):
    """Edit an existing entry by ID."""
    details = args.details
    if args.details_from_stdin:
        details = sys.stdin.read()

    if args.completed_at is not None:
        _require_completion_command(todo_path)
        args.completed_at = _resolve_completed_at(args.completed_at)

    data = _read_todo(todo_path)
    item = data[_step_index(data, args.id)]
    for field, value in (
        ("name", args.step_name), ("details", details),
        ("completed_at", args.completed_at), ("commit_title", args.commit_title),
    ):
        if value is not None:
            item[field] = value
    skip_commit = getattr(args, "skip_commit", None)
    if skip_commit is not None:
        normalized = normalize_skip_commit(skip_commit)
        if normalized == _SKIP_COMMIT_FALSE:
            item.pop("skip_commit", None)
        else:
            item["skip_commit"] = normalized

    _write_todo(todo_path, data)
    logger.info("Updated %s.", todo_step_label(args.id, len(data)))
    _emit_todo_edit_apply_anchor(todo_path, args, item)


def cmd_complete(todo_path, args, *, emit_done=True):
    """Persist completion and its required evidence in a single write."""
    from debug_log import emit_apply_task

    data = validate_todo(todo_path)
    task = data[_step_index(data, args.id)]
    if task["completed_at"]:
        logger.info("%s is already complete.", todo_step_label(args.id, len(data)))
        return data, False

    try:
        general = _is_general_todo(todo_path)
        if general and task is not next(item for item in data if not item["completed_at"]):
            raise ValueError("only the first unfinished general task can be completed")
        if general and not args.acceptance_evidence_stdin:
            raise ValueError("completing a general task requires --acceptance-evidence-stdin")
        if args.acceptance_evidence_stdin:
            if not general:
                raise ValueError("--acceptance-evidence-stdin is for general tasks")
            task["acceptance_evidence"] = validate_acceptance_evidence(json.load(sys.stdin))
        task["completed_at"] = local_iso_timestamp()
        if args.commit_title is not None:
            task["commit_title"] = args.commit_title
        _write_todo(todo_path, data)
    except (OSError, ValueError) as exc:
        logger.error("Error: cannot complete step-%s: %s", args.id, exc)
        sys.exit(1)

    logger.info("Completed %s.", todo_step_label(args.id, len(data)))
    if emit_done:
        emit_apply_task(todo_path.parent, "done", id=args.id)
    return data, True


def cmd_move(todo_path, args):
    """Swap two entries without rewriting their stored IDs."""
    data = _read_todo(todo_path)
    first = _step_index(data, args.from_id)
    second = _step_index(data, args.to_id)
    if first == second:
        return
    data[first], data[second] = data[second], data[first]
    atomic_write_json(todo_path, data)
    logger.info(
        "Swapped %s and %s.",
        todo_step_label(args.from_id, len(data)),
        todo_step_label(args.to_id, len(data)),
    )


def cmd_remove(todo_path, args):
    """Remove an entry by ID."""
    data = _read_todo(todo_path)
    del data[_step_index(data, args.id)]
    _write_todo(todo_path, data)
    logger.info("Removed %s.", todo_step_label(args.id, len(data) + 1))


def cmd_remove_undone(todo_path):
    """Remove incomplete entries, preserving completed entries in order."""
    data = _read_todo(todo_path)
    completed = filter_completed_todos(data)
    removed = len(data) - len(completed)
    if removed:
        _write_todo(todo_path, completed)
        logger.info("Removed %d unfinished step(s).", removed)


class StaleBackupError(SystemExit):
    """A failed start left a backup that cannot safely be restored."""


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
        try:
            current = todo_path.read_bytes() if todo_path.exists() else b""
            if snapshot != current:
                raise OSError(f"{todo_path} changed while opening the transaction")
        except OSError:
            try:
                backup_path.unlink()
            except OSError as exc:
                logger.error(
                    "Cannot remove potentially stale todo backup '%s': %s. "
                    "Preserve the current todo; do not roll back from this backup.",
                    backup_path, exc,
                )
                raise StaleBackupError(1) from exc
            raise


def cmd_transaction(todo_path, action):
    """Start, commit, or roll back a todo file transaction."""
    backup_path = _backup_path(todo_path)
    try:
        if action == "start":
            _start_transaction(todo_path, backup_path)
        elif action == "commit":
            backup_stat = backup_path.lstat()
            if todo_path.exists():
                atomic_write_json(todo_path, validate_todo(todo_path))
            if stat.S_ISDIR(backup_stat.st_mode):
                backup_path.rmdir()
            else:
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


def _format_markdown(data, count, width=0):
    """Format todo entries as markdown.

    width=0 disables wrapping (lines may exceed 80 chars).
    """
    w = width if width > 0 else 10**9
    lines = []
    for idx, item in enumerate(data, 1):
        step_label = todo_step_label(item["id"], count)
        completed = bool(item.get("completed_at"))
        icon = "✅" if completed else "🔲"
        prefix = f"{idx}. "
        indent = " " * len(prefix)
        lines.append(f"{prefix}{icon} {step_label}")

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
    count = len(data)

    if args.step_id:
        data = [data[_step_index(data, args.step_id)]]
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
        print(_format_markdown(data, count, width=80 if args.wrap else 0))
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
    "--from",
    "--to",
    "--before",
    "--after",
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


def _parse_step_id(value):
    """Read a positive integer step ID."""
    if value.isascii() and value.isdecimal():
        try:
            number = int(value)
        except ValueError:
            pass
        else:
            if number > 0:
                return number
    raise ArgumentTypeError(f"expected a positive step ID, got {value!r}")


def _add_new_entry_options(parser):
    """Register fields shared by append and insert."""
    parser.add_argument(
        "--step-name", required=True, help="Task name",
    )
    parser.add_argument(
        "--details", default=None, help="Task details text",
    )
    parser.add_argument(
        "--details-from-stdin", action="store_true",
        help="Read details from stdin",
    )
    parser.add_argument(
        "--completed-at", default="",
        help="Completion timestamp (or 'now')",
    )
    parser.add_argument(
        "--commit-title", default="",
        help="Commit title for the task",
    )
    parser.add_argument(
        "--skip-commit",
        choices=list(_SKIP_COMMIT_VALUES),
        default=None,
        help=(
            "Skip commit mode: false (default, omit key),"
            " auto, or true (lowercase strings only)"
        ),
    )


def _build_parser():
    """Build the top-level parser with subcommand sub-parsers."""
    parser = ArgumentParser(
        prog="spex todo-helper",
        description=(
            "Operate on todo files"
            " (validate, append, insert, edit, complete, move, remove, remove-undone,"
            " renumber, show, transaction)."
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
    _add_new_entry_options(p_append)

    p_insert = subs.add_parser(
        "insert",
        description=(
            "Insert a new entry before or after a current step position from show."
            " Assign stored IDs on transaction commit or immediately outside a transaction."
        ),
        help="Insert a new entry before or after an existing step",
    )
    anchor = p_insert.add_mutually_exclusive_group(required=True)
    anchor.add_argument(
        "--before", type=_parse_step_id, help="Position of the step to insert before",
    )
    anchor.add_argument(
        "--after", type=_parse_step_id, help="Position of the step to insert after",
    )
    _add_new_entry_options(p_insert)

    # edit
    p_edit = subs.add_parser(
        "edit",
        description="Edit an existing entry by ID.",
        help="Edit an existing entry by ID",
    )
    p_edit.add_argument(
        "--id", required=True, type=_parse_step_id, help="Task number to edit",
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

    p_move = subs.add_parser(
        "move",
        description=(
            "Swap two steps by their current positions from show, preserving stored IDs."
            " Commit an open transaction to renumber the file."
        ),
        help="Swap two steps while preserving stored IDs",
    )
    p_move.add_argument(
        "--from", dest="from_id", required=True, type=_parse_step_id,
        help="Position of the first step",
    )
    p_move.add_argument(
        "--to", dest="to_id", required=True, type=_parse_step_id,
        help="Position of the second step",
    )

    # remove
    p_remove = subs.add_parser(
        "remove",
        description="Remove an entry by ID.",
        help="Remove an entry by ID",
    )
    p_remove.add_argument(
        "--id", required=True, type=_parse_step_id, help="Task number to remove",
    )

    p_remove_undone = subs.add_parser(
        "remove-undone",
        help="Remove all unfinished steps",
    )

    p_renumber = subs.add_parser(
        "renumber",
        description=(
            "Write consecutive integer IDs from 1 in current list order."
            " Use transaction commit when a transaction is open."
        ),
        help="Regenerate stored IDs outside a transaction",
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
        "--id", dest="step_id", type=_parse_step_id, default=None,
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
            " commit by assigning numeric IDs, or roll back using the backup."
        ),
        help="Start, commit, or roll back a todo transaction",
    )
    p_transaction.add_argument("action", choices=["start", "commit", "rollback"])

    p_complete = subs.add_parser("complete", help="Complete a task with its acceptance evidence")
    p_complete.add_argument("--id", required=True, type=_parse_step_id, help="Task number")
    p_complete.add_argument("--commit-title", help="Final commit title for the task")
    p_complete.add_argument(
        "--acceptance-evidence-stdin", action="store_true",
        help="Read a JSON array of successful acceptance records for a general task",
    )

    for subparser in (
        p_validate, p_append, p_insert, p_edit, p_complete, p_move, p_remove, p_remove_undone,
        p_renumber, p_show, p_transaction,
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
    elif args.subcmd == "insert":
        cmd_insert(todo_path, args)
    elif args.subcmd == "edit":
        cmd_edit(todo_path, args)
    elif args.subcmd == "complete":
        cmd_complete(todo_path, args)
    elif args.subcmd == "move":
        cmd_move(todo_path, args)
    elif args.subcmd == "remove":
        cmd_remove(todo_path, args)
    elif args.subcmd == "remove-undone":
        cmd_remove_undone(todo_path)
    elif args.subcmd == "renumber":
        cmd_renumber(todo_path)
    elif args.subcmd == "show":
        cmd_show(todo_path, args)
    elif args.subcmd == "transaction":
        cmd_transaction(todo_path, args.action)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
