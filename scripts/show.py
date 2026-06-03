#!/usr/bin/env python3
"""Show detailed information about a single spec topic."""

from __future__ import annotations

import os
import subprocess
import sys

from cli import ArgumentParser
from common import (
    Topic,
    find_matching_topics,
    format_topic,
    get_archives_dir,
    get_specs_dir,
    strip_front_matter,
)
from config import get_project_context
from list import collect_topics


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
    t = Topic.from_dir(topic_dir)
    if t is None:
        return f"(unable to load topic: {topic_dir.name})"

    parts = []

    parts.append(f"{t.icon} [{t.done}/{t.total}] {t.name}")
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


def _prompt_selection(dirs):
    """Show a numbered list of topic directories and prompt user to choose one.

    Args:
        dirs: List of Path objects for topic directories (must be non-empty).

    Returns:
        Path to the selected topic directory.
    """
    display = dirs[:10]
    for i, topic_dir in enumerate(display, 1):
        print(f"  [{i}] {format_topic(topic_dir)}", file=sys.stderr)
    if len(dirs) > 10:
        print(f"  ... ({len(dirs) - 10} more)", file=sys.stderr)

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


def _resolve_topic(name, include_archives=False):
    """Resolve a topic name to its directory, with optional archive search.

    Searches specs_dir first. When include_archives is True, also
    searches archives_dir and merges results (deduplicated).  When
    include_archives is False and no match is found, suggests retrying
    with --archives.

    Args:
        name: Topic name or substring to match.
        include_archives: If True, search both specs and archives.

    Returns:
        Path to the resolved topic directory.
    """
    specs_dir = get_specs_dir()

    matches = find_matching_topics(name, specs_dir)

    if include_archives:
        archives_dir = get_archives_dir()
        archive_matches = find_matching_topics(name, archives_dir)
        seen = {m.resolve() for m in matches}
        for m in archive_matches:
            if m.resolve() not in seen:
                matches.append(m)
                seen.add(m.resolve())

    if not matches:
        print(f"Error: no topic matching '{name}' found.", file=sys.stderr)
        if not include_archives:
            print("Hint: try --archives to search archived topics.",
                  file=sys.stderr)
        sys.exit(1)

    if len(matches) == 1:
        return matches[0]

    return _prompt_selection(sorted(matches, key=lambda d: d.name, reverse=True))


def _select_topic_interactive(include_archives=False, all_projects=False):
    """List topics and prompt user to select one.

    Args:
        include_archives: If True, include archived topics.
        all_projects: If True, skip is_related_to filtering.
    """
    dirs = [get_specs_dir()]
    archive_dirs = []
    if include_archives:
        ad = get_archives_dir()
        dirs.append(ad)
        archive_dirs.append(ad)

    topics = collect_topics(dirs, archive_dirs=archive_dirs)

    ctx = get_project_context()
    if not all_projects:
        topics = [t for t in topics if ctx.is_related_to(t)]

    topic_dirs = sorted(
        [t.path for t in topics],
        key=lambda d: d.name,
        reverse=True,
    )

    if not topic_dirs:
        print("Error: no topics found.", file=sys.stderr)
        sys.exit(1)
    if len(topic_dirs) == 1:
        return topic_dirs[0]

    return _prompt_selection(topic_dirs)


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
        topic_dir = _resolve_topic(args.topic, include_archives=args.archives)
    else:
        topic_dir = _select_topic_interactive(
            include_archives=args.archives,
            all_projects=args.all_projects,
        )

    if args.brief:
        print(_format_default(topic_dir))
    else:
        _paged_output(_format_verbose(topic_dir))


if __name__ == "__main__":
    main()
