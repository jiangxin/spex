"""Helper utilities for applying specs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cli import ArgumentParser
from common import (
    DEFAULT_SPEX_BRANCH_PREFIX,
    SpecMeta,
    logger,
    strip_date_prefix,
)

# ---------------------------------------------------------------------------
# Dirty detection (apply.md Phase 4 six-step algorithm)
# ---------------------------------------------------------------------------


def strip_porcelain_quotes(path: str) -> str:
    """Strip surrounding double quotes from a porcelain path token."""
    if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
        return path[1:-1]
    return path


def parse_porcelain_paths(line: str) -> list[str]:
    """Extract path(s) from one ``git status --porcelain`` line.

    Status is the first two characters; paths follow the separating space.
    Renames/copies yield both sides of `` -> ``. Surrounding quotes are
    stripped from each path.
    """
    if not line:
        return []
    # Porcelain: XY + space + path info (XY may include spaces rarely;
    # standard format is always two status chars then a space).
    if len(line) < 4 or line[2] != " ":
        # Malformed / unexpected — treat remainder after optional status.
        rest = line[3:] if len(line) > 3 else line
    else:
        rest = line[3:]
    if " -> " in rest:
        left, right = rest.split(" -> ", 1)
        return [strip_porcelain_quotes(left), strip_porcelain_quotes(right)]
    return [strip_porcelain_quotes(rest)]


def resolve_repo_path(path: str, toplevel: str) -> str:
    """Resolve a porcelain path to absolute using the git toplevel."""
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str(Path(toplevel) / path)


def is_under_spex_root(abs_path: str, spex_root: str) -> bool:
    """True iff ``abs_path`` equals ``spex_root`` or is under it as a directory.

    Uses a directory boundary (``spex_root + '/'``), never a bare string
    prefix — so ``.spex.toml`` is not treated as under ``.spex``.
    """
    return abs_path == spex_root or abs_path.startswith(spex_root + "/")


def compute_dirty_from_porcelain(
    porcelain_text: str,
    spex_root: str,
    toplevel: str,
) -> tuple[bool, list[str]]:
    """Apply Phase 4 dirty algorithm to porcelain output.

    Steps:
      1–2. Parse each line; rename → both path sides; strip quotes
      3. Resolve each path to absolute via ``toplevel``
      4–5. Drop a line only if every path is under ``spex_root``
      6. dirty iff any line remains

    Returns ``(dirty, paths)`` where ``paths`` are absolute paths from
    remaining lines that are **not** under ``spex_root`` (excl. spex_root).
    """
    dirty_paths: list[str] = []
    for raw in porcelain_text.splitlines():
        if not raw:
            continue
        rel_paths = parse_porcelain_paths(raw)
        if not rel_paths:
            continue
        abs_paths = [resolve_repo_path(p, toplevel) for p in rel_paths]
        if all(is_under_spex_root(p, spex_root) for p in abs_paths):
            continue
        for p in abs_paths:
            if not is_under_spex_root(p, spex_root):
                dirty_paths.append(p)
    return (bool(dirty_paths), dirty_paths)


def collect_dirty(
    spex_root: str,
    cwd: str | Path | None = None,
) -> tuple[bool, list[str], str]:
    """Run git status and compute dirty state.

    Returns ``(dirty, paths, spex_root)``. Raises
    ``subprocess.CalledProcessError`` on git failure.
    """
    spex_root_abs = str(Path(spex_root))
    if not Path(spex_root_abs).is_absolute():
        spex_root_abs = str(Path(spex_root_abs).resolve())

    toplevel = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        text=True,
        stderr=subprocess.PIPE,
    ).strip()
    porcelain = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        text=True,
        stderr=subprocess.PIPE,
    )
    dirty, paths = compute_dirty_from_porcelain(
        porcelain, spex_root_abs, toplevel,
    )
    return dirty, paths, spex_root_abs


def _extract_spec_name_for_branch(spec_dir: Path, meta) -> str:
    """Get the spec name to use for branch naming."""
    return meta.name or spec_dir.name


def validate_apply_branch(
    config: dict, spec_dir: Path, cwd: str | Path | None = None,
) -> None:
    """Perform branch setup for applying a spec.

    Steps:
    1. If all spec tasks are completed, error and exit.
    2. If branch_management is False in config, return immediately.
    3. If meta.json has spex_branch, ensure current branch matches it;
       switch if not (exit on failure).
    4. If meta.json has no spex_branch, try creating a branch using
       spex/<spec-name-without-date-prefix>, then spex/<spec-name-with-date-prefix>.
       Exit on failure if both fail.
    5. On success, switch to the branch, set git branch description from
       the spec's description, and persist spex_branch to meta.json.
    """
    import common
    from branch import (
        branch_exists,
        create_and_switch_branch,
        get_current_branch,
        set_branch_description,
        switch_branch,
    )

    if common.is_spec_completed(spec_dir):
        status = common.format_spec(spec_dir, verbose=2)
        logger.error(f"Error: spec is already completed.\n{status}")
        sys.exit(1)

    if not bool(config["branch_management"]):
        return

    meta = common.load_meta(spec_dir) or SpecMeta()
    spex_branch = meta.spex_branch

    if spex_branch:
        try:
            current = get_current_branch(cwd)
        except RuntimeError:
            # Detached HEAD (e.g. review agent ran `git checkout <sha>`):
            # treat as not on spex_branch and re-attach below.
            current = None
        if current != spex_branch:
            if not branch_exists(spex_branch, cwd):
                logger.error(
                    f"Error: spex_branch '{spex_branch}' defined in meta.json "
                    f"does not exist.",
                )
                sys.exit(1)
            try:
                switch_branch(spex_branch, cwd)
            except subprocess.CalledProcessError as e:
                logger.error(
                    f"Error: failed to switch to '{spex_branch}': "
                    f"{e.stderr.strip() or e}",
                )
                sys.exit(1)
            if current is None:
                logger.info(
                    f"Re-attached detached HEAD to branch '{spex_branch}'.",
                )
            else:
                logger.info(f"Switched to branch '{spex_branch}'.")
        return

    spec_name = _extract_spec_name_for_branch(spec_dir, meta)
    short_name = strip_date_prefix(spec_name)

    base = meta.branch or "main"
    if not branch_exists(base, cwd):
        logger.warning(
            "Base branch '%s' does not exist; creating from current HEAD.",
            base,
        )
        base = None

    candidates = [
        f"{DEFAULT_SPEX_BRANCH_PREFIX}{short_name}",
        f"{DEFAULT_SPEX_BRANCH_PREFIX}{spec_name}",
    ]

    created_branch = None
    for candidate in candidates:
        if branch_exists(candidate, cwd):
            created_branch = candidate
            break
        try:
            create_and_switch_branch(candidate, cwd, base=base)
            created_branch = candidate
            break
        except subprocess.CalledProcessError:
            continue

    if created_branch is None:
        logger.error(
            f"Error: failed to create branch. Tried: {', '.join(candidates)}",
        )
        sys.exit(1)

    # create_and_switch_branch already uses `git switch -c` which switches to the new
    # branch, so no separate switch_branch call is needed here.

    description = common.get_spec_description(spec_dir)
    if description:
        try:
            set_branch_description(created_branch, description, cwd)
        except subprocess.CalledProcessError:
            pass

    meta_path = spec_dir / "meta.json"
    meta.spex_branch = created_branch
    common.atomic_write_json(meta_path, meta.to_dict())

    logger.info(f"Created and switched to branch '{created_branch}'.")


def _do_precheck(args):
    """Perform branch setup for applying a spec."""
    import common
    import config as cfg
    import hooks

    ctx = cfg.get_project_context()
    spec_dir = common.resolve_spec_dir(args.name)
    validate_apply_branch(ctx.config, spec_dir, cwd=ctx.top_workdir)

    meta = common.load_meta(spec_dir) or SpecMeta()
    hooks.run_pre_action(
        "apply",
        {
            "source_branch": meta.spex_branch or "",
            "target_branch": meta.branch or "main",
        },
        workdir=ctx.top_workdir,
        spec_name=spec_dir.name,
    )


def cli_precheck(argv=None):
    """CLI: perform branch setup for applying a spec."""

    args = _build_parser().parse(["precheck"] + (argv or []))
    _do_precheck(args)


def _do_ensure_branch(args):
    """Re-attach to spex_branch without running apply hooks.

    Used after review/fix sub-agents that may have left detached HEAD
    via ``git checkout <sha>``.

    Before switching, refuse re-attach when detached HEAD is not an
    ancestor of ``spex_branch`` (would silently discard an amend).
    """
    import common
    import config as cfg
    from branch import branch_exists, get_current_branch

    ctx = cfg.get_project_context()
    spec_dir = common.resolve_spec_dir(args.name)
    cwd = ctx.top_workdir

    # Guard only for ensure-branch (not precheck): refuse discarding
    # detached commits that are not ancestors of spex_branch.
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if head.returncode == 0:
        pre = head.stdout.strip()
        try:
            get_current_branch(cwd)
            detached = False
        except RuntimeError:
            detached = True
        if detached:
            meta = common.load_meta(spec_dir) or SpecMeta()
            spex_branch = meta.spex_branch
            if spex_branch and branch_exists(spex_branch, cwd):
                ancestor = subprocess.run(
                    [
                        "git",
                        "merge-base",
                        "--is-ancestor",
                        pre,
                        spex_branch,
                    ],
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                )
                if ancestor.returncode != 0:
                    logger.error(
                        "Detached HEAD %s is not an ancestor of '%s'; "
                        "re-attaching would discard it. Recover with: "
                        "git branch -f %s %s",
                        pre,
                        spex_branch,
                        spex_branch,
                        pre,
                    )
                    sys.exit(1)

    validate_apply_branch(ctx.config, spec_dir, cwd=cwd)


def cli_ensure_branch(argv=None):
    """CLI: ensure HEAD is on the spec's spex_branch."""

    args = _build_parser().parse(["ensure-branch"] + (argv or []))
    _do_ensure_branch(args)


def _do_post_action(args):
    """Run post-action hook, and show hint."""
    import common
    import config as cfg
    import hooks
    from debug_log import emit_apply_anchor

    spec_dir = common.resolve_spec_dir(args.name)
    spec_name = spec_dir.name
    meta = common.load_meta(spec_dir)
    spex_branch = meta.spex_branch if meta else ""
    if not spex_branch:
        return

    target = meta.branch or "main"
    ctx = cfg.get_project_context()
    workdir = ctx.top_workdir

    hooks.run_post_action(
        "apply",
        {
            "source_branch": spex_branch,
            "target_branch": target,
        },
        workdir,
        spec_name,
    )

    emit_apply_anchor(spec_dir, "===== APPLY post-action ok =====")

    if hooks.find_hook("post-action", workdir) is None:
        logger.info(
            f"Development completed on spec branch {spex_branch}.\n"
            f"After local code review, run /spex merge to merge into\n"
            f"branch {target}, or create a pull request."
        )


def cli_post_action(argv=None):
    """CLI: run post-action hook, and show hint."""

    args = _build_parser().parse(["post-action"] + (argv or []))
    _do_post_action(args)


def _do_dirty(args):
    """Compute working-tree dirtiness excluding spex_root (Phase 4)."""
    import config as cfg

    ctx = cfg.get_project_context()
    if getattr(args, "spex_root", None):
        spex_root = str(Path(args.spex_root).expanduser().resolve())
    else:
        spex_root = ctx.spex_root
        if not spex_root:
            logger.error("Error: spex_root is not configured.")
            sys.exit(1)
        # Paths section is already absolute; normalize anyway.
        spex_root = str(Path(spex_root).expanduser().resolve())

    cwd = ctx.top_workdir or ctx.cwd

    try:
        dirty, paths, spex_root_abs = collect_dirty(spex_root, cwd=cwd)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip() if isinstance(e.stderr, str) else ""
        logger.error(
            "Error: git failed while checking dirty status%s",
            f": {err}" if err else "",
        )
        sys.exit(e.returncode or 1)

    payload = {
        "dirty": dirty,
        "paths": paths,
        "spex_root": spex_root_abs,
    }
    # Machine-default JSON (always). --json kept for SOP / discoverability.
    print(json.dumps(payload))


def cli_dirty(argv=None):
    """CLI: report dirty working tree excluding spex_root."""

    args = _build_parser().parse(["dirty"] + (argv or []))
    _do_dirty(args)


def _build_parser():
    """Build the top-level parser with subcommand sub-parsers."""
    parser = ArgumentParser(
        prog="spex apply-helper",
        description="Helper utilities for applying specs.",
    )
    subs = parser.add_subparsers(dest="subcmd", title="Subcommands")

    p_precheck = subs.add_parser(
        "precheck",
        description=(
            "Validate branch setup for applying a spec."
        ),
        help="Validate branch setup for applying a spec",
    )
    p_precheck.add_argument(
        "--name", required=True, help="Spec name",
    )

    p_ensure = subs.add_parser(
        "ensure-branch",
        description=(
            "Ensure HEAD is on the spec's spex_branch "
            "(re-attach if detached). Does not run apply hooks."
        ),
        help="Re-attach to spex_branch if detached",
    )
    p_ensure.add_argument(
        "--name", required=True, help="Spec name",
    )

    p_post = subs.add_parser(
        "post-action",
        description="Run post-action hook and show hint.",
        help="Run post-action hook and show hint",
    )
    p_post.add_argument(
        "--name", required=True, help="Spec name",
    )

    p_dirty = subs.add_parser(
        "dirty",
        description=(
            "Report whether the working tree is dirty outside spex_root "
            "(apply.md Phase 4 algorithm)."
        ),
        help="Check dirty tree excluding spex_root",
    )
    p_dirty.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Output JSON (machine default; always emitted)",
    )
    p_dirty.add_argument(
        "--spex-root",
        dest="spex_root",
        default=None,
        help="Absolute or relative spex_root override",
    )

    return parser


def main(argv=None):
    """Parse args, route to subcommand."""

    parser = _build_parser()
    args = parser.parse(argv)

    if not args.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    if args.subcmd == "precheck":
        _do_precheck(args)
    elif args.subcmd == "ensure-branch":
        _do_ensure_branch(args)
    elif args.subcmd == "post-action":
        _do_post_action(args)
    elif args.subcmd == "dirty":
        _do_dirty(args)
