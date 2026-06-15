#!/usr/bin/env python3
"""Archive completed spec topics.

Moves topic directories whose todo.json items are all completed
into the archives directory.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from cli import ArgumentParser
from common import (
    find_completed_specs,
    find_matching_specs,
    get_archives_dir,
    get_specs_dir,
    has_active_branch,
    is_spec_completed,
    load_meta,
    logger,
    resolve_topic_dir,
)
from config import get_project_context


def move_topic_with_conflict(source_dir: Path, dest_dir: Path) -> Path:
    """Move source_dir into dest_dir, appending suffix on conflict.

    Returns the final destination path.
    """
    dest = dest_dir / source_dir.name
    if not dest.exists():
        shutil.move(str(source_dir), str(dest))
        return dest

    counter = 2
    while True:
        candidate = dest_dir / f"{source_dir.name}-{counter}"
        if not candidate.exists():
            shutil.move(str(source_dir), str(candidate))
            return candidate
        counter += 1


def move_topic(topic_dir: Path, archives_dir: Path) -> Path:
    """Move topic_dir into archives_dir, appending suffix on conflict.

    Thin wrapper around move_topic_with_conflict for backward compatibility.
    Returns the final destination path.
    """
    return move_topic_with_conflict(topic_dir, archives_dir)


def archive_single_topic(
    topic_name: str,
    specs_dir: Path,
    archives_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> Path | None:
    """Archive a single topic by name. Supports partial topic name matching.

    Returns the destination path, or None if skipped due to active branch.
    """
    topic_dir = resolve_topic_dir(topic_name, specs_dir)
    if not force and not is_spec_completed(topic_dir):
        logger.info(
            "Skipping: topic is not completed (use --force to archive)"
        )
        return None
    if not force and has_active_branch(topic_dir):
        meta = load_meta(topic_dir)
        spex_branch = meta.spex_branch if meta else ""
        logger.info(
            "Skipping: spex branch '%s' still exists"
            " (use --force to archive)", spex_branch
        )
        return None
    if dry_run:
        logger.info("Would archive: %s", topic_dir.name)
        return archives_dir / topic_dir.name
    archives_dir.mkdir(parents=True, exist_ok=True)
    dest = move_topic(topic_dir, archives_dir)
    logger.info("Archived: %s -> %s", topic_dir.name, dest)
    return dest


def restore_single_topic(
    topic_name: str,
    specs_dir: Path,
    archives_dir: Path,
    dry_run: bool = False,
) -> Path | None:
    """Restore a single topic from archives back to specs.

    Uses fuzzy substring matching against archives_dir. Exits with error
    if no match or multiple matches.

    Returns the destination path in specs_dir, or None on error.
    """
    if not archives_dir.is_dir():
        logger.error(
            "Error: archives directory does not exist: %s", archives_dir
        )
        sys.exit(1)

    matches = find_matching_specs(topic_name, archives_dir)
    if not matches:
        logger.error(
            "Error: no topic matching '%s' found in archives.", topic_name
        )
        sys.exit(1)
    if len(matches) > 1:
        names = "\n  ".join(m.name for m in matches)
        logger.error(
            "Error: multiple topics match '%s' in archives:\n  %s",
            topic_name, names
        )
        sys.exit(1)

    if dry_run:
        logger.info("Would restore: %s", matches[0].name)
        return specs_dir / matches[0].name
    specs_dir.mkdir(parents=True, exist_ok=True)
    dest = move_topic_with_conflict(matches[0], specs_dir)
    logger.info("Restored: %s -> %s", matches[0].name, dest)
    return dest


def main(argv=None):
    parser = ArgumentParser(
        prog="spex archive",
        description="Archive completed spec topics.",
    )
    parser.add_argument("--topic", help="Archive a single topic by name")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Preview without moving")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Bypass spex_branch existence check")
    parser.add_argument("--restore", action="store_true",
                        help="Restore a topic from archives back to specs")
    parser.add_argument("--not", action="store_true", dest="restore",
                        help=argparse.SUPPRESS)
    parser.add_argument("--all-projects", action="store_true",
                        help="Archive topics from all projects")
    args = parser.parse(argv)

    specs_dir = get_specs_dir()
    archives_dir = get_archives_dir()

    if args.restore:
        if not args.topic:
            logger.error(
                "Error: --restore requires --topic to specify what to restore."
            )
            sys.exit(1)
        restore_single_topic(args.topic, specs_dir, archives_dir,
                             dry_run=args.dry_run)
        return

    if args.topic:
        archive_single_topic(args.topic, specs_dir, archives_dir, args.force,
                             dry_run=args.dry_run)
        return

    ctx = get_project_context()

    if not ctx.in_git_workdir() and not args.all_projects:
        logger.info(
            "Not in a git workdir. Use --all-projects to archive"
            " topics from all projects."
        )
        return

    completed = find_completed_specs(
        specs_dir, ctx, args.force, all_projects=args.all_projects,
    )

    if not completed:
        logger.info("No completed topics to archive.")
        return

    if args.dry_run:
        # Show topics that would be skipped due to active branches
        skipped = [
            d for d in sorted(specs_dir.iterdir())
            if d.is_dir() and is_spec_completed(d) and has_active_branch(d)
        ]
        logger.info("Would archive %d topic(s):", len(completed))
        for topic_dir in completed:
            logger.info("  %s", topic_dir.name)
        if skipped:
            logger.info(
                "Would skip %d topic(s) (active spex_branch):", len(skipped)
            )
            for topic_dir in skipped:
                meta = load_meta(topic_dir)
                branch = meta.spex_branch if meta else ""
                logger.info("  %s (%s)", topic_dir.name, branch)
        return

    archives_dir.mkdir(parents=True, exist_ok=True)
    for topic_dir in completed:
        dest = move_topic(topic_dir, archives_dir)
        logger.info("Archived: %s -> %s", topic_dir.name, dest)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
