#!/usr/bin/env python3
"""Parse and operate on a todo.json file.

Subcommands:
    validate          Validate structure of a todo.json file.
    get-next-undone   Print the next incomplete task.
    get-done          Print completed tasks.
"""

from __future__ import annotations

import sys

from cli import ArgumentParser
from common import load_and_validate_todo_json, validate_unique_ids

REQUIRED_FIELDS = {"id", "name", "details", "completed_at", "commit_title"}

USAGE = """\
Usage: spex todo <subcommand> [options] <todo.json>

Subcommands:
  validate                              Validate todo.json structure
  get-next-undone [--only-id|--details]  Print next undone task
  get-done [--details]                   Print completed tasks
  mark-done <task-id> <commit-title>     Mark a task as completed
  xml2json <xml-file>                    Convert todo.xml to todo.json

Options:
  -h, --help  Show this help message and exit
"""

VALIDATE_USAGE = """\
Usage: spex todo validate <todo.json>

Validate todo.json structure.

Options:
  -h, --help  Show this help message and exit
"""

GET_NEXT_UNDONE_USAGE = """\
Usage: spex todo get-next-undone [--only-id|--details] <todo.json>

Print the next incomplete task.

Options:
  --only-id   Print only the task ID
  --details   Print full task details
  -h, --help  Show this help message and exit
"""

GET_DONE_USAGE = """\
Usage: spex todo get-done [--details] <todo.json>

Print completed tasks.

Options:
  --details   Print full task details
  -h, --help  Show this help message and exit
"""




def main(argv=None):
    parser = ArgumentParser(prog="spex todo", usage=USAGE)
    subparsers = parser.add_subparsers(dest="command")

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate todo.json")
    p_validate.add_argument("todo_json", help="Path to todo.json")

    # get-next-undone
    p_next = subparsers.add_parser(
        "get-next-undone", help="Print next undone task"
    )
    next_mode = p_next.add_mutually_exclusive_group()
    next_mode.add_argument("--only-id", action="store_true")
    next_mode.add_argument("--details", action="store_true")
    p_next.add_argument("todo_json", help="Path to todo.json")

    # get-done
    p_done = subparsers.add_parser("get-done", help="Print completed tasks")
    p_done.add_argument("--details", action="store_true")
    p_done.add_argument("todo_json", help="Path to todo.json")

    args = parser.parse(argv)

    if args.command == "validate":
        cmd_validate(args)
    elif args.command == "get-next-undone":
        cmd_get_next_undone(args)
    elif args.command == "get-done":
        cmd_get_done(args)
    else:
        parser.print_usage(file=sys.stderr)
        sys.exit(1)


def cmd_validate(args):
    """Validate todo.json structure."""
    data = load_and_validate_todo_json(args.todo_json)

    validate_unique_ids(data)

    errors = []
    for i, item in enumerate(data):
        missing = REQUIRED_FIELDS - set(item.keys())
        if missing:
            errors.append(
                f"  item[{i}]: missing fields: {', '.join(sorted(missing))}"
            )

    if errors:
        print("Error: invalid todo items:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)

    print(f"OK: {len(data)} step(s) validated.")


def cmd_get_next_undone(args):
    """Print the next incomplete task."""
    mode = "--only-id" if args.only_id else "--details" if args.details else ""
    data = load_and_validate_todo_json(args.todo_json, allow_empty=True)

    for item in data:
        if not isinstance(item, dict):
            continue
        if not item.get("completed_at"):
            if mode == "--only-id":
                print(item.get("id", ""))
            elif mode == "--details":
                task_id = item.get("id", "")
                name = item.get("name", "")
                details = item.get("details", "")
                print(f"**Task**: {task_id} - {name}")
                print()
                print("**Implementation Details**:")
                print()
                print("<details>")
                print(f"{details}")
                print()
                print("</details>")
            else:
                print(f"{item.get('id', '')}: {item.get('name', '')}")
            return

    # No undone task found — output nothing, exit 0


def _format_item_summary(item):
    """Format a completed item as a one-line summary."""
    return f"{item.get('id', '')}: {item.get('name', '')}"


def _format_item_details(item):
    """Format a completed item with full details block."""
    task_id = item.get("id", "")
    name = item.get("name", "")
    details = item.get("details", "")
    lines = [
        f"**Task**: {task_id} - {name}",
        "",
        "**Implementation Details**:",
        "",
        "<details>",
        f"{details}",
        "</details>",
        "",
    ]
    return "\n".join(lines)


def _format_done_output(done_items, details_mode):
    """Format all completed items into a single output string."""
    parts = []
    for item in done_items:
        if details_mode:
            parts.append(_format_item_details(item))
        else:
            parts.append(_format_item_summary(item))
    return "\n".join(parts)


def _format_truncated_output(done_items, details_mode):
    """Format truncated output showing only last 10 items."""
    total = len(done_items)
    last_10 = done_items[-10:]
    parts = [f"... ({total} completed, showing last 10)"]
    for item in last_10[:-1]:
        parts.append(_format_item_summary(item))
    last_item = last_10[-1]
    if details_mode:
        parts.append(_format_item_details(last_item))
    else:
        parts.append(_format_item_summary(last_item))
    return "\n".join(parts)


MAX_OUTPUT_BYTES = 10240


def cmd_get_done(args):
    """Print completed tasks."""
    data = load_and_validate_todo_json(args.todo_json, allow_empty=True)

    done_items = [
        item for item in data
        if isinstance(item, dict) and item.get("completed_at")
    ]

    if not done_items:
        return

    details_mode = args.details
    full_output = _format_done_output(done_items, details_mode)

    if len(full_output.encode("utf-8")) <= MAX_OUTPUT_BYTES:
        print(full_output)
    else:
        print(_format_truncated_output(done_items, details_mode))


if __name__ == "__main__":
    main()
