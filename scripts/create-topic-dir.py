#!/usr/bin/env python3
"""Create a topic directory under the spec root."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_specs_dir

TOPIC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
MAX_TOPIC_BYTES = 64


def create_topic(topic, specs_dir):
    """Create a topic directory under specs_dir.

    Returns the created directory path.
    Raises ValueError on invalid input, FileExistsError if topic exists.
    """
    specs_dir = Path(specs_dir)

    if not TOPIC_PATTERN.match(topic):
        raise ValueError(
            f"invalid topic name '{topic}'. "
            "Must match YYYY-MM-DD-HH-MM-<name> with [a-z0-9-]."
        )

    if len(topic.encode("utf-8")) > MAX_TOPIC_BYTES:
        raise ValueError(f"topic name '{topic}' exceeds {MAX_TOPIC_BYTES} bytes.")

    topic_dir = specs_dir / topic
    if topic_dir.exists():
        raise FileExistsError(f"'{topic}' already exists, use a different name.")

    specs_dir.mkdir(parents=True, exist_ok=True)
    topic_dir.mkdir()
    return topic_dir


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <topic>", file=sys.stderr)
        sys.exit(1)

    specs_dir = Path(get_specs_dir())
    topic = sys.argv[1]

    try:
        topic_dir = create_topic(topic, specs_dir)
    except (ValueError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(topic_dir)


if __name__ == "__main__":
    main()
