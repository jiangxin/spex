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
from dataclasses import fields

from cli import ArgumentParser
from common import TopicMeta, atomic_write_json, resolve_topic_dir


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


def _set_key(meta, key, value, meta_path):
    """Set a key in TopicMeta and write back."""
    if key == "prompts":
        from common import local_iso_timestamp
        if not isinstance(meta.prompts, list):
            meta.prompts = []
        meta.prompts.append({"text": value, "timestamp": local_iso_timestamp()})
    else:
        known = {f.name for f in fields(TopicMeta)} - {"extras"}
        if key in known:
            setattr(meta, key, value)
        else:
            meta.extras[key] = value

    data = meta.to_dict()
    atomic_write_json(meta_path, data)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    print(content, end="")


def _build_parser() -> ArgumentParser:
    """Build the argument parser for ``spex meta``."""
    parser = ArgumentParser(
        prog="spex meta",
        description="Get or set key/value in a topic's meta.json.",
    )
    parser.add_argument(
        "topic_name",
        help="Topic name to look up",
    )
    parser.add_argument(
        "key",
        nargs="?",
        default=None,
        help="Meta key to get or set",
    )
    parser.add_argument(
        "value",
        nargs="?",
        default=None,
        help="Value to set for the key",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        dest="stdin_flag",
        help="Read value from stdin instead of positional argument",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse(argv)

    topic_name = args.topic_name
    key = args.key
    value = args.value
    stdin_flag = args.stdin_flag

    topic_dir = resolve_topic_dir(topic_name)
    meta_path = topic_dir / "meta.json"

    if not meta_path.is_file():
        print(f"Error: file not found: {meta_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    meta = TopicMeta.from_dict(data)

    if key is None:
        _display_all(meta.to_dict())
    elif value is not None:
        _set_key(meta, key, value, meta_path)
    elif stdin_flag:
        value = sys.stdin.read()
        _set_key(meta, key, value, meta_path)
    else:
        _display_key(meta.to_dict(), key)


if __name__ == "__main__":
    main()
