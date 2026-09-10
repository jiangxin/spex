#!/usr/bin/env python3
"""Archive completed specs.

Moves spec directories whose todo.json items are all completed
into the archives directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
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
    resolve_spec_dir,
)
from config import get_project_context
from debug_log import DEBUG_LOG_NAME

_DEBUG_ORPHAN_ALLOWED = frozenset({
    DEBUG_LOG_NAME,
    f"{DEBUG_LOG_NAME}.prev_end",
})


@dataclass(frozen=True)
class ArchiveItem:
    """One archive/restore outcome for JSON and human logging."""

    action: str
    spec_name: str
    spec_path: Path | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        item = {
            "action": self.action,
            "spec_name": self.spec_name,
            "spec_path": str(self.spec_path) if self.spec_path else "",
        }
        if self.detail:
            item["detail"] = self.detail
        return item


def _emit_json(dry_run: bool, results: list[ArchiveItem]) -> None:
    """Print machine-readable archive results to stdout."""
    print(json.dumps({
        "dry_run": dry_run,
        "results": [r.to_dict() for r in results],
    }))


def is_debug_orphan_stub(spec_dir: Path) -> bool:
    """Return True if ``spec_dir`` only contains debug tee artifacts.

    A debug orphan stub is a directory whose entries are a subset of
    ``{debug.log, debug.log.prev_end}`` and that contains ``debug.log``.
    Directories with any other file (e.g. ``.DS_Store``) are not stubs.
    """
    if not spec_dir.is_dir():
        return False
    if not (spec_dir / DEBUG_LOG_NAME).is_file():
        return False
    names = {p.name for p in spec_dir.iterdir()}
    return names <= _DEBUG_ORPHAN_ALLOWED


def remove_debug_orphan_stub(
    spec_dir: Path,
    archives_dir: Path,
    *,
    dry_run: bool = False,
) -> bool:
    """Remove a debug-only stub when archives already has the same name.

    Returns True if the stub was removed, or would be removed in dry-run.
    Returns False when ``spec_dir`` is not a stub or no archives sibling
    exists (stub is left untouched).
    """
    if not is_debug_orphan_stub(spec_dir):
        return False
    if not (archives_dir / spec_dir.name).is_dir():
        return False
    if dry_run:
        logger.info("Would remove orphan stub: %s", spec_dir.name)
        return True
    shutil.rmtree(spec_dir)
    logger.info("Removed orphan stub: %s", spec_dir.name)
    return True


def move_spec_with_conflict(source_dir: Path, dest_dir: Path) -> Path:
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


def move_spec(spec_dir: Path, archives_dir: Path) -> Path:
    """Move spec_dir into archives_dir, appending suffix on conflict.

    Thin wrapper around move_spec_with_conflict for backward compatibility.
    Returns the final destination path.
    """
    return move_spec_with_conflict(spec_dir, archives_dir)


def _remove_spex_worktree(spec_dir: Path, *, force: bool = False) -> None:
    """Remove linked spex worktree when ``meta.spex_worktree`` is set.

    Runs even if ``use_git_worktree`` is false, so leftover paths are cleaned.
    ``force`` maps to ``git worktree remove --force`` (archive ``-f``).
    """
    meta = load_meta(spec_dir)
    if not meta or not meta.spex_worktree:
        return
    from worktree import remove_worktree

    cwd = meta.main_worktree or None
    remove_worktree(meta.spex_worktree, force=force, cwd=cwd)


def _archive_one(
    spec_name: str,
    specs_dir: Path,
    archives_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> ArchiveItem:
    """Archive a single spec; return a structured outcome."""
    spec_dir = resolve_spec_dir(spec_name, specs_dir)
    if remove_debug_orphan_stub(spec_dir, archives_dir, dry_run=dry_run):
        dest = archives_dir / spec_dir.name
        if dry_run:
            return ArchiveItem(
                "would_archive",
                spec_dir.name,
                dest,
                detail="remove orphan stub",
            )
        return ArchiveItem(
            "archived",
            spec_dir.name,
            dest,
            detail="removed orphan stub",
        )
    if not force and not is_spec_completed(spec_dir):
        logger.info(
            "Skipping: spec is not completed (use --force to archive)"
        )
        return ArchiveItem(
            "skipped",
            spec_dir.name,
            spec_dir,
            detail="not completed",
        )
    if not force and has_active_branch(spec_dir):
        meta = load_meta(spec_dir)
        spex_branch = meta.spex_branch if meta else ""
        logger.info(
            "Skipping: spex branch '%s' still exists"
            " (use --force to archive)", spex_branch
        )
        return ArchiveItem(
            "skipped",
            spec_dir.name,
            spec_dir,
            detail=f"active branch '{spex_branch}'",
        )
    if dry_run:
        logger.info("Would archive: %s", spec_dir.name)
        return ArchiveItem(
            "would_archive",
            spec_dir.name,
            archives_dir / spec_dir.name,
        )
    archives_dir.mkdir(parents=True, exist_ok=True)
    _remove_spex_worktree(spec_dir, force=force)
    dest = move_spec(spec_dir, archives_dir)
    logger.info("Archived: %s -> %s", spec_dir.name, dest)
    return ArchiveItem("archived", spec_dir.name, dest)


def archive_single_spec(
    spec_name: str,
    specs_dir: Path,
    archives_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> Path | None:
    """Archive a single spec by name. Supports partial name matching.

    Returns the destination path, or None if skipped due to active branch.
    When a debug-only stub is cleaned because archives already has the
    same name, returns the existing archives path (success, no ``-2``).
    """
    item = _archive_one(
        spec_name, specs_dir, archives_dir, force=force, dry_run=dry_run,
    )
    if item.action in ("archived", "would_archive"):
        return item.spec_path
    return None


def _restore_one(
    spec_name: str,
    specs_dir: Path,
    archives_dir: Path,
    dry_run: bool = False,
) -> ArchiveItem:
    """Restore a single spec from archives; return a structured outcome."""
    if not archives_dir.is_dir():
        logger.error(
            "Error: archives directory does not exist: %s", archives_dir
        )
        sys.exit(1)

    matches = find_matching_specs(spec_name, archives_dir)
    if not matches:
        logger.error(
            "Error: no spec matching '%s' found in archives.", spec_name
        )
        sys.exit(1)
    if len(matches) > 1:
        names = "\n  ".join(m.name for m in matches)
        logger.error(
            "Error: multiple specs match '%s' in archives:\n  %s",
            spec_name, names
        )
        sys.exit(1)

    src = matches[0]
    if dry_run:
        logger.info("Would restore: %s", src.name)
        return ArchiveItem(
            "would_restore",
            src.name,
            specs_dir / src.name,
        )
    specs_dir.mkdir(parents=True, exist_ok=True)
    dest = move_spec_with_conflict(src, specs_dir)
    logger.info("Restored: %s -> %s", src.name, dest)
    return ArchiveItem("restored", src.name, dest)


def restore_single_spec(
    spec_name: str,
    specs_dir: Path,
    archives_dir: Path,
    dry_run: bool = False,
) -> Path | None:
    """Restore a single spec from archives back to specs.

    Uses fuzzy substring matching against archives_dir. Exits with error
    if no match or multiple matches.

    Returns the destination path in specs_dir, or None on error.
    """
    item = _restore_one(spec_name, specs_dir, archives_dir, dry_run=dry_run)
    return item.spec_path


def _build_parser() -> ArgumentParser:
    """Build the argument parser for ``spex archive``."""
    parser = ArgumentParser(
        prog="spex archive",
        description="Archive completed specs.",
    )
    parser.add_argument("--name", help="Archive a single spec by name")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Preview without moving")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Bypass spex_branch existence check")
    parser.add_argument("--restore", action="store_true",
                        help="Restore a spec from archives back to specs")
    parser.add_argument("--not", action="store_true", dest="restore",
                        help=argparse.SUPPRESS)
    parser.add_argument("--all-projects", action="store_true",
                        help="Archive specs from all projects")
    parser.add_argument(
        "--json", action="store_true", dest="json_mode",
        help="Emit machine-readable JSON on stdout",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse(argv)

    specs_dir = get_specs_dir()
    archives_dir = get_archives_dir()
    results: list[ArchiveItem] = []

    if args.restore:
        if not args.name:
            logger.error(
                "Error: --restore requires --name to specify what to restore."
            )
            sys.exit(1)
        item = _restore_one(
            args.name, specs_dir, archives_dir, dry_run=args.dry_run,
        )
        results.append(item)
        if args.json_mode:
            _emit_json(args.dry_run, results)
        return

    if args.name:
        item = _archive_one(
            args.name, specs_dir, archives_dir, args.force,
            dry_run=args.dry_run,
        )
        results.append(item)
        if args.json_mode:
            _emit_json(args.dry_run, results)
        return

    ctx = get_project_context()

    if not ctx.in_git_workdir() and not args.all_projects:
        logger.info(
            "Not in a git workdir. Use --all-projects to archive"
            " specs from all projects."
        )
        results.append(ArchiveItem(
            "noop",
            "",
            detail="Not in a git workdir; use --all-projects",
        ))
        if args.json_mode:
            _emit_json(args.dry_run, results)
        return

    completed = find_completed_specs(
        specs_dir, ctx, args.force, all_projects=args.all_projects,
    )

    def _cleanup_orphan_stubs(*, dry_run: bool) -> list[ArchiveItem]:
        cleaned: list[ArchiveItem] = []
        if not specs_dir.is_dir():
            return cleaned
        for entry in sorted(specs_dir.iterdir()):
            if entry.is_dir() and remove_debug_orphan_stub(
                entry, archives_dir, dry_run=dry_run
            ):
                dest = archives_dir / entry.name
                if dry_run:
                    cleaned.append(ArchiveItem(
                        "would_archive",
                        entry.name,
                        dest,
                        detail="remove orphan stub",
                    ))
                else:
                    cleaned.append(ArchiveItem(
                        "archived",
                        entry.name,
                        dest,
                        detail="removed orphan stub",
                    ))
        return cleaned

    if args.dry_run:
        # Active-branch skips only when not --force (force includes them
        # in completed; listing them again would double-count in JSON).
        skipped = []
        if not args.force:
            # Same relatedness scope as find_completed_specs / would_archive.
            skipped = [
                d for d in sorted(specs_dir.iterdir())
                if (
                    d.is_dir()
                    and is_spec_completed(d)
                    and has_active_branch(d)
                    and (
                        args.all_projects or ctx.is_related_to(d)
                    )
                )
            ]
        if completed:
            logger.info("Would archive %d spec(s):", len(completed))
            for spec_dir in completed:
                logger.info("  %s", spec_dir.name)
                results.append(ArchiveItem(
                    "would_archive",
                    spec_dir.name,
                    archives_dir / spec_dir.name,
                ))
        else:
            logger.info("No completed specs to archive.")
        if skipped:
            logger.info(
                "Would skip %d spec(s) (active spex_branch):", len(skipped)
            )
            for spec_dir in skipped:
                meta = load_meta(spec_dir)
                branch = meta.spex_branch if meta else ""
                logger.info("  %s (%s)", spec_dir.name, branch)
                results.append(ArchiveItem(
                    "skipped",
                    spec_dir.name,
                    spec_dir,
                    detail=f"active branch '{branch}'",
                ))
        results.extend(_cleanup_orphan_stubs(dry_run=True))
        if not results:
            results.append(ArchiveItem(
                "noop",
                "",
                detail="No completed specs to archive.",
            ))
        if args.json_mode:
            _emit_json(True, results)
        return

    results.extend(_cleanup_orphan_stubs(dry_run=False))
    if not completed:
        if not results:
            logger.info("No completed specs to archive.")
            results.append(ArchiveItem(
                "noop",
                "",
                detail="No completed specs to archive.",
            ))
        if args.json_mode:
            _emit_json(False, results)
        return

    archives_dir.mkdir(parents=True, exist_ok=True)
    for spec_dir in completed:
        _remove_spex_worktree(spec_dir, force=args.force)
        dest = move_spec(spec_dir, archives_dir)
        logger.info("Archived: %s -> %s", spec_dir.name, dest)
        results.append(ArchiveItem("archived", spec_dir.name, dest))

    if args.json_mode:
        _emit_json(False, results)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
