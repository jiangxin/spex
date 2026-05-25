#!/usr/bin/env python3
"""List spec topics with progress and prompt summary."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_archives_dir,
    get_current_workdir,
    get_specs_dir,
    get_todo_progress,
    load_meta,
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


def collect_topics(dirs: list, archive_dirs: list | None = None) -> list:
    """Collect topic info from given directories."""
    archive_dirs = set(archive_dirs or [])
    topics = []
    for d in dirs:
        if not d.is_dir():
            continue
        archived = d in archive_dirs
        for sub in d.iterdir():
            if not sub.is_dir():
                continue
            meta = load_meta(sub)
            if meta is not None:
                timestamp = meta.get("created_at", "")
                prompts = meta.get("prompts", [])
                prompt = prompts[0] if prompts else ""
                workdir = meta.get("workdir", "")
            else:
                ts_prompt = parse_prompt_log(sub / PROMPT_LOG)
                timestamp, prompt = ts_prompt
                workdir = ""
            n, m = get_todo_progress(sub)
            topics.append({
                "name": sub.name,
                "timestamp": timestamp,
                "n": n,
                "m": m,
                "prompt": prompt,
                "workdir": workdir,
                "archived": archived,
            })
    return topics


def _truncate(text: str, width: int) -> str:
    """Truncate text to width, appending ... if needed."""
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


ICON_ARCHIVED = "\U0001f4e6"
ICON_COMPLETED = "✅"
ICON_IN_PROGRESS = "\U0001f527"

MAX_REPO_WIDTH = 11


def _get_icon(topic: dict) -> str:
    """Return status emoji for a topic."""
    if topic.get("archived"):
        return ICON_ARCHIVED
    if topic["m"] > 0 and topic["n"] == topic["m"]:
        return ICON_COMPLETED
    return ICON_IN_PROGRESS


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

    topics.sort(key=lambda t: t["timestamp"], reverse=True)

    progress_strs = [f"{t['n']}/{t['m']}" for t in topics]
    progress_width = max(len(s) for s in progress_strs)

    repo_labels = []
    if show_repo:
        repo_labels = [_repo_label(t.get("workdir", "")) for t in topics]
        max_label_width = max(len(lb) for lb in repo_labels)
        repo_col_width = max_label_width + 3  # brackets + trailing space
    else:
        repo_col_width = 0

    icon_width = 3
    fixed_width = repo_col_width + icon_width + MAX_TOPIC_WIDTH + 2 + progress_width + 2
    prompt_width = max_width - fixed_width

    lines = []
    for i, (topic, prog_str) in enumerate(zip(topics, progress_strs)):
        icon = _get_icon(topic)
        name = _truncate(topic["name"], MAX_TOPIC_WIDTH)
        name_col = name.ljust(MAX_TOPIC_WIDTH)
        prog_col = prog_str.rjust(progress_width)
        prompt_col = _truncate(topic["prompt"], prompt_width) if prompt_width > 3 else ""

        if show_repo:
            repo_col = f"[{repo_labels[i]}]".ljust(repo_col_width - 1) + " "
            lines.append(f"{repo_col}{icon} {name_col}  {prog_col}  {prompt_col}".rstrip())
        else:
            lines.append(f"{icon} {name_col}  {prog_col}  {prompt_col}".rstrip())

    return "\n".join(lines)


def main():
    all_mode = "--all" in sys.argv

    dirs = [Path(get_specs_dir())]
    archive_dirs = []
    if all_mode:
        archive_dir = Path(get_archives_dir())
        dirs.append(archive_dir)
        archive_dirs.append(archive_dir)

    topics = collect_topics(dirs, archive_dirs=archive_dirs)

    current_workdir = get_current_workdir()
    if current_workdir:
        topics = [
            t for t in topics
            if not t.get("workdir") or t["workdir"] == current_workdir
        ]
        show_repo = False
    else:
        show_repo = True

    print(format_output(topics, show_repo=show_repo))


if __name__ == "__main__":
    main()
