#!/usr/bin/env python3
"""Create a topic directory under the spec root."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_specs_dir


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <topic>", file=sys.stderr)
        sys.exit(1)

    specs_dir = Path(get_specs_dir())
    topic = sys.argv[1]

    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
    if not pattern.match(topic):
        print(
            f"Error: invalid topic name '{topic}'. "
            "Must match YYYY-MM-DD-<name> with [a-z0-9-].",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(topic.encode("utf-8")) > 64:
        print(
            f"Error: topic name '{topic}' exceeds 64 bytes.",
            file=sys.stderr,
        )
        sys.exit(1)

    topic_dir = specs_dir / topic
    if topic_dir.exists():
        print(
            f"Error: '{topic}' already exists, use a different name.",
            file=sys.stderr,
        )
        sys.exit(1)

    specs_dir.mkdir(parents=True, exist_ok=True)
    topic_dir.mkdir()
    print(topic_dir)


if __name__ == "__main__":
    main()
