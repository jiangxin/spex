#!/usr/bin/env python3
"""Show detailed information about a single spec topic."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from cli import ArgumentParser
from common import (
    Topic,
    check_help_flag,
    format_topic,
    get_specs_dir,
    get_todo_progress,
    load_todo,
    resolve_topic_dir,
    strip_front_matter,
)

USAGE = """\
Usage: spex show [topic] [-l]

Show detailed information about a spec topic.

If no topic is given and only one exists, it is shown automatically.
If multiple topics exist, an interactive list is displayed.

Options:
  -l, --list     Show brief list format instead of full details
  -h, --help     Show this help message and exit
"""


def _paged_output(text):
    """Output text through a pager if stdout is a tty."""
    if not sys.stdout.isatty():
        print(text)
        return
    pager = os.environ.get("PAGER", "less -R")
    try:
        proc = subprocess.Popen(pager, shell=True, stdin=subprocess.PIPE)
        proc.communicate(input=text.encode())
    except (BrokenPipeError, OSError):
        print(text)


def _format_default(topic_dir):
    """Format topic in list -vv style, reused from common."""
    return format_topic(topic_dir, verbose=2)


def _format_verbose(topic_dir):
    """Format topic with full spec and structured todo."""
    name = topic_dir.name
    n, m = get_todo_progress(topic_dir)
    t = Topic(name=name, path=topic_dir, done=n, total=m)
    icon = t.icon

    spec_path = topic_dir / "spec.md"
    parts = []

    parts.append(f"{icon} [{n}/{m}] {name}")
    parts.append("")
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


def _select_topic_interactive():
    """List topics and prompt user to select one."""
    specs_dir = Path(get_specs_dir())
    if not specs_dir.is_dir():
        print("Error: no topics found.", file=sys.stderr)
        sys.exit(1)

    topics = sorted(
        [d for d in specs_dir.iterdir() if d.is_dir() and (d / "meta.json").exists()],
        key=lambda d: d.name,
        reverse=True,
    )

    if not topics:
        print("Error: no topics found.", file=sys.stderr)
        sys.exit(1)
    if len(topics) == 1:
        return topics[0]

    display = topics[:10]
    for i, topic_dir in enumerate(display, 1):
        print(f"  [{i}] {format_topic(topic_dir)}", file=sys.stderr)
    if len(topics) > 10:
        print(f"  ... ({len(topics) - 10} more)", file=sys.stderr)

    try:
        sys.stderr.write("Enter number to show: ")
        sys.stderr.flush()
        choice = sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)
    if not choice:
        sys.exit(1)

    try:
        idx = int(choice) - 1
    except ValueError:
        print(f"Error: invalid number '{choice}'", file=sys.stderr)
        sys.exit(1)
    if idx < 0 or idx >= len(display):
        print(f"Error: number out of range (1-{len(display)})", file=sys.stderr)
        sys.exit(1)

    return display[idx]


def main(argv=None):
    check_help_flag(USAGE, argv)

    parser = ArgumentParser(prog="spex show", usage=USAGE)
    parser.add_argument("topic", nargs="?", help="Topic name or substring")
    parser.add_argument("-l", "--list", action="store_true",
                        dest="brief",
                        help="Show brief list format instead of full details")
    args = parser.parse(argv)

    if args.topic:
        topic_dir = resolve_topic_dir(args.topic)
    else:
        topic_dir = _select_topic_interactive()

    if args.brief:
        print(_format_default(topic_dir))
    else:
        _paged_output(_format_verbose(topic_dir))


if __name__ == "__main__":
    main()
