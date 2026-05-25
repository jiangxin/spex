#!/usr/bin/env python3
"""Parse and operate on a todo.json file.

Subcommands:
    validate          Validate structure of a todo.json file.
    get-next-undone   Print the next incomplete task.
    get-done          Print completed tasks.
"""

import json
import sys

REQUIRED_FIELDS = {"id", "name", "details", "completed_at", "commit_title"}

USAGE = f"""\
Usage: {sys.argv[0]} <command> [options] <todo.json>

Commands:
    validate                     Validate todo.json structure.
    get-next-undone [--only-id|--details] <todo.json>
                                 Print next undone task.
    get-done [--details] <todo.json>
                                 Print completed tasks.
"""


def _load(path):
    """Load and return parsed todo.json data."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)


def cmd_validate(args):
    """Validate todo.json structure."""
    if len(args) != 1:
        print(
            f"Usage: {sys.argv[0]} validate <todo.json>", file=sys.stderr
        )
        sys.exit(1)

    data = _load(args[0])

    if not isinstance(data, list):
        print("Error: top-level value must be an array.", file=sys.stderr)
        sys.exit(1)

    if len(data) == 0:
        print("Error: todo list is empty.", file=sys.stderr)
        sys.exit(1)

    errors = []
    seen_ids = {}
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"  item[{i}]: must be an object.")
            continue
        missing = REQUIRED_FIELDS - set(item.keys())
        if missing:
            errors.append(
                f"  item[{i}]: missing fields: {', '.join(sorted(missing))}"
            )
        item_id = item.get("id", "")
        if not item_id:
            errors.append(f"  item[{i}]: 'id' must not be empty")
        elif item_id in seen_ids:
            errors.append(
                f"  item[{i}]: duplicate id '{item_id}'"
                f" (first seen at item[{seen_ids[item_id]}])"
            )
        else:
            seen_ids[item_id] = i

    if errors:
        print("Error: invalid todo items:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)

    print(f"OK: {len(data)} step(s) validated.")


def cmd_get_next_undone(args):
    """Print the next incomplete task."""
    if len(args) != 2 or args[0] not in ("--only-id", "--details"):
        print(
            f"Usage: {sys.argv[0]} get-next-undone "
            "[--only-id|--details] <todo.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = args[0]
    data = _load(args[1])

    if not isinstance(data, list):
        print("Error: top-level value must be an array.", file=sys.stderr)
        sys.exit(1)

    for item in data:
        if not isinstance(item, dict):
            continue
        if not item.get("completed_at"):
            if mode == "--only-id":
                print(item.get("id", ""))
            else:
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
    details_mode = False
    if args and args[0] == "--details":
        details_mode = True
        args = args[1:]

    if len(args) != 1:
        print(
            f"Usage: {sys.argv[0]} get-done [--details] <todo.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    data = _load(args[0])

    if not isinstance(data, list):
        print("Error: top-level value must be an array.", file=sys.stderr)
        sys.exit(1)

    done_items = [
        item for item in data
        if isinstance(item, dict) and item.get("completed_at")
    ]

    if not done_items:
        return

    full_output = _format_done_output(done_items, details_mode)

    if len(full_output.encode("utf-8")) <= MAX_OUTPUT_BYTES:
        print(full_output)
    else:
        print(_format_truncated_output(done_items, details_mode))


def main():
    if len(sys.argv) < 2:
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "validate": cmd_validate,
        "get-next-undone": cmd_get_next_undone,
        "get-done": cmd_get_done,
    }

    if command not in commands:
        print(f"Error: unknown command '{command}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    commands[command](args)


if __name__ == "__main__":
    main()
