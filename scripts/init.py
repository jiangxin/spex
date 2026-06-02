#!/usr/bin/env python3
"""Initialize the spex environment."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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


def _install_deps(verbose=False):
    """Install Python dependencies from the skill's pyproject.toml."""
    from common import _get_skill_path

    skill_dir = _get_skill_path()
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


def _install_cli(verbose=False):
    """Install spex CLI symlink to ~/.local/bin."""
    import shutil as _shutil

    from common import _get_skill_path

    script_path = _get_skill_path() / "scripts" / "spex"
    link_dir = Path.home() / ".local" / "bin"
    link_path = link_dir / "spex"

    found = _shutil.which("spex")
    if found and Path(found).resolve() == script_path.resolve():
        if verbose:
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


def _init_target_toml(target_dir, verbose=False):
    """Create .spex.toml in target_dir if it does not exist.

    The new file inherits effective config values from parent tomls.
    """
    toml_path = Path(target_dir) / ".spex.toml"
    if toml_path.is_file():
        if verbose:
            print(f"Config already exists: {toml_path}")
        return

    effective = load_config(str(target_dir))
    content = generate_updated_toml(effective, force_keys={"spex_root"})
    toml_path.write_text(content, encoding="utf-8")
    print(f"Created: {toml_path}")


def _create_toml_config(workdir=None, verbose=False):
    """Create or safely update .spex.toml files with the latest config schema."""
    ctx = get_project_context(workdir)

    if ctx.spex_tomls:
        changed = False
        for toml_path in ctx.spex_tomls:
            path = Path(toml_path)
            if safe_update_toml(path):
                print(f"Reinitialized: {path}")
                changed = True
            elif verbose:
                print(f"Config up-to-date: {path}")
        if changed:
            clear_config_cache()
        return

    home_toml = Path.home() / ".spex.toml"
    _create_default_toml()
    print(f"Created: {home_toml}")
    clear_config_cache()


def run_init(workdir=None, target_dir=None, verbose=False):
    """Run full spex initialization."""
    if workdir is None:
        top = get_top_workdir()
        workdir = str(top) if top else None

    _install_deps(verbose=verbose)

    if target_dir:
        resolved = _resolve_target_dir(target_dir)
        _init_target_toml(resolved, verbose=verbose)
        clear_config_cache()
        workdir = str(resolved)

    _create_toml_config(workdir=workdir, verbose=verbose)

    ctx = get_project_context(workdir)

    spex_root = Path(ctx.spex_root)
    ensure_initialized(str(spex_root), verbose=verbose)
    _sync_all_templates(spex_root, verbose=verbose)

    _install_cli(verbose=verbose)
    print("Initialization complete.")


_USAGE = """\
Usage: spex init [<dir>] [--check] [-v | --verbose]

Initialize the spex environment.

When <dir> is given, creates .spex.toml in that directory (resolving to the
git main worktree if applicable) and initializes its spex_root.

Options:
  --check        Check if initialized (exit 0 = yes, exit 1 = no)
  -v, --verbose  Show detailed operations during initialization
  -h, --help     Show this help message and exit
"""


def main(argv=None):
    from common import check_help_flag

    check_help_flag(_USAGE, argv)
    args = argv if argv is not None else (sys.argv[2:] if len(sys.argv) > 2 else sys.argv[1:])

    if "--check" in args:
        sys.exit(0 if is_initialized() else 1)

    verbose = "-v" in args or "--verbose" in args
    positional = [a for a in args if not a.startswith("-")]
    target_dir = positional[0] if positional else None

    run_init(target_dir=target_dir, verbose=verbose)


if __name__ == "__main__":
    main()
