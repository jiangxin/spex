#!/usr/bin/env python3
"""Mark a task as completed in todo.json.

Usage: mark_todo_complete.py <task-id> <commit-title> <todo.json>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import atomic_write_json, local_iso_timestamp


def main():
    if len(sys.argv) != 4:
        print(
            f"Usage: {sys.argv[0]} <task-id> <commit-title> <todo.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    task_id = sys.argv[1]
    commit_title = sys.argv[2]
    todo_path = Path(sys.argv[3])

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
