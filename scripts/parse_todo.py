#!/usr/bin/env python3
"""Parse and validate a todo.json file."""

import json
import sys

REQUIRED_FIELDS = {"id", "name", "details", "completed_at", "commit_title"}


def validate(path):
    """Validate todo.json structure and print errors to stderr."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print("Error: top-level value must be an array.", file=sys.stderr)
        sys.exit(1)

    if len(data) == 0:
        print("Error: todo list is empty.", file=sys.stderr)
        sys.exit(1)

    errors = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"  item[{i}]: must be an object.")
            continue
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


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "validate":
        print(
            f"Usage: {sys.argv[0]} validate <todo.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    validate(sys.argv[2])


if __name__ == "__main__":
    main()
