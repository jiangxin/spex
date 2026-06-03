#!/usr/bin/env python3
"""List spec topics with progress and prompt summary."""

from __future__ import annotations

import re
from pathlib import Path

from cli import ArgumentParser
from common import (
    Topic,
    format_topic,
    get_archives_dir,
    get_specs_dir,
)
from config import get_project_context

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


def collect_topics(dirs: list, archive_dirs: list | None = None) -> list[Topic]:
    """Collect topic info from given directories."""
    archive_dirs = set(archive_dirs or [])
    topics: list[Topic] = []
    for d in dirs:
        if not d.is_dir():
            continue
        archived = d in archive_dirs
        for sub in d.iterdir():
            if not sub.is_dir():
                continue
            topic = Topic.from_dir(sub, archived=archived)
            if topic is not None:
                topics.append(topic)
    return topics


def _truncate(text: str, width: int) -> str:
    """Truncate text to width, appending ... if needed."""
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


MAX_REPO_WIDTH = 11


def _repo_label(workdir: str) -> str:
    """Return truncated basename of workdir for display."""
    name = Path(workdir).name if workdir else "?"
    if len(name) > MAX_REPO_WIDTH:
        return name[:8] + "..."
    return name


def format_output(
    topics: list, max_width: int = MAX_LINE_WIDTH, show_repo: bool = False
) -> str:
    """Format topics into aligned columns."""
    if not topics:
        return "No specs found."

    topics.sort(key=lambda t: t.created_at, reverse=True)

    progress_strs = [f"{t.done}/{t.total}" for t in topics]
    progress_width = max(len(s) for s in progress_strs)

    repo_labels = []
    if show_repo:
        repo_labels = [_repo_label(t.workdir) for t in topics]
        max_label_width = max(len(lb) for lb in repo_labels)
        repo_col_width = max_label_width + 3  # brackets + trailing space
    else:
        repo_col_width = 0

    icon_width = 3
    fixed_width = repo_col_width + icon_width + MAX_TOPIC_WIDTH + 2 + progress_width + 2
    prompt_width = max_width - fixed_width

    lines = []
    for i, (topic, prog_str) in enumerate(zip(topics, progress_strs)):
        icon = topic.icon
        name = _truncate(topic.name, MAX_TOPIC_WIDTH)
        name_col = name.ljust(MAX_TOPIC_WIDTH)
        prog_col = prog_str.rjust(progress_width)
        display_text = topic.display_text
        prompt_col = _truncate(display_text, prompt_width) if prompt_width > 3 else ""

        if show_repo:
            repo_col = f"[{repo_labels[i]}]".ljust(repo_col_width - 1) + " "
            lines.append(f"{repo_col}{icon} {name_col}  {prog_col}  {prompt_col}".rstrip())
        else:
            lines.append(f"{icon} {name_col}  {prog_col}  {prompt_col}".rstrip())

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
        elif len(current) + 1 + len(word) <= max_content:
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
        return "No specs found."

    if verbosity >= 3:
        return "Use 'spex show <topic>' for detailed view."

    topics.sort(key=lambda t: t.created_at, reverse=True)

    blocks = []
    for topic in topics:
        if show_repo:
            label = _repo_label(topic.workdir)
            icon = topic.icon
            prog = f"[{topic.done}/{topic.total}]"
            line1 = f"[{label}] {icon} {prog} {topic.name}"
            display_text = topic.display_text
            parts = [line1]
            if display_text:
                parts.append(_wrap_text(display_text))
            if verbosity >= 2:
                todo = topic.todo_data
                if todo:
                    parts.append("")
                    for item in todo:
                        step_id = item.get("id", "")
                        step_name = item.get("name", "")
                        parts.append(f"    {step_id}: {step_name}")
            blocks.append("\n".join(parts))
        else:
            blocks.append(format_topic(topic.path, verbose=verbosity))

    return "\n\n".join(blocks)


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
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv)",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse(argv)

    dirs = [get_specs_dir()]
    archive_dirs = []
    if args.archives:
        archive_dir = get_archives_dir()
        dirs.append(archive_dir)
        archive_dirs.append(archive_dir)

    topics = collect_topics(dirs, archive_dirs=archive_dirs)

    ctx = get_project_context()
    if not args.all_projects:
        topics = [t for t in topics if ctx.is_related_to(t)]
        show_repo = not ctx.in_git_workdir()
    else:
        show_repo = True

    verbosity = args.verbose
    if verbosity > 0:
        print(format_verbose_output(topics, verbosity=verbosity, show_repo=show_repo))
    else:
        print(format_output(topics, show_repo=show_repo))


if __name__ == "__main__":
    main()
