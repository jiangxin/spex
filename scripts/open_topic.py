#!/usr/bin/env python3
"""Open a topic directory in the system file browser.

If no topic is given, opens the spex root directory.
If a topic is given, searches specs and archives for a match.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import check_help_flag, get_archives_dir, get_specs_dir, get_spex_root

USAGE = """\
Usage: spex open [topic]

Open a topic directory in the system file browser.
If no topic is given, opens the spex root directory.

Options:
  -h, --help  Show this help message and exit
"""


def find_topic(name, specs_dir, archives_dir):
    """Search for a topic by name in both specs and archives directories.

    First tries exact match, then falls back to substring match.
    No filtering by undone tasks.

    Args:
        name: Topic name or substring to search for.
        specs_dir: Path to the specs directory.
        archives_dir: Path to the archives directory.

    Returns:
        List of (path_str, source_label) tuples where source_label
        is "specs" or "archives".
    """
    specs_dir = Path(specs_dir)
    archives_dir = Path(archives_dir)
    sources = [
        (specs_dir, "specs"),
        (archives_dir, "archives"),
    ]

    # Try exact match first
    exact = []
    for base, label in sources:
        candidate = base / name
        if candidate.is_dir():
            exact.append((str(candidate), label))
    if exact:
        return exact

    # Fall back to substring match
    matches = []
    for base, label in sources:
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and name in d.name:
                matches.append((str(d), label))
    return matches


def open_directory(path):
    """Open a directory using the platform file browser.

    Args:
        path: Path string of the directory to open.
    """
    if sys.platform == "darwin":
        subprocess.run(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.run(["xdg-open", path])


def main():
    """CLI entry point for the open command."""
    check_help_flag(USAGE)
    topic = sys.argv[1] if len(sys.argv) > 1 else ""

    if not topic:
        open_directory(get_spex_root())
        return

    specs_dir = get_specs_dir()
    archives_dir = get_archives_dir()
    matches = find_topic(topic, specs_dir, archives_dir)

    if not matches:
        print(
            f"Error: no topic matching '{topic}' found.",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(matches) == 1:
        open_directory(matches[0][0])
        return

    print(
        f"Multiple topics match '{topic}'. Please specify more precisely:",
        file=sys.stderr,
    )
    for path, source in matches:
        name = Path(path).name
        print(f"  [{source}] {name}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
