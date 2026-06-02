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
    TopicMeta,
    check_help_flag,
    find_matching_topics,
    get_archives_dir,
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
Usage: spex get-topic [--json] [--all] [--with-archives] [--must-done | --must-undone] [topic]
       spex get-topic --spex-roots | --spex-toml | --spex-tomls

Resolve a topic directory under specs.

Options:
  --json         Output in JSON format
  --all          Show all topics (ignore workspace filter)
  --with-archives
                 Also search archives directory
  --spex-config-file <path>
                 Use specified config file (overrides SPEX_CONFIG_FILE env var)
  --must-done    Only show completed topics
  --must-undone  Only show topics with undone tasks
  --spex-roots   Print all spex root directories (one per line)
  --spex-toml    Print the highest-priority .spex.toml path
  --spex-tomls   Print all discovered .spex.toml paths (one per line)
  -h, --help     Show this help message and exit"""


def resolve_topic(topic_name, search_dirs, filter_workdir=None,
                  must_done=False, must_undone=False):
    """Resolve topic name against search directories.

    Args:
        topic_name: Topic name or substring to match. Empty string lists all.
        search_dirs: List of Path objects to search for topics.
        filter_workdir: When set, only return topics whose meta.json workdir
            matches this path. Ignored when topic_name is provided.
        must_done: When True, only return completed topics.
        must_undone: When True, only return topics with undone tasks.

    Returns a list of (topic_name, parent_dir) tuples.
    Raises SystemExit on error.
    """
    # Accept a single Path/str for backward compatibility
    if isinstance(search_dirs, (str, Path)):
        search_dirs = [Path(search_dirs)]

    if must_done:
        topic_filter = is_topic_completed
    elif must_undone:
        topic_filter = has_undone_tasks
    else:
        topic_filter = None  # no filtering

    if topic_name:
        all_matches = []
        for search_dir in search_dirs:
            search_dir = Path(search_dir)
            for m in find_matching_topics(topic_name, search_dir):
                all_matches.append((m, search_dir))

        # Exact match — apply status check directly
        if len(all_matches) == 1 and all_matches[0][0].name == topic_name:
            topic_path, parent_dir = all_matches[0]
            if must_done:
                if not is_topic_completed(topic_path):
                    print(
                        f"Error: topic '{topic_name}' is not completed.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                return [(topic_name, parent_dir)]
            if must_undone:
                if not has_undone_tasks(topic_path):
                    print(
                        f"Warning: topic '{topic_name}' has no undone tasks.",
                        file=sys.stderr,
                    )
                    return []
            return [(topic_name, parent_dir)]

        # Substring matches — filter by status
        if topic_filter is not None:
            filtered = sorted(
                (d.name, parent) for d, parent in all_matches
                if topic_filter(d)
            )
        else:
            filtered = sorted(
                (d.name, parent) for d, parent in all_matches
            )

        if not filtered:
            dir_list = ", ".join(str(d) for d in search_dirs)
            print(
                f"Error: no topic matching '{topic_name}' found in"
                f" {dir_list}",
                file=sys.stderr,
            )
            sys.exit(1)

        return filtered

    all_candidates = []
    for search_dir in search_dirs:
        search_dir = Path(search_dir)
        if not search_dir.is_dir():
            continue
        if topic_filter is not None:
            entries = sorted(
                (d.name, search_dir)
                for d in search_dir.iterdir()
                if d.is_dir() and topic_filter(d)
            )
        else:
            entries = sorted(
                (d.name, search_dir)
                for d in search_dir.iterdir()
                if d.is_dir()
            )
        all_candidates.extend(entries)

    if not all_candidates and not any(
        Path(d).is_dir() for d in search_dirs
    ):
        dir_list = ", ".join(str(d) for d in search_dirs)
        print(
            f"Error: specs directory does not exist: {dir_list}",
            file=sys.stderr,
        )
        sys.exit(1)

    if filter_workdir:
        all_candidates = [
            (name, parent) for name, parent in all_candidates
            if _topic_matches_workdir(parent / name, filter_workdir)
        ]

    if not all_candidates:
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
        elif must_undone:
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
        else:
            if filter_workdir:
                print(
                    "Error: no topics found for the current"
                    " workspace. Use --all to show all topics.",
                    file=sys.stderr,
                )
            else:
                print(
                    "Error: no topics found.",
                    file=sys.stderr,
                )
        sys.exit(1)

    return all_candidates


def _topic_matches_workdir(topic_dir, workdir):
    """Return True if the topic's workdir or main_worktree matches the given workdir."""
    meta = load_meta(topic_dir) or TopicMeta()
    topic_wd = meta.workdir
    main_wt = meta.main_worktree
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

    with_archives_flag = "--with-archives" in args
    if with_archives_flag:
        args = [a for a in args if a != "--with-archives"]

    topic_name = args[0] if args else ""

    if all_flag and topic_name:
        print(
            "Error: --all cannot be used with a topic name.",
            file=sys.stderr,
        )
        sys.exit(1)

    workdir = get_current_workdir()
    specs_dir = get_specs_dir()
    search_dirs = [specs_dir]
    if with_archives_flag:
        archives_dir = get_archives_dir(workdir)
        if archives_dir.is_dir():
            search_dirs.append(archives_dir)

    # Determine workspace filter
    if topic_name or all_flag:
        filter_workdir = None
    else:
        filter_workdir = workdir

    results = resolve_topic(
        topic_name, search_dirs, filter_workdir=filter_workdir,
        must_done=must_done_flag, must_undone=must_undone_flag,
    )
    if json_mode:
        items = [
            {"topic_name": name, "topic_path": str(parent_dir / name)}
            for name, parent_dir in results
        ]
        print(json.dumps(items, indent=2))
    else:
        for name, _parent_dir in results:
            print(name)


if __name__ == "__main__":
    main()
