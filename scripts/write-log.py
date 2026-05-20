#!/usr/bin/env python3
"""Log a message to the topic's prompt.log file.

Reads text from stdin and appends it with a timestamp to
<spec_root>/<topic>/prompt.log.
"""

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PROMPT_LOG, get_specs_dir, local_iso_timestamp

INDENT = "    "
WRAP_WIDTH = 70


def _char_width(ch):
    """Return display width of a character (2 for wide/fullwidth, 1 otherwise)."""
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ("W", "F") else 1


def _wrap_line(line, width):
    """Wrap a single line by display width, returning a list of lines."""
    if not line:
        return [""]
    result = []
    current = []
    current_width = 0
    for ch in line:
        cw = _char_width(ch)
        if current_width + cw > width and current:
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


def write_log(topic, content, specs_dir, timestamp=None):
    """Append a prompt entry to the topic's prompt.log.

    Returns the log file path.
    Raises FileNotFoundError if topic dir doesn't exist.
    Raises ValueError if content is empty.
    """
    specs_dir = Path(specs_dir)
    topic_dir = specs_dir / topic

    if not topic_dir.is_dir():
        raise FileNotFoundError(f"topic directory does not exist: {topic_dir}")

    content = content.strip()
    if not content:
        raise ValueError("no input provided")

    log_file = topic_dir / PROMPT_LOG
    if timestamp is None:
        timestamp = local_iso_timestamp()
    wrapped = format_prompt(content)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"**[{timestamp}]**\n\n")
        f.write(f"```prompt\n{wrapped}\n```\n\n")

    return log_file


def main():
    if len(sys.argv) != 2:
        print(
            f"Usage: {sys.argv[0]} <topic>",
            file=sys.stderr,
        )
        sys.exit(1)

    specs_dir = Path(get_specs_dir())
    topic = sys.argv[1]

    content = sys.stdin.read()

    try:
        log_file = write_log(topic, content, specs_dir)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(log_file)


if __name__ == "__main__":
    main()
