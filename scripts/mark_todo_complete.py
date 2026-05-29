#!/usr/bin/env python3
"""Mark a task as completed in todo.json.

Usage: mark_todo_complete.py <task-id> <commit-title> <todo.json>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli import ArgumentParser
from common import atomic_write_json, check_help_flag, local_iso_timestamp

USAGE = """\
Usage: spex todo mark-done <task-id> <commit-title> <todo.json>

Mark a task as completed in todo.json.

Options:
  -h, --help  Show this help message and exit
"""


def main(argv=None):
    check_help_flag(USAGE, argv)

    parser = ArgumentParser(prog="spex todo mark-done", usage=USAGE)
    parser.add_argument("task_id", help="Task ID to mark as done")
    parser.add_argument("commit_title", help="Commit title")
    parser.add_argument("todo_path", help="Path to todo.json")
    args = parser.parse(argv)

    task_id = args.task_id
    commit_title = args.commit_title
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

    found = False
    for item in data:
        if isinstance(item, dict) and item.get("id") == task_id:
            item["completed_at"] = local_iso_timestamp()
            item["commit_title"] = commit_title
            found = True
            break

    if not found:
        print(
            f"Error: task '{task_id}' not found in {todo_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    atomic_write_json(todo_path, data)
    print(f"Marked '{task_id}' as completed.")


if __name__ == "__main__":
    main()
