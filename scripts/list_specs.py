#!/usr/bin/env python3
"""List spec topics with progress and prompt summary."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TODO_FILE, get_archives_dir, get_specs_dir

META_FILE = "meta.json"
PROMPT_LOG = "prompt.log"
MAX_TOPIC_WIDTH = 38
MAX_LINE_WIDTH = 80


def _read_meta(topic_dir: Path):
    """Read meta.json, return (created_at, first_prompt) or None."""
    meta_path = topic_dir / META_FILE
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    timestamp = data.get("created_at", "")
    prompts = data.get("prompts", [])
    prompt_text = prompts[0] if prompts else ""
    return (timestamp, prompt_text)


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


def get_todo_progress(topic_dir: Path) -> tuple:
    """Return (completed_count, total_count) from todo.json."""
    todo_path = topic_dir / TODO_FILE
    if not todo_path.is_file():
        return (0, 0)
    try:
        data = json.loads(todo_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return (0, 0)
    if not isinstance(data, list) or len(data) == 0:
        return (0, 0)
    total = len(data)
    done = sum(
        1 for item in data
        if isinstance(item, dict) and item.get("completed_at")
    )
    return (done, total)


def collect_topics(dirs: list) -> list:
    """Collect topic info from given directories."""
    topics = []
    for d in dirs:
        if not d.is_dir():
            continue
        for sub in d.iterdir():
            if not sub.is_dir():
                continue
            result = _read_meta(sub)
            if result is None:
                result = parse_prompt_log(sub / PROMPT_LOG)
            timestamp, prompt = result
            n, m = get_todo_progress(sub)
            topics.append({
                "name": sub.name,
                "timestamp": timestamp,
                "n": n,
                "m": m,
                "prompt": prompt,
            })
    return topics


def _truncate(text: str, width: int) -> str:
    """Truncate text to width, appending ... if needed."""
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


def format_output(topics: list, max_width: int = MAX_LINE_WIDTH) -> str:
    """Format topics into aligned columns."""
    if not topics:
        return "No specs found."

    topics.sort(key=lambda t: t["timestamp"], reverse=True)

    progress_strs = [f"{t['n']}/{t['m']}" for t in topics]
    progress_width = max(len(s) for s in progress_strs)

    # Layout: <topic>  <progress>  <prompt>
    # Gaps: 2 spaces between columns
    fixed_width = MAX_TOPIC_WIDTH + 2 + progress_width + 2
    prompt_width = max_width - fixed_width

    lines = []
    for topic, prog_str in zip(topics, progress_strs):
        name = _truncate(topic["name"], MAX_TOPIC_WIDTH)
        name_col = name.ljust(MAX_TOPIC_WIDTH)
        prog_col = prog_str.rjust(progress_width)
        prompt_col = _truncate(topic["prompt"], prompt_width) if prompt_width > 3 else ""
        lines.append(f"{name_col}  {prog_col}  {prompt_col}".rstrip())

    return "\n".join(lines)


def main():
    all_mode = "--all" in sys.argv

    dirs = [Path(get_specs_dir())]
    if all_mode:
        dirs.append(Path(get_archives_dir()))

    topics = collect_topics(dirs)
    print(format_output(topics))


if __name__ == "__main__":
    main()
