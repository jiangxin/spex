#!/usr/bin/env python3
"""Log a message to the topic's prompt.log file.

Reads text from stdin and appends it with a timestamp to
<spec_root>/<topic>/prompt.log.
"""

import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_shared"))
from common import PROMPT_LOG, get_specs_dir

INDENT = "    "
WRAP_WIDTH = 70


def _char_width(ch):
    """Return display width of a character (2 for wide/fullwidth, 1 otherwise)."""
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ("W", "F") else 1


def _wrap_line(line, width):
    """Wrap a single line by display width, returning a list of lines.

    Avoids splitting ASCII words mid-character by backtracking to the
    last space when the break falls inside a Latin word.
    """
    if not line:
        return [""]
    result = []
    current = []
    current_width = 0
    for ch in line:
        cw = _char_width(ch)
        if current_width + cw > width and current:
            # backtrack to last space to avoid splitting ASCII words
            space_idx = None
            for i in range(len(current) - 1, -1, -1):
                if current[i] == " ":
                    space_idx = i
                    break
            if space_idx is not None and space_idx > 0:
                result.append("".join(current[: space_idx + 1]).rstrip())
                remaining = current[space_idx + 1 :]
                current = remaining
                current_width = sum(_char_width(c) for c in current)
            else:
                result.append("".join(current))
                current = []
                current_width = 0
        current.append(ch)
        current_width += cw
    if current:
        result.append("".join(current))
    return result


def format_prompt(content, width=WRAP_WIDTH, indent=INDENT):
    """Format prompt text with wrapping and indentation."""
    lines = []
    for raw_line in content.splitlines():
        for wrapped in _wrap_line(raw_line, width):
            lines.append(f"{indent}{wrapped}")
    return "\n".join(lines)


def main():
    if len(sys.argv) != 2:
        print(
            f"Usage: {sys.argv[0]} <topic>",
            file=sys.stderr,
        )
        sys.exit(1)

    specs_dir = Path(get_specs_dir())
    topic = sys.argv[1]
    topic_dir = specs_dir / topic

    if not topic_dir.is_dir():
        print(
            f"Error: topic directory does not exist: {topic_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    content = sys.stdin.read().strip()
    if not content:
        print("Error: no input provided on stdin.", file=sys.stderr)
        sys.exit(1)

    log_file = topic_dir / PROMPT_LOG
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    wrapped = format_prompt(content)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"**[{timestamp}]**\n\n")
        f.write(f"```prompt\n{wrapped}\n```\n\n")

    print(log_file)


if __name__ == "__main__":
    main()
