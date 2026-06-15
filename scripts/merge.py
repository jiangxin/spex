"""Submit/merge CLI logic for spex."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys

from cli import ArgumentParser
from common import logger, strip_date_prefix


def _build_submit_parser() -> ArgumentParser:
    """Build the argument parser for ``spex submit``."""
    parser = ArgumentParser(
        prog="spex submit",
        description="Submit (merge) a spex branch back to the target branch.",
    )
    parser.add_argument(
        "topic",
        nargs="?",
        default="",
        help="Topic name to submit",
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


def _find_submittable_topics(ctx):
    """Find topics ready to submit: all tasks done + has spex_branch."""
    import common
    from common import Spec, find_completed_specs

    specs_dir = common.get_specs_dir()
    completed = find_completed_specs(specs_dir, ctx, force=True)
    results = []
    for d in completed:
        meta = common.load_meta(d)
        if meta and meta.spex_branch:
            topic = Spec.from_dir(d)
            if topic is not None:
                results.append(topic)
    return results


def cli_submit(argv=None) -> None:
    """CLI: submit (merge) a spex branch back to target. Output JSON."""
    import common
    import config as cfg
    import hooks
    from branch import merge_branch

    parser = _build_submit_parser()
    parsed = parser.parse(argv)
    topic_name = parsed.topic

    ctx = cfg.get_project_context()
    conf = ctx.config

    if not topic_name:
        candidates = _find_submittable_topics(ctx)
        if not candidates:
            logger.error("No submittable topics found.")
            sys.exit(1)
        elif len(candidates) == 1:
            topic_dir = candidates[0].path
            topic_name = candidates[0].name
            logger.error("Auto-selected: %s", topic_name)
        else:
            from common import prompt_selection

            selected = prompt_selection(candidates)
            topic_dir = selected.path
            topic_name = selected.name
    else:
        topic_dir = common.resolve_topic_dir(topic_name)

    if not ctx.is_related_to(topic_dir):
        meta = common.load_meta(topic_dir)
        workdir = meta.workdir if meta else "(unknown)"
        logger.error(
            "Error: topic '%s' is not related to current project, "
            "it is associated with %s", topic_name, workdir
        )
        sys.exit(1)
    meta = common.load_meta(topic_dir)
    source = meta.spex_branch if meta else ""
    target = (meta.branch or "main") if meta else "main"
    method = conf["submit_method"]
    errors: list[str] = []

    if not source:
        errors.append("No spex_branch in topic meta.json")
        print(json.dumps({"action": method, "source": "", "target": target,
                          "errors": errors}))
        sys.exit(1)

    if parsed.dry_run:
        logger.info("Would merge: %s -> %s", source, target)
        if not parsed.no_archive:
            logger.info("Would archive: %s", topic_dir.name)
        print(json.dumps({"action": method, "source": source,
                          "target": target, "archived": not parsed.no_archive,
                          "dry_run": True, "errors": []}))
        return

    if method == "merge":
        try:
            merge_branch(target, source, cwd=ctx.main_worktree)
        except subprocess.CalledProcessError as e:
            errors.append(f"Merge failed: {e.stderr.strip() or str(e)}")
            print(json.dumps({"action": method, "source": source,
                              "target": target, "errors": errors}))
            sys.exit(1)
    else:
        errors.append(f"submit method '{method}' is not implemented")
        print(json.dumps({"action": method, "source": source,
                          "target": target, "errors": errors}))
        sys.exit(1)

    # Run post-action hook on success
    short_name = strip_date_prefix(topic_dir.name)
    done, total = common.get_todo_progress(topic_dir)
    workdir = ctx.top_workdir
    hooks.run_post_action(
        "submit",
        {
            "topic": short_name,
            "source_branch": source,
            "target_branch": target,
            "action": method,
            "done": done,
            "undone": total - done,
        },
        workdir,
        short_name,
    )

    # Auto-archive the topic unless --no-archive is set
    archived = False
    if not parsed.no_archive:
        try:
            import archive as archive_mod

            with contextlib.redirect_stdout(io.StringIO()):
                result = archive_mod.archive_single_topic(
                    topic_name,
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
