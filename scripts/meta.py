#!/usr/bin/env python3
"""Get or set key/value in a topic's meta.json.

Usage: spex meta <topic_name> [key] [value] [--stdin]

When no key is given, display all meta.json contents.
When key is given without value, display that key's value.
When key + value is given, set the key.
When key + --stdin is given, read value from stdin and set.
When key is 'prompts', the value is appended to the prompts array.
"""

from __future__ import annotations

import json
import sys

from common import atomic_write_json, check_help_flag, get_specs_dir

USAGE = """\
Usage: spex meta <topic_name> [key] [value] [--stdin]

Get or set key/value in a topic's meta.json.

Modes:
  spex meta <topic>              Show all meta key/values
  spex meta <topic> <key>        Show value for a specific key
  spex meta <topic> <key> <val>  Set key to value
  spex meta <topic> <key> --stdin  Set key from stdin

When key is 'prompts', the value is appended to the prompts array.

Options:
  --stdin       Read value from stdin
  -h, --help    Show this help message and exit"""


def _format_value(key, value, indent=""):
    """Format a single key-value pair for display."""
    if isinstance(value, list):
        lines = [f"{indent}{key}:"]
        for item in value:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    prefix = "- " if first else "  "
                    lines.append(f"{indent}{prefix}{k}: {v}")
                    first = False
            else:
                lines.append(f"{indent}- {item}")
        return "\n".join(lines)
    return f"{indent}{key}: {value}"


def _display_all(data):
    """Display all meta.json contents in config-like format."""
    for key, value in data.items():
        print(_format_value(key, value))


def _display_key(data, key):
    """Display a specific key's value."""
    if key not in data:
        print(f"Error: key '{key}' not found in meta.json", file=sys.stderr)
        sys.exit(1)
    value = data[key]
    if isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2, ensure_ascii=False))
    else:
        print(value)


def _set_key(data, key, value, meta_path):
    """Set a key in meta.json and write back."""
    if key == "prompts":
        if not isinstance(data.get("prompts"), list):
            data["prompts"] = []
        data["prompts"].append(value)
    else:
        data[key] = value

    atomic_write_json(meta_path, data)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    print(content, end="")


def main(argv=None):
    check_help_flag(USAGE, argv)
    args = argv if argv is not None else sys.argv[1:]

    stdin_flag = "--stdin" in args
    if stdin_flag:
        args = [a for a in args if a != "--stdin"]

    if len(args) < 1:
        print("Error: topic_name is required.", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    topic_name = args[0]
    key = args[1] if len(args) >= 2 else None
    value = args[2] if len(args) >= 3 else None

    specs_dir = get_specs_dir()
    meta_path = specs_dir / topic_name / "meta.json"

    if not meta_path.is_file():
        print(f"Error: file not found: {meta_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if key is None:
        _display_all(data)
    elif value is not None:
        _set_key(data, key, value, meta_path)
    elif stdin_flag:
        value = sys.stdin.read()
        _set_key(data, key, value, meta_path)
    else:
        _display_key(data, key)


if __name__ == "__main__":
    main()
