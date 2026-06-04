#!/usr/bin/env python3
"""Initialize the spex environment."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from cli import ArgumentParser
from common import (
    _create_default_toml,
    _sync_all_templates,
    ensure_initialized,
)
from config import (
    clear_config_cache,
    generate_updated_toml,
    get_main_worktree,
    get_project_context,
    get_top_workdir,
    load_config,
    safe_update_toml,
)


def is_initialized(workdir=None):
    """Check if spex environment is initialized.

    Returns True if a spex_root is resolved and its specs/ directory exists.
    """
    ctx = get_project_context(workdir)
    if not ctx.spex_tomls:
        return False
    if ctx.spex_root and not Path(ctx.spex_root).is_dir():
        return False
    return True


def _install_deps(verbose=False, dry_run=False):
    """Install Python dependencies from the skill's pyproject.toml."""
    from common import _get_skill_path

    skill_dir = _get_skill_path()
    if dry_run:
        print(f"Would install dependencies from {skill_dir}")
        return True
    if verbose:
        print(f"Installing dependencies from {skill_dir} ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", str(skill_dir), "--quiet"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Warning: pip install failed: {result.stderr.strip()}",
              file=sys.stderr)
        return False
    print("Installed Python dependencies.")
    return True


def _install_cli(verbose=False, dry_run=False):
    """Install spex CLI symlink to ~/.local/bin."""
    import shutil as _shutil

    from common import _get_skill_path

    script_path = _get_skill_path() / "scripts" / "spex"
    link_dir = Path.home() / ".local" / "bin"
    link_path = link_dir / "spex"

    if dry_run:
        print(f"Would install CLI: {link_path} -> {script_path}")
        return

    found = _shutil.which("spex")
    if found and Path(found).resolve() == script_path.resolve():
        print(f"CLI already installed: {found}")
        return

    try:
        link_dir.mkdir(parents=True, exist_ok=True)
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        link_path.symlink_to(script_path)
        print(f"Installed CLI: {link_path} -> {script_path}")
    except PermissionError:
        print(f"Warning: cannot install CLI to {link_dir} (permission denied)",
              file=sys.stderr)


def _resolve_target_dir(dir_path):
    """Resolve target directory for init.

    If dir_path is inside a git repo, returns the main worktree (handles
    submodules and linked worktrees). Otherwise returns dir_path as-is.
    """
    target = Path(dir_path).resolve()
    if not target.is_dir():
        print(f"Error: not a directory: {dir_path}", file=sys.stderr)
        sys.exit(1)

    main_wt = get_main_worktree(str(target))
    return main_wt if main_wt is not None else target


def _init_target_toml(target_dir, verbose=False, dry_run=False):
    """Create .spex.toml in target_dir if it does not exist.

    The new file inherits effective config values from parent tomls.
    """
    toml_path = Path(target_dir) / ".spex.toml"
    if toml_path.is_file():
        print(f"Config already exists: {toml_path}")
        return

    if dry_run:
        print(f"Would create: {toml_path}")
        return

    effective = load_config(str(target_dir))
    content = generate_updated_toml(effective, force_keys={"spex_root"})
    toml_path.write_text(content, encoding="utf-8")
    print(f"Created: {toml_path}")


def _create_toml_config(workdir=None, verbose=False, dry_run=False):
    """Create or safely update .spex.toml files with the latest config schema."""
    ctx = get_project_context(workdir)

    if ctx.spex_tomls:
        changed = False
        for toml_path in ctx.spex_tomls:
            path = Path(toml_path)
            if dry_run:
                if safe_update_toml(path, dry_run=True):
                    print(f"Would reinitialize: {path}")
                else:
                    print(f"Config up-to-date: {path}")
            elif safe_update_toml(path):
                print(f"Reinitialized: {path}")
                changed = True
            else:
                print(f"Config up-to-date: {path}")
        if changed:
            clear_config_cache()
        return

    home_toml = Path.home() / ".spex.toml"
    if dry_run:
        print(f"Would create: {home_toml}")
        return
    _create_default_toml()
    print(f"Created: {home_toml}")
    clear_config_cache()


def run_init(workdir=None, target_dir=None, verbose=False, dry_run=False):
    """Run full spex initialization."""
    if dry_run:
        verbose = True

    if workdir is None:
        top = get_top_workdir()
        workdir = str(top) if top else None

    _install_deps(verbose=verbose, dry_run=dry_run)

    if target_dir:
        resolved = _resolve_target_dir(target_dir)
        _init_target_toml(resolved, verbose=verbose, dry_run=dry_run)
        if not dry_run:
            clear_config_cache()
        workdir = str(resolved)

    _create_toml_config(workdir=workdir, verbose=verbose, dry_run=dry_run)

    ctx = get_project_context(workdir)

    spex_root = Path(ctx.spex_root)
    ensure_initialized(str(spex_root), verbose=verbose, dry_run=dry_run)
    _sync_all_templates(spex_root, verbose=verbose, dry_run=dry_run)

    _install_cli(verbose=verbose, dry_run=dry_run)
    print("Initialization complete.")


def _build_parser() -> ArgumentParser:
    """Build the argument parser for ``spex init``."""
    parser = ArgumentParser(
        prog="spex init",
        description="Initialize the spex environment.",
    )
    parser.add_argument(
        "dir",
        nargs="?",
        default=None,
        help="Target directory to initialize (resolves to git main worktree)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if initialized (exit 0 = yes, exit 1 = no)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed operations during initialization",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="Preview operations without executing them",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse(argv)

    if args.check:
        sys.exit(0 if is_initialized() else 1)

    run_init(target_dir=args.dir, verbose=args.verbose, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
