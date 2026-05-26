#!/usr/bin/env python3
"""Show detailed information about a single spec topic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    check_help_flag,
    get_spec_description,
    get_todo_progress,
    load_todo,
    resolve_topic_dir,
    strip_front_matter,
)
from list_specs import _get_icon, _wrap_text

USAGE = """\
Usage: spex show <topic> [-v]

Show detailed information about a spec topic.

Options:
  -v, --verbose  Show full spec and structured todo details
  -h, --help     Show this help message and exit
"""


def _format_default(topic_dir):
    """Format topic in list -vv style."""
    name = topic_dir.name
    n, m = get_todo_progress(topic_dir)
    topic = {"n": n, "m": m, "archived": False}
    icon = _get_icon(topic)
    description = get_spec_description(topic_dir)

    parts = [f"{icon} [{n}/{m}] {name}"]
    if description:
        parts.append(_wrap_text(description))

    todo = load_todo(topic_dir)
    if todo:
        parts.append("")
        for item in todo:
            step_id = item.get("id", "")
            step_name = item.get("name", "")
            parts.append(f"    {step_id}: {step_name}")

    return "\n".join(parts)


def _format_verbose(topic_dir):
    """Format topic with full spec and structured todo."""
    spec_path = topic_dir / "spec.md"
    parts = []

    parts.append("# **Specification**")
    parts.append("")
    if spec_path.is_file():
        content = spec_path.read_text(encoding="utf-8")
        parts.append(strip_front_matter(content).rstrip())
    else:
        parts.append("(no spec.md found)")

    parts.append("")
    parts.append("----")
    parts.append("")
    parts.append("# **TODO**")
    parts.append("")

    todo = load_todo(topic_dir)
    if todo:
        for item in todo:
            step_id = item.get("id", "")
            step_name = item.get("name", "")
            details = item.get("details", "")
            parts.append(f"- **{step_id}: {step_name}**")
            parts.append("")
            if details:
                for line in details.splitlines():
                    parts.append(f"  {line}" if line else "")
                parts.append("")
    else:
        parts.append("(no tasks)")

    return "\n".join(parts).rstrip()


def main():
    check_help_flag(USAGE)

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]

    verbose = any(f in ("-v", "--verbose") for f in flags)

    if not args:
        print("Error: topic name is required.", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    topic_name = args[0]

    try:
        topic_dir = resolve_topic_dir(topic_name)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(_format_verbose(topic_dir))
    else:
        print(_format_default(topic_dir))


if __name__ == "__main__":
    main()
