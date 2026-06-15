#!/usr/bin/env python3
"""List spec topics with progress and prompt summary."""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

from cli import ArgumentParser
from common import (
    Spec,
    display_ljust,
    display_truncate,
    display_width,
    format_spec,
    gather_specs,
    repo_label,
)

PROMPT_LOG = "prompt.log"
MAX_TOPIC_WIDTH = 38
MAX_LINE_WIDTH = 80


def parse_prompt_log(log_path: Path) -> tuple:
    """Parse prompt.log, return (timestamp, prompt_text) of first entry."""
    if not log_path.is_file():
        return ("", "")
    content = log_path.read_text(encoding="utf-8")

    ts_match = re.search(r"\*\*\[(.+?)\]\*\*", content)
    timestamp = ts_match.group(1) if ts_match else ""

    block_match = re.search(r"```prompt\n(.*?)```", content, re.DOTALL)
    if not block_match:
        return (timestamp, "")

    lines = block_match.group(1).splitlines()
    stripped = [line[4:] if len(line) > 4 else line.strip() for line in lines]
    prompt_text = " ".join(part for part in stripped if part)
    return (timestamp, prompt_text)


def collect_topics(dirs: list, archive_dirs: list | None = None) -> list[Spec]:
    """Collect topic info from given directories."""
    archive_dirs = set(archive_dirs or [])
    topics: list[Spec] = []
    for d in dirs:
        if not d.is_dir():
            continue
        archived = d in archive_dirs
        for sub in d.iterdir():
            if not sub.is_dir():
                continue
            topic = Spec.from_dir(sub, archived=archived)
            if topic is not None:
                topics.append(topic)
    return topics


MAX_REPO_WIDTH = 11


def format_output(
    topics: list, max_width: int = MAX_LINE_WIDTH, show_repo: bool = False
) -> str:
    """Format topics into aligned columns."""
    if not topics:
        return ""

    topics.sort(key=lambda t: t.created_at, reverse=True)

    progress_strs = [f"{t.done}/{t.total}" for t in topics]
    progress_width = max(len(s) for s in progress_strs)

    if show_repo:
        from common import MAX_REPO_WIDTH
        repo_col_width = MAX_REPO_WIDTH + 3 + 1  # [label] + space
    else:
        repo_col_width = 0

    icon_width = 3
    fixed_width = icon_width + repo_col_width + progress_width + 3 + MAX_TOPIC_WIDTH + 2
    prompt_width = max_width - fixed_width

    lines = []
    for topic, prog_str in zip(topics, progress_strs):
        icon = topic.icon
        name = display_truncate(topic.name, MAX_TOPIC_WIDTH)
        name_col = display_ljust(name, MAX_TOPIC_WIDTH)
        prog_col = f"({prog_str})".rjust(progress_width + 2)
        desc = topic.display_text
        prompt_col = display_truncate(desc, prompt_width) if prompt_width > 3 else ""

        if show_repo:
            label = repo_label(topic.workdir)
            repo_col = display_ljust(f"[{label}]", repo_col_width - 1) + " "
        else:
            repo_col = ""
        lines.append(f"{icon} {repo_col}{prog_col} {name_col}  {prompt_col}".rstrip())

    return "\n".join(lines)


def _wrap_text(text: str, width: int = 80, indent: int = 4) -> str:
    """Wrap text at word boundaries with indentation.

    Returns multi-line string where each line (including the first) is
    prefixed with `indent` spaces and does not exceed `width` characters.
    """
    prefix = " " * indent
    max_content = width - indent
    if max_content <= 0:
        return prefix + text

    words = text.split()
    lines = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif display_width(current) + 1 + display_width(word) <= max_content:
            current += " " + word
        else:
            lines.append(prefix + current)
            current = word
    if current:
        lines.append(prefix + current)
    return "\n".join(lines) if lines else prefix


def format_verbose_output(
    topics: list, verbosity: int = 1, show_repo: bool = False
) -> str:
    """Format topics with expanded detail based on verbosity level."""
    if not topics:
        return ""

    if verbosity >= 3:
        return "Use 'spex show <topic>' for detailed view."

    topics.sort(key=lambda t: t.created_at, reverse=True)

    blocks = [
        format_spec(topic, verbose=verbosity, show_repo=show_repo)
        for topic in topics
    ]

    return "\n\n".join(blocks)


def format_json_output(topics: list) -> str:
    """Format topics as a JSON array."""
    topics.sort(key=lambda t: t.created_at, reverse=True)
    return json.dumps(
        [{"topic_name": t.name, "topic_path": str(t.path)} for t in topics],
        ensure_ascii=False,
        indent=2,
    )


def filter_topics(topics: list, patterns: list) -> list:
    """Filter topics by name patterns (substring, glob, or regex)."""
    if not patterns:
        return topics

    def matches(name: str, pattern: str) -> bool:
        if pattern.startswith("^"):
            try:
                return re.search(pattern, name) is not None
            except re.error:
                return False
        if "*" in pattern or "?" in pattern:
            return fnmatch.fnmatch(name, pattern)
        return pattern in name

    return [t for t in topics if any(matches(t.name, p) for p in patterns)]


def _build_parser() -> ArgumentParser:
    """Build the argument parser for ``spex list``."""
    parser = ArgumentParser(
        prog="spex list",
        description="List spec topics with progress.",
    )
    parser.add_argument(
        "--archives",
        action="store_true",
        help="Include archived topics",
    )
    parser.add_argument(
        "--all-projects",
        action="store_true",
        help="Show topics from all projects (disables project filter)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON array",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--must-done",
        action="store_true",
        help="Only show completed topics",
    )
    group.add_argument(
        "--must-undone",
        action="store_true",
        help="Only show topics with undone steps",
    )
    parser.add_argument(
        "patterns",
        nargs="*",
        default=[],
        metavar="pattern",
        help="Filter topics by name pattern",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse(argv)

    topics, show_repo = gather_specs(
        include_archives=args.archives,
        all_projects=args.all_projects,
    )

    topics = filter_topics(topics, args.patterns)

    if args.must_done:
        topics = [t for t in topics if t.is_completed]
    elif args.must_undone:
        topics = [t for t in topics if not t.is_completed]

    if not topics:
        print("No specs found.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(format_json_output(topics))
        return

    verbosity = args.verbose
    if verbosity > 0:
        print(format_verbose_output(topics, verbosity=verbosity, show_repo=show_repo))
    else:
        print(format_output(topics, show_repo=show_repo))


if __name__ == "__main__":
    main()
