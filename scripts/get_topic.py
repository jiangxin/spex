#!/usr/bin/env python3
"""Resolve a topic directory under specs.

If a topic name is given, verify it exists.
If no topic name is given, list topics with undone tasks as candidates.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_specs_dir, has_undone_tasks


def resolve_topic(topic_name, specs_dir):
    """Resolve topic name against specs_dir.

    Returns a list of matching topic names.
    Raises SystemExit on error.
    """
    specs_dir = Path(specs_dir)

    if topic_name:
        if (specs_dir / topic_name).is_dir():
            return [topic_name]

        matches = sorted(
            d.name
            for d in specs_dir.iterdir()
            if d.is_dir()
            and topic_name in d.name
            and has_undone_tasks(d)
        )

        if not matches:
            print(
                f"Error: no topic matching '{topic_name}' found in"
                f" {specs_dir}",
                file=sys.stderr,
            )
            sys.exit(1)

        return matches

    if not specs_dir.is_dir():
        print(
            f"Error: specs directory does not exist: {specs_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    candidates = sorted(
        d.name
        for d in specs_dir.iterdir()
        if d.is_dir() and has_undone_tasks(d)
    )

    if not candidates:
        print("Error: no topics with undone tasks found.", file=sys.stderr)
        sys.exit(1)

    return candidates


def main():
    args = sys.argv[1:]
    json_mode = "--json" in args
    if json_mode:
        args = [a for a in args if a != "--json"]

    topic_name = args[0] if args else ""
    specs_dir = Path(get_specs_dir())

    results = resolve_topic(topic_name, specs_dir)
    if json_mode:
        items = [
            {"topic_name": name, "topic_path": str(specs_dir / name)}
            for name in results
        ]
        print(json.dumps(items, indent=2))
    else:
        for name in results:
            print(name)


if __name__ == "__main__":
    main()
