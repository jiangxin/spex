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
from common import get_spex_root, resolve_spec, select_spec_interactive


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


def run_in_directory(path, command):
    """Run a command in the given directory.

    Args:
        path: Path string of the working directory.
        command: Shell command string to execute.
    """
    result = subprocess.run(command, shell=True, cwd=path)
    sys.exit(result.returncode)


def _perform_action(path, run_command):
    """Dispatch to open_directory or run_in_directory based on --run value.

    Args:
        path: Path string of the target directory.
        run_command: Value of --run argument. None or empty string opens the
            directory; a non-empty string runs that command in the directory.
    """
    if run_command is None or run_command == "":
        open_directory(path)
    else:
        run_in_directory(path, run_command)


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
    parser.add_argument(
        "--run",
        nargs="?",
        const="",
        default=None,
        metavar="COMMAND",
        help="Run a command in the topic directory instead of opening it",
    )
    return parser


def main(argv=None):
    """CLI entry point for the open command."""
    parser = _build_parser()
    args = parser.parse(argv)
    spec_name = args.topic

    if spec_name:
        spec_dir = resolve_spec(spec_name, include_archives=args.archives)
        _perform_action(str(spec_dir), args.run)
    else:
        selected = select_spec_interactive(
            include_archives=args.archives,
            all_projects=args.all_projects,
            allow_empty=True,
        )
        if selected is None:
            _perform_action(get_spex_root(), args.run)
        else:
            _perform_action(str(selected), args.run)


if __name__ == "__main__":
    main()
