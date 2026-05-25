#!/usr/bin/env python3
"""Archive completed spec topics.

Moves topic directories whose todo.json items are all completed
into the archives directory.
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TODO_FILE, get_archives_dir, get_specs_dir


def is_topic_completed(topic_dir: Path) -> bool:
    """Return True if all tasks in todo.json have non-empty completed_at.

    Returns False if todo.json is missing, unreadable, or has an empty list.
    """
    todo_path = topic_dir / TODO_FILE
    if not todo_path.is_file():
        return False
    try:
        data = json.loads(todo_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, list) or len(data) == 0:
        return False
    return all(
        isinstance(item, dict) and item.get("completed_at")
        for item in data
    )


def find_completed_topics(specs_dir: Path) -> list:
    """Return sorted list of topic paths where all tasks are completed."""
    if not specs_dir.is_dir():
        return []
    return sorted(
        d for d in specs_dir.iterdir()
        if d.is_dir() and is_topic_completed(d)
    )


def move_topic(topic_dir: Path, archives_dir: Path) -> Path:
    """Move topic_dir into archives_dir, appending suffix on conflict.

    Returns the final destination path.
    """
    dest = archives_dir / topic_dir.name
    if not dest.exists():
        shutil.move(str(topic_dir), str(dest))
        return dest

    counter = 2
    while True:
        candidate = archives_dir / f"{topic_dir.name}-{counter}"
        if not candidate.exists():
            shutil.move(str(topic_dir), str(candidate))
            return candidate
        counter += 1


def main():
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    specs_dir = Path(get_specs_dir())
    archives_dir = Path(get_archives_dir())

    completed = find_completed_topics(specs_dir)

    if not completed:
        print("No completed topics to archive.")
        return

    if dry_run:
        print(f"Would archive {len(completed)} topic(s):")
        for topic_dir in completed:
            print(f"  {topic_dir.name}")
        return

    archives_dir.mkdir(parents=True, exist_ok=True)
    for topic_dir in completed:
        dest = move_topic(topic_dir, archives_dir)
        print(f"Archived: {topic_dir.name} -> {dest}")


if __name__ == "__main__":
    main()
