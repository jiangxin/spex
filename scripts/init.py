#!/usr/bin/env python3
"""Initialize the spex environment."""

import subprocess
import sys
from pathlib import Path

from common import (
    _create_default_toml,
    _sync_all_templates,
    ensure_initialized,
    get_current_workdir,
)
from config import clear_config_cache, get_context


def is_initialized(workdir=None):
    """Check if spex environment is initialized.

    Returns True if a spex_root is resolved and its specs/ directory exists.
    """
    ctx = get_context(workdir)
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


def _create_toml_config(verbose=False):
    """Create ~/.spex.toml if no config exists yet."""
    ctx = get_context()
    if ctx.spex_tomls:
        if verbose:
            print(f"Config already exists: {ctx.spex_tomls[0]}")
        return

    _create_default_toml()
    print(f"Created: {Path.home() / '.spex.toml'}")
    clear_config_cache()


def run_init(workdir=None, verbose=False):
    """Run full spex initialization."""
    if workdir is None:
        workdir = get_current_workdir()

    _install_deps(verbose=verbose)

    ctx = get_context(workdir)

    if not ctx.spex_tomls:
        _create_toml_config(verbose=verbose)
        clear_config_cache()
        ctx = get_context(workdir)

    spex_root = Path(ctx.spex_root)
    ensure_initialized(str(spex_root), verbose=verbose)
    _sync_all_templates(spex_root, verbose=verbose)

    _install_cli(verbose=verbose)
    print("Initialization complete.")


_USAGE = """\
Usage: spex init [--check] [-v | --verbose]

Initialize the spex environment.

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
    run_init(verbose=verbose)


if __name__ == "__main__":
    main()
