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

from branch import branch_exists
from cli import ArgumentParser
from common import (
    find_matching_topics,
    get_archives_dir,
    get_specs_dir,
    is_topic_completed,
    load_meta,
    resolve_topic_dir,
)
from config import ProjectContext, get_project_context


def has_active_branch(topic_dir: Path) -> bool:
    """Return True if meta.json has spex_branch and that git branch exists."""
    meta = load_meta(topic_dir)
    if not meta:
        return False
    spex_branch = meta.spex_branch
    if not spex_branch:
        return False
    return branch_exists(spex_branch)



def find_completed_topics(
    specs_dir: Path, ctx: ProjectContext, force: bool = False
) -> list:
    """Return sorted list of topic paths where all tasks are completed.

    Topics are filtered by ctx.is_related_to() to only include topics
    matching the current workspace (or all topics when not in a git repo).

    If force is False, topics with an active spex_branch are excluded.
    """
    if not specs_dir.is_dir():
        return []
    results = []
    for d in specs_dir.iterdir():
        if not d.is_dir() or not is_topic_completed(d):
            continue
        if not force and has_active_branch(d):
            continue
        if not ctx.is_related_to(d):
            continue
        results.append(d)
    return sorted(results)


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
    if not force and not is_topic_completed(topic_dir):
        print(
            "Skipping: topic is not completed (use --force to archive)"
        )
        return None
    if not force and has_active_branch(topic_dir):
        meta = load_meta(topic_dir)
        spex_branch = meta.spex_branch if meta else ""
        print(
            f"Skipping: spex branch '{spex_branch}' still exists"
            f" (use --force to archive)"
        )
        return None
    if dry_run:
        print(f"Would archive: {topic_dir.name}")
        return archives_dir / topic_dir.name
    archives_dir.mkdir(parents=True, exist_ok=True)
    dest = move_topic(topic_dir, archives_dir)
    print(f"Archived: {topic_dir.name} -> {dest}")
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
        print(
            f"Error: archives directory does not exist: {archives_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    matches = find_matching_topics(topic_name, archives_dir)
    if not matches:
        print(
            f"Error: no topic matching '{topic_name}' found in archives.",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(matches) > 1:
        names = "\n  ".join(m.name for m in matches)
        print(
            f"Error: multiple topics match '{topic_name}' in archives:"
            f"\n  {names}",
            file=sys.stderr,
        )
        sys.exit(1)

    if dry_run:
        print(f"Would restore: {matches[0].name}")
        return specs_dir / matches[0].name
    specs_dir.mkdir(parents=True, exist_ok=True)
    dest = move_topic_with_conflict(matches[0], specs_dir)
    print(f"Restored: {matches[0].name} -> {dest}")
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
    args = parser.parse(argv)

    specs_dir = get_specs_dir()
    archives_dir = get_archives_dir()

    if args.restore:
        if not args.topic:
            print(
                "Error: --restore requires --topic to specify what to restore.",
                file=sys.stderr,
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
    completed = find_completed_topics(specs_dir, ctx, args.force)

    if not completed:
        print("No completed topics to archive.")
        return

    if args.dry_run:
        # Show topics that would be skipped due to active branches
        skipped = [
            d for d in sorted(specs_dir.iterdir())
            if d.is_dir() and is_topic_completed(d) and has_active_branch(d)
        ]
        print(f"Would archive {len(completed)} topic(s):")
        for topic_dir in completed:
            print(f"  {topic_dir.name}")
        if skipped:
            print(f"Would skip {len(skipped)} topic(s) (active spex_branch):")
            for topic_dir in skipped:
                meta = load_meta(topic_dir)
                branch = meta.spex_branch if meta else ""
                print(f"  {topic_dir.name} ({branch})")
        return

    archives_dir.mkdir(parents=True, exist_ok=True)
    for topic_dir in completed:
        dest = move_topic(topic_dir, archives_dir)
        print(f"Archived: {topic_dir.name} -> {dest}")


if __name__ == "__main__":
    main()
