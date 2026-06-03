#!/usr/bin/env python3
"""Open a topic directory in the system file browser.

If no topic is given, lists topics for interactive selection.
If a topic is given, searches specs (and optionally archives) for a match.
When no selection is made or no topics exist, opens the spex root directory.
"""

from __future__ import annotations

import os
import subprocess
import sys

from cli import ArgumentParser
from common import get_spex_root, resolve_topic, select_topic_interactive


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


def _build_parser() -> ArgumentParser:
    """Build the argument parser for ``spex open``."""
    parser = ArgumentParser(
        prog="spex open",
        description="Open a topic directory in the system file browser.",
    )
    parser.add_argument(
        "topic",
        nargs="?",
        default="",
        help="Topic name or substring to open (interactive selection if omitted)",
    )
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
    return parser


def main(argv=None):
    """CLI entry point for the open command."""
    parser = _build_parser()
    args = parser.parse(argv)
    topic = args.topic

    if topic:
        topic_dir = resolve_topic(topic, include_archives=args.archives)
        open_directory(str(topic_dir))
    else:
        selected = select_topic_interactive(
            include_archives=args.archives,
            all_projects=args.all_projects,
            allow_empty=True,
        )
        if selected is None:
            open_directory(get_spex_root())
        else:
            open_directory(str(selected))


if __name__ == "__main__":
    main()
