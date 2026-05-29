#!/usr/bin/env python3
"""Remove undone tasks from todo.json, keeping only completed ones."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli import ArgumentParser
from common import atomic_write_json, check_help_flag

USAGE = """\
Usage: spex todo remove-undone <todo.json>

Remove undone tasks from todo.json, keeping only completed ones.

Options:
  -h, --help  Show this help message and exit
"""


def filter_completed_todos(data):
    """Filter a list of todo dicts, returning only completed ones.

    Args:
        data: List of todo item dicts.

    Returns:
        List of only the completed items.
    """
    return [
        item for item in data
        if isinstance(item, dict) and item.get("completed_at")
    ]


def main(argv=None):
    check_help_flag(USAGE, argv)

    parser = ArgumentParser(prog="spex todo remove-undone", usage=USAGE)
    parser.add_argument("todo_path", help="Path to todo.json")
    args = parser.parse(argv)

    todo_path = Path(args.todo_path)

    if not todo_path.is_file():
        print(f"Error: file not found: {todo_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(todo_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print("Error: top-level value must be an array.", file=sys.stderr)
        sys.exit(1)

    completed = filter_completed_todos(data)
    removed = len(data) - len(completed)

    atomic_write_json(todo_path, completed)
    print(f"Removed {removed} undone task(s), {len(completed)} completed task(s) remain.")


if __name__ == "__main__":
    main()
