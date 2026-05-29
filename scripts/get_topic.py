#!/usr/bin/env python3
"""Resolve a topic directory under specs.

If a topic name is given, verify it exists.
If no topic name is given, list topics with undone tasks as candidates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from cli import ArgumentParser
from common import (
    check_help_flag,
    find_matching_topics,
    get_current_workdir,
    get_specs_dir,
    get_spex_roots,
    get_spex_tomls,
    has_undone_tasks,
    is_topic_completed,
    load_meta,
    same_path,
)
from config import set_spex_config_file

USAGE = """\
Usage: spex get-topic [--json] [--all] [--must-done | --must-undone] [topic]
       spex get-topic --spex-roots | --spex-toml | --spex-tomls

Resolve a topic directory under specs.

Options:
  --json         Output in JSON format
  --all          Show all topics (ignore workspace filter)
  --spex-config-file <path>
                 Use specified config file (overrides SPEX_CONFIG_FILE env var)
  --must-done    Only show completed topics
  --must-undone  Only show topics with undone tasks (default)
  --spex-roots   Print all spex root directories (one per line)
  --spex-toml    Print the highest-priority .spex.toml path
  --spex-tomls   Print all discovered .spex.toml paths (one per line)
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

    if must_done:
        topic_filter = is_topic_completed
    else:
        topic_filter = has_undone_tasks

    if topic_name:
        matches = find_matching_topics(topic_name, specs_dir)

        # Exact match — apply status check directly
        if len(matches) == 1 and matches[0].name == topic_name:
            topic_path = matches[0]
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

        # Substring matches — filter by status
        filtered = sorted(
            d.name for d in matches if topic_filter(d)
        )

        if not filtered:
            print(
                f"Error: no topic matching '{topic_name}' found in"
                f" {specs_dir}",
                file=sys.stderr,
            )
            sys.exit(1)

        return filtered

    if not specs_dir.is_dir():
        print(
            f"Error: specs directory does not exist: {specs_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

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
    """Return True if the topic's workdir or main_worktree matches the given workdir."""
    meta = load_meta(topic_dir) or {}
    topic_wd = meta.get("workdir", "")
    main_wt = meta.get("main_worktree", "")
    if topic_wd and same_path(topic_wd, workdir):
        return True
    if main_wt and same_path(main_wt, workdir):
        return True
    return False


def main(argv=None):
    check_help_flag(USAGE, argv)
    args = argv if argv is not None else sys.argv[1:]

    # --- Introspection flags (handled early, before topic resolution) ---
    parser = ArgumentParser(
        prog="spex get-topic", usage=USAGE, add_help=False,
    )
    parser.add_argument("--spex-config-file", default=None)
    parser.add_argument("--spex-roots", action="store_true")
    parser.add_argument("--spex-toml", action="store_true")
    parser.add_argument("--spex-tomls", action="store_true")
    parsed, remaining = parser.parse_known(args)

    if parsed.spex_config_file:
        set_spex_config_file(parsed.spex_config_file)

    if parsed.spex_roots:
        roots = get_spex_roots()
        if not roots:
            sys.exit(1)
        for p in roots:
            print(p)
        return

    if parsed.spex_toml:
        tomls = get_spex_tomls()
        if not tomls:
            sys.exit(1)
        print(tomls[0])
        return

    if parsed.spex_tomls:
        tomls = get_spex_tomls()
        if not tomls:
            sys.exit(1)
        for p in tomls:
            print(p)
        return

    # --- Normal topic resolution ---
    args = remaining
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

    specs_dir = get_specs_dir()

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
