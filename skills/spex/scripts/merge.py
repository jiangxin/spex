"""Submit/merge CLI logic for spex."""

from __future__ import annotations

import contextlib
import io
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cli import ArgumentParser
from common import logger


@dataclass(frozen=True)
class MergePlan:
    cwd: Path
    current_branch: str
    multiple_worktrees: bool
    target_checked_out: bool
    restore_branch: str


def _plan_merge(target: str, caller: Path | None) -> MergePlan:
    """Select a checkout and record the branch to restore after merging."""
    from branch import get_current_branch
    from worktree import list_worktrees

    if caller is None:
        raise RuntimeError("Run merge from a Git working tree.")
    worktrees = [entry for entry in list_worktrees(cwd=caller) if "bare" not in entry]
    multiple = len(worktrees) > 1
    target_branch = target.removeprefix("refs/heads/")
    target_ref = f"refs/heads/{target_branch}"
    for entry in worktrees:
        if entry.get("branch") == target_ref:
            return MergePlan(Path(entry["path"]), target_branch, multiple, True, "")

    try:
        current_branch = get_current_branch(cwd=caller)
    except RuntimeError as exc:
        if multiple:
            raise RuntimeError(
                f"Cannot temporarily switch branches in '{caller}' with detached HEAD. "
                "Check out a local branch and retry."
            ) from exc
        current_branch = ""
    return MergePlan(caller, current_branch, multiple, False,
                     current_branch if multiple else "")


def _fail_with_errors(payload: dict) -> None:
    """Print JSON errors to stdout and mirror each to stderr, then exit 1."""
    for err in payload.get("errors") or []:
        logger.error("%s", err)
    print(json.dumps(payload))
    sys.exit(1)


def _build_submit_parser() -> ArgumentParser:
    """Build the argument parser for ``spex submit``."""
    parser = ArgumentParser(
        prog="spex submit",
        description="Submit (merge) a spex branch back to the target branch.",
    )
    parser.add_argument(
        "name",
        metavar="<spec-name>",
        nargs="?",
        default="",
        help="Spec name to submit",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip automatic archiving after successful merge",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Preview merge without executing",
    )
    return parser


def _find_submittable_specs(ctx):
    """Find specs ready to submit: all tasks done + has spex_branch."""
    import common
    from common import Spec, find_completed_specs

    specs_dir = common.get_specs_dir()
    completed = find_completed_specs(specs_dir, ctx, force=True)
    results = []
    for d in completed:
        meta = common.load_meta(d)
        if meta and meta.spex_branch:
            spec = Spec.from_dir(d)
            if spec is not None:
                results.append(spec)
    return results


def cli_submit(argv=None, command="submit") -> None:
    """CLI: submit (merge) a spex branch back to target. Output JSON."""
    import common
    import config as cfg
    import hooks
    from branch import (
        branch_exists,
        create_and_switch_branch,
        merge_branch,
        resolve_default_branch,
        switch_branch,
    )

    parser = _build_submit_parser()
    parsed = parser.parse(argv)
    spec_name = parsed.name

    ctx = cfg.get_project_context()
    conf = ctx.config

    if not spec_name:
        candidates = _find_submittable_specs(ctx)
        if not candidates:
            logger.error("No submittable specs found.")
            sys.exit(1)
        elif len(candidates) == 1:
            spec_dir = candidates[0].path
            spec_name = candidates[0].name
            logger.error("Auto-selected: %s", spec_name)
        else:
            from common import prompt_selection

            selected = prompt_selection(candidates)
            spec_dir = selected.path
            spec_name = selected.name
    else:
        spec_dir = common.resolve_spec_dir(spec_name)
        spec_name = spec_dir.name if spec_dir else spec_name

    if not ctx.is_related_to(spec_dir):
        meta = common.load_meta(spec_dir)
        workdir = meta.workdir if meta else "(unknown)"
        logger.error(
            "Error: spec '%s' is not related to current project, "
            "it is associated with %s", spec_name, workdir
        )
        sys.exit(1)
    meta = common.load_meta(spec_dir)
    source = meta.spex_branch if meta else ""
    target = meta.branch if (meta and meta.branch) else None
    if target is None:
        target = resolve_default_branch(cwd=ctx.top_workdir)
    method = conf["submit_method"]
    errors: list[str] = []

    todo_backup = spec_dir / "todo.json.lock"
    if todo_backup.exists():
        quoted_name = shlex.quote(spec_name)
        errors.append(
            f"Unfinished todo transaction at '{todo_backup}'. Finish it with "
            f"`spex todo-helper transaction commit {quoted_name}` or "
            f"`spex todo-helper transaction rollback {quoted_name}` before retrying."
        )
        _fail_with_errors({"action": method, "source": source, "target": target,
                           "errors": errors})

    if not source:
        errors.append("No spex_branch in spec meta.json")
        _fail_with_errors({"action": method, "source": "", "target": target,
                           "errors": errors})

    try:
        plan = _plan_merge(target, ctx.top_workdir)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        errors.append(detail.strip())
        _fail_with_errors({"action": method, "source": source, "target": target,
                           "errors": errors})

    if parsed.dry_run:
        merge_cwd = str(plan.cwd)
        spex_wt = (meta.spex_worktree if meta else "") or ""
        will_archive = not parsed.no_archive
        would_remove = will_archive and bool(spex_wt)
        merge_cwd_head = plan.current_branch
        would_switch = not plan.target_checked_out
        logger.info("Would merge: %s -> %s", source, target)
        logger.info("Would merge in worktree: %s", merge_cwd)
        logger.info(
            "  (current HEAD: %s)",
            merge_cwd_head or "unknown",
        )
        if would_switch:
            logger.info("Would switch to %s", target)
        logger.info("Would git merge %s", source)
        if spex_wt:
            logger.info("Feature worktree: %s", spex_wt)
        if will_archive:
            logger.info("Would archive: %s", spec_dir.name)
        if would_remove:
            logger.info("Would remove worktree: %s", spex_wt)
        print(json.dumps({
            "action": method,
            "source": source,
            "target": target,
            "archived": will_archive,
            "dry_run": True,
            "merge_cwd": merge_cwd,
            "merge_cwd_head": merge_cwd_head,
            "would_switch": would_switch,
            "target_checked_out": plan.target_checked_out,
            "spex_worktree": spex_wt,
            "would_remove_worktree": would_remove,
            "errors": [],
        }))
        return

    done, total = common.get_todo_progress(spec_dir)
    hooks.run_pre_action(
        command,
        {
            "source_branch": source,
            "target_branch": target,
            "done": done,
            "undone": total - done,
        },
        workdir=ctx.top_workdir,
        spec_name=spec_dir.name,
    )

    # If target branch doesn't exist, create it from the current branch
    if not branch_exists(target, cwd=plan.cwd):
        logger.warning(
            "Warning: target branch '%s' does not exist. "
            "Creating it from HEAD in '%s'.", target, plan.cwd,
        )
        try:
            create_and_switch_branch(target, cwd=plan.cwd)
        except subprocess.CalledProcessError as e:
            errors.append(
                f"Failed to create target branch '{target}' in '{plan.cwd}': "
                f"{(e.stderr or str(e)).strip()}"
            )
            _fail_with_errors({"action": method, "source": source,
                               "target": target, "errors": errors})

    if method == "merge":
        try:
            merge_branch(target, source, cwd=plan.cwd)
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or e.stdout or str(e)).strip()
            errors.append(f"Merge failed in '{plan.cwd}': {detail}")
            _fail_with_errors({"action": method, "source": source,
                               "target": target, "errors": errors})
        if plan.restore_branch:
            try:
                switch_branch(plan.restore_branch, cwd=plan.cwd)
            except subprocess.CalledProcessError as e:
                detail = (e.stderr or str(e)).strip()
                errors.append(
                    f"Merge completed in '{plan.cwd}', but restoring branch "
                    f"'{plan.restore_branch}' failed: {detail}"
                )
                _fail_with_errors({"action": method, "source": source,
                                   "target": target, "errors": errors})
    else:
        errors.append(f"submit method '{method}' is not implemented")
        _fail_with_errors({"action": method, "source": source,
                           "target": target, "errors": errors})

    # Run post-action hook on success
    done, total = common.get_todo_progress(spec_dir)
    workdir = ctx.top_workdir
    hooks.run_post_action(
        command,
        {
            "source_branch": source,
            "target_branch": target,
            "action": method,
            "done": done,
            "undone": total - done,
        },
        workdir,
        spec_name,
    )

    # Auto-archive the spec unless --no-archive is set
    archived = False
    if not parsed.no_archive:
        try:
            import archive as archive_mod

            with contextlib.redirect_stdout(io.StringIO()):
                result = archive_mod.archive_single_spec(
                    spec_name,
                    common.get_specs_dir(),
                    common.get_archives_dir(),
                    force=True,
                )
            archived = result is not None
        except Exception:
            archived = False

    print(json.dumps({"action": method, "source": source,
                      "target": target, "archived": archived,
                      "errors": errors}))
