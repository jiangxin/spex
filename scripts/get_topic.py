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
    find_matching_topics,
    get_archives_dir,
    get_specs_dir,
    get_spex_roots,
    get_spex_tomls,
    has_undone_tasks,
    is_topic_completed,
)
from config import ProjectContext, get_project_context, set_spex_config_file


def resolve_topic(topic_name, search_dirs, ctx: ProjectContext | None = None,
                  must_done=False, must_undone=False):
    """Resolve topic name against search directories.

    Args:
        topic_name: Topic name or substring to match. Empty string lists all.
        search_dirs: List of Path objects to search for topics.
        ctx: When set, only return topics related to this project context.
            Ignored when topic_name is provided.
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

    if ctx is not None:
        all_candidates = [
            (name, parent) for name, parent in all_candidates
            if ctx.is_related_to(parent / name)
        ]

    if not all_candidates:
        if must_done:
            if ctx is not None:
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
            if ctx is not None:
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
            if ctx is not None:
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


def _build_parser() -> ArgumentParser:
    """Build the argument parser for ``spex get-topic``."""
    parser = ArgumentParser(
        prog="spex get-topic",
        description="Resolve a topic directory under specs.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--spex-config-file",
        default=None,
        help="Use specified config file (overrides SPEX_CONFIG_FILE env var)",
    )
    parser.add_argument(
        "--spex-roots",
        action="store_true",
        help="Print all spex root directories (one per line)",
    )
    parser.add_argument(
        "--spex-toml",
        action="store_true",
        help="Print the highest-priority .spex.toml path",
    )
    parser.add_argument(
        "--spex-tomls",
        action="store_true",
        help="Print all discovered .spex.toml paths (one per line)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show all topics (ignore workspace filter)",
    )
    parser.add_argument(
        "--with-archives",
        action="store_true",
        help="Also search archives directory",
    )
    exclusive = parser.add_mutually_exclusive_group()
    exclusive.add_argument(
        "--must-done",
        action="store_true",
        help="Only show completed topics",
    )
    exclusive.add_argument(
        "--must-undone",
        action="store_true",
        help="Only show topics with undone tasks",
    )
    parser.add_argument(
        "topic",
        nargs="?",
        default="",
        help="Topic name or substring to match",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse(argv)

    if args.spex_config_file:
        set_spex_config_file(args.spex_config_file)

    if args.spex_roots:
        roots = get_spex_roots()
        if not roots:
            sys.exit(1)
        for p in roots:
            print(p)
        return

    if args.spex_toml:
        tomls = get_spex_tomls()
        if not tomls:
            sys.exit(1)
        print(tomls[0])
        return

    if args.spex_tomls:
        tomls = get_spex_tomls()
        if not tomls:
            sys.exit(1)
        for p in tomls:
            print(p)
        return

    topic_name = args.topic

    if getattr(args, "all") and topic_name:
        print(
            "Error: --all cannot be used with a topic name.",
            file=sys.stderr,
        )
        sys.exit(1)

    ctx = get_project_context()
    workdir = str(ctx.top_workdir) if ctx.in_git_workdir() else None
    specs_dir = get_specs_dir()
    search_dirs = [specs_dir]
    if args.with_archives:
        archives_dir = get_archives_dir(workdir)
        if archives_dir.is_dir():
            search_dirs.append(archives_dir)

    # Determine workspace filter
    if topic_name or getattr(args, "all"):
        filter_ctx = None
    else:
        filter_ctx = ctx

    results = resolve_topic(
        topic_name, search_dirs, ctx=filter_ctx,
        must_done=args.must_done, must_undone=args.must_undone,
    )
    if args.json:
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
