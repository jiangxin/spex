#!/usr/bin/env python3
"""Archive completed spec topics.

Moves topic directories whose todo.json items are all completed
into the archives directory.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from branch import branch_exists
from cli import ArgumentParser
from common import (
    check_help_flag,
    get_archives_dir,
    get_current_workdir,
    get_specs_dir,
    get_topic_workdir,
    is_topic_completed,
    load_meta,
    resolve_topic_dir,
    same_path,
)


def has_active_branch(topic_dir: Path) -> bool:
    """Return True if meta.json has spex_branch and that git branch exists."""
    meta = load_meta(topic_dir)
    if not meta:
        return False
    spex_branch = meta.get("spex_branch", "")
    if not spex_branch:
        return False
    return branch_exists(spex_branch)


USAGE = """\
Usage: spex archive [--topic <topic>] [--dry-run | -n] [--force | -f]

Archive completed spec topics.

Options:
  --topic <topic>  Archive a single topic by name
  --dry-run, -n    Preview without moving
  --force, -f      Bypass spex_branch existence check
  -h, --help       Show this help message and exit
"""


def find_completed_topics(
    specs_dir: Path, current_workdir=None, force: bool = False
) -> list:
    """Return sorted list of topic paths where all tasks are completed.

    If current_workdir is provided, only topics matching that workdir
    (or topics without a workdir) are included.

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
        if current_workdir is not None:
            workdir = get_topic_workdir(d)
            if workdir and not same_path(workdir, current_workdir):
                continue
        results.append(d)
    return sorted(results)


def move_topic(topic_dir: Path, archives_dir: Path) -> Path:
    """Move topic_dir into archives_dir, appending suffix on conflict.

    Returns the final destination path.
    """
    dest = archives_dir / topic_dir.name
    if not dest.exists():
        shutil.move(str(topic_dir), str(dest))
        return dest

    counter = 2
    while True:
        candidate = archives_dir / f"{topic_dir.name}-{counter}"
        if not candidate.exists():
            shutil.move(str(topic_dir), str(candidate))
            return candidate
        counter += 1


def archive_single_topic(
    topic_name: str, specs_dir: Path, archives_dir: Path, force: bool = False
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
        spex_branch = meta.get("spex_branch", "") if meta else ""
        print(
            f"Skipping: spex branch '{spex_branch}' still exists"
            f" (use --force to archive)"
        )
        return None
    archives_dir.mkdir(parents=True, exist_ok=True)
    dest = move_topic(topic_dir, archives_dir)
    print(f"Archived: {topic_dir.name} -> {dest}")
    return dest


def main(argv=None):
    check_help_flag(USAGE, argv)

    parser = ArgumentParser(prog="spex archive", usage=USAGE)
    parser.add_argument("--topic", help="Archive a single topic by name")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Preview without moving")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Bypass spex_branch existence check")
    args = parser.parse(argv)

    specs_dir = get_specs_dir()
    archives_dir = get_archives_dir()

    if args.topic:
        archive_single_topic(args.topic, specs_dir, archives_dir, args.force)
        return

    current_workdir = get_current_workdir()
    completed = find_completed_topics(specs_dir, current_workdir, args.force)

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
                branch = meta.get("spex_branch", "") if meta else ""
                print(f"  {topic_dir.name} ({branch})")
        return

    archives_dir.mkdir(parents=True, exist_ok=True)
    for topic_dir in completed:
        dest = move_topic(topic_dir, archives_dir)
        print(f"Archived: {topic_dir.name} -> {dest}")


if __name__ == "__main__":
    main()
