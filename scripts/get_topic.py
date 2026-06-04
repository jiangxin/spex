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
    has_undone_tasks,
    is_topic_completed,
    logger,
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
                    logger.error(
                        "Error: topic '%s' is not completed.", topic_name
                    )
                    sys.exit(1)
                return [(topic_name, parent_dir)]
            if must_undone:
                if not has_undone_tasks(topic_path):
                    logger.warning(
                        "Warning: topic '%s' has no undone tasks.", topic_name
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
            logger.error(
                "Error: no topic matching '%s' found in %s",
                topic_name, dir_list,
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
        logger.error(
            "Error: specs directory does not exist: %s", dir_list
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
                logger.error(
                    "Error: no completed topics found for the current"
                    " workspace. Use --all to show all topics."
                )
            else:
                logger.error("Error: no completed topics found.")
        elif must_undone:
            if ctx is not None:
                logger.error(
                    "Error: no topics with undone tasks found for the current"
                    " workspace. Use --all to show all topics."
                )
            else:
                logger.error(
                    "Error: no topics with undone tasks found."
                )
        else:
            if ctx is not None:
                logger.error(
                    "Error: no topics found for the current"
                    " workspace. Use --all to show all topics."
                )
            else:
                logger.error("Error: no topics found.")
        sys.exit(1)

    return all_candidates


def _build_parser() -> ArgumentParser:
    """Build the argument parser for ``spex get-topic``."""
    parser = ArgumentParser(
        prog="spex get-topic",
        description="Resolve a topic directory under specs.",
    )
    parser.add_argument(
        "--spex-config-file",
        default=None,
        help="Use specified config file (overrides SPEX_CONFIG_FILE env var)",
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

    topic_name = args.topic

    if getattr(args, "all") and topic_name:
        logger.error("Error: --all cannot be used with a topic name.")
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
    from common import setup_logging
    setup_logging()
    main()
