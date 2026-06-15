#!/usr/bin/env python3
"""Show detailed information about a single spec topic."""

from __future__ import annotations

import os
import subprocess
import sys

from cli import ArgumentParser
from common import (
    Spec,
    format_topic,
    resolve_topic,
    select_topic_interactive,
    strip_front_matter,
)


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
    t = Spec.from_dir(topic_dir)
    if t is None:
        return f"(unable to load topic: {topic_dir.name})"

    parts = []

    parts.append(f"{t.icon} ({t.done}/{t.total}) {t.name}")
    parts.append("")
    parts.append("# **Specification**")
    parts.append("")
    if t.spec_content is not None:
        parts.append(strip_front_matter(t.spec_content).rstrip())
    else:
        parts.append("(no spec.md found)")

    parts.append("")
    parts.append("----")
    parts.append("")
    parts.append("# **TODO**")
    parts.append("")

    todo = t.todo_data
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



def main(argv=None):
    parser = ArgumentParser(
        prog="spex show",
        description="Show detailed information about a spec topic.",
    )
    parser.add_argument("topic", nargs="?", help="Topic name or substring")
    parser.add_argument("-l", "--list", action="store_true",
                        dest="brief",
                        help="Show brief list format instead of full details")
    parser.add_argument(
        "--archives",
        action="store_true",
        help="Include archived topics in search",
    )
    parser.add_argument(
        "--all-projects",
        action="store_true",
        help="Show topics from all projects (disables project filter)",
    )
    args = parser.parse(argv)

    if args.topic:
        topic_dir = resolve_topic(args.topic, include_archives=args.archives)
    else:
        topic_dir = select_topic_interactive(
            include_archives=args.archives,
            all_projects=args.all_projects,
        )

    if args.brief:
        print(_format_default(topic_dir))
    else:
        _paged_output(_format_verbose(topic_dir))


if __name__ == "__main__":
    main()
