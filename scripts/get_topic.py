#!/usr/bin/env python3
"""Resolve a topic directory under specs.

If a topic name is given, verify it exists.
If no topic name is given, list topics with undone tasks as candidates.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    check_help_flag,
    get_current_workdir,
    get_specs_dir,
    get_topic_workdir,
    has_undone_tasks,
    is_topic_completed,
    same_path,
)

USAGE = """\
Usage: spex get-topic [--json] [--all] [--must-done | --must-undone] [topic]

Resolve a topic directory under specs.

Options:
  --json         Output in JSON format
  --all          Show all topics (ignore workspace filter)
  --must-done    Only show completed topics
  --must-undone  Only show topics with undone tasks (default)
  -h, --help     Show this help message and exit"""


def resolve_topic(topic_name, specs_dir, filter_workdir=None, must_done=False):
    """Resolve topic name against specs_dir.

    Args:
        topic_name: Topic name or substring to match. Empty string lists all.
        specs_dir: Path to the specs directory.
        filter_workdir: When set, only return topics whose meta.json workdir
            matches this path. Ignored when topic_name is provided.
        must_done: When True, only return completed topics.

    Returns a list of matching topic names.
    Raises SystemExit on error.
    """
    specs_dir = Path(specs_dir)

    if topic_name:
        if (specs_dir / topic_name).is_dir():
            topic_path = specs_dir / topic_name
            if must_done:
                if not is_topic_completed(topic_path):
                    print(
                        f"Error: topic '{topic_name}' is not completed.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                return [topic_name]
            if not has_undone_tasks(topic_path):
                print(
                    f"Warning: topic '{topic_name}' has no undone tasks.",
                    file=sys.stderr,
                )
                return []
            return [topic_name]

        if must_done:
            topic_filter = is_topic_completed
        else:
            topic_filter = has_undone_tasks

        matches = sorted(
            d.name
            for d in specs_dir.iterdir()
            if d.is_dir()
            and topic_name in d.name
            and topic_filter(d)
        )

        if not matches:
            print(
                f"Error: no topic matching '{topic_name}' found in"
                f" {specs_dir}",
                file=sys.stderr,
            )
            sys.exit(1)

        return matches

    if not specs_dir.is_dir():
        print(
            f"Error: specs directory does not exist: {specs_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    if must_done:
        topic_filter = is_topic_completed
    else:
        topic_filter = has_undone_tasks

    candidates = sorted(
        d.name
        for d in specs_dir.iterdir()
        if d.is_dir() and topic_filter(d)
    )

    if filter_workdir:
        candidates = [
            name for name in candidates
            if _topic_matches_workdir(specs_dir / name, filter_workdir)
        ]

    if not candidates:
        if must_done:
            if filter_workdir:
                print(
                    "Error: no completed topics found for the current"
                    " workspace. Use --all to show all topics.",
                    file=sys.stderr,
                )
            else:
                print(
                    "Error: no completed topics found.",
                    file=sys.stderr,
                )
        else:
            if filter_workdir:
                print(
                    "Error: no topics with undone tasks found for the current"
                    " workspace. Use --all to show all topics.",
                    file=sys.stderr,
                )
            else:
                print(
                    "Error: no topics with undone tasks found.",
                    file=sys.stderr,
                )
        sys.exit(1)

    return candidates


def _topic_matches_workdir(topic_dir, workdir):
    """Return True if the topic's workdir matches the given workdir."""
    topic_wd = get_topic_workdir(topic_dir)
    if not topic_wd:
        return False
    return same_path(topic_wd, workdir)


def main(argv=None):
    check_help_flag(USAGE, argv)
    args = argv if argv is not None else sys.argv[1:]
    json_mode = "--json" in args
    if json_mode:
        args = [a for a in args if a != "--json"]

    all_flag = "--all" in args
    if all_flag:
        args = [a for a in args if a != "--all"]

    must_done_flag = "--must-done" in args
    must_undone_flag = "--must-undone" in args
    if must_done_flag and must_undone_flag:
        print(
            "Error: --must-done and --must-undone are mutually exclusive.",
            file=sys.stderr,
        )
        sys.exit(1)
    args = [a for a in args if a not in ("--must-done", "--must-undone")]

    topic_name = args[0] if args else ""

    if all_flag and topic_name:
        print(
            "Error: --all cannot be used with a topic name.",
            file=sys.stderr,
        )
        sys.exit(1)

    specs_dir = Path(get_specs_dir())

    # Determine workspace filter
    if topic_name or all_flag:
        filter_workdir = None
    else:
        filter_workdir = get_current_workdir()

    results = resolve_topic(
        topic_name, specs_dir, filter_workdir=filter_workdir,
        must_done=must_done_flag,
    )
    if json_mode:
        items = [
            {"topic_name": name, "topic_path": str(specs_dir / name)}
            for name in results
        ]
        print(json.dumps(items, indent=2))
    else:
        for name in results:
            print(name)


if __name__ == "__main__":
    main()
