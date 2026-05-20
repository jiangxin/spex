#!/usr/bin/env python3
"""Resolve a topic directory under specs.

If a topic name is given, verify it exists.
If no topic name is given, list topics with undone tasks as candidates.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_shared"))
from common import TODO_FILE, get_specs_dir


def _has_undone_tasks(topic_dir):
    """Return True if the topic's todo.json has incomplete items."""
    todo_path = topic_dir / TODO_FILE
    if not todo_path.is_file():
        return False
    try:
        data = json.loads(todo_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, list):
        return False
    return any(
        isinstance(item, dict) and not item.get("completed_at")
        for item in data
    )


def main():
    topic_name = sys.argv[1] if len(sys.argv) > 1 else ""
    specs_dir = Path(get_specs_dir())

    if topic_name:
        topic_dir = specs_dir / topic_name
        if not topic_dir.is_dir():
            print(
                f"Error: topic '{topic_name}' not found in {specs_dir}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(topic_name)
        return

    if not specs_dir.is_dir():
        print(
            f"Error: specs directory does not exist: {specs_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    candidates = sorted(
        d.name
        for d in specs_dir.iterdir()
        if d.is_dir() and _has_undone_tasks(d)
    )

    if not candidates:
        print("Error: no topics with undone tasks found.", file=sys.stderr)
        sys.exit(1)

    for name in candidates:
        print(name)


if __name__ == "__main__":
    main()
