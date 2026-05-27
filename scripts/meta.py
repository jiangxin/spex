#!/usr/bin/env python3
"""Set key/value in a topic's meta.json.

Usage: meta.py <topic_name> <key> [value]

When value is omitted, it is read from stdin.
When key is 'prompts', the value is appended to the prompts array.
Otherwise the key is set (overwritten) directly.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import atomic_write_json, check_help_flag, get_specs_dir

USAGE = """\
Usage: spex meta <topic_name> <key> [value]

Set key/value in a topic's meta.json.
When value is omitted, it is read from stdin.
When key is 'prompts', the value is appended to the prompts array.

Options:
  -h, --help  Show this help message and exit"""


def main(argv=None):
    check_help_flag(USAGE, argv)
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print(
            f"Usage: {sys.argv[0]} <topic_name> <key> [value]",
            file=sys.stderr,
        )
        sys.exit(1)

    topic_name = args[0]
    key = args[1]

    if len(args) >= 3:
        value = args[2]
    else:
        value = sys.stdin.read()

    specs_dir = Path(get_specs_dir())
    meta_path = specs_dir / topic_name / "meta.json"

    if not meta_path.is_file():
        print(f"Error: file not found: {meta_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if key == "prompts":
        if not isinstance(data.get("prompts"), list):
            data["prompts"] = []
        data["prompts"].append(value)
    else:
        data[key] = value

    atomic_write_json(meta_path, data)

    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    print(content, end="")


if __name__ == "__main__":
    main()
