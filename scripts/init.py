#!/usr/bin/env python3
"""Initialize the spex environment."""

import subprocess
import sys
from pathlib import Path

from common import (
    ensure_initialized,
    get_current_workdir,
)
from config import clear_config_cache, get_context


def is_initialized(workdir=None):
    """Check if spex environment is initialized.

    Returns True if a spex_root is resolved and its specs/ directory exists.
    """
    ctx = get_context(workdir)
    if not ctx.spex_roots:
        return False
    return (Path(ctx.spex_root) / "specs").is_dir()


def _install_deps():
    """Install Python dependencies from the skill's pyproject.toml."""
    from common import _get_skill_path

    skill_dir = _get_skill_path()
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


def _install_cli():
    """Install spex CLI symlink to ~/.local/bin."""
    import shutil as _shutil

    from common import _get_skill_path

    script_path = _get_skill_path() / "scripts" / "spex"
    link_dir = Path.home() / ".local" / "bin"
    link_path = link_dir / "spex"

    found = _shutil.which("spex")
    if found and Path(found).resolve() == script_path.resolve():
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


_DEFAULT_TOML = '# spex_root = ".spex"\n'


def _create_toml_config():
    """Create ~/.spex.toml if no config exists yet."""
    ctx = get_context()
    if ctx.spex_tomls:
        return

    target = Path.home() / ".spex.toml"
    target.write_text(_DEFAULT_TOML, encoding="utf-8")
    print(f"Created: {target}")
    clear_config_cache()


def run_init(workdir=None):
    """Run full spex initialization."""
    if workdir is None:
        workdir = get_current_workdir()

    _install_deps()
    _create_toml_config()
    clear_config_cache()

    ctx = get_context(workdir)
    if not ctx.spex_roots:
        target = Path.home() / ctx.config.get("spex_root", ".spex")
        ensure_initialized(str(target))
    else:
        ensure_initialized(ctx.spex_root)

    _install_cli()
    print("Initialization complete.")


_USAGE = """\
Usage: spex init [--check]

Initialize the spex environment.

Options:
  --check     Check if initialized (exit 0 = yes, exit 1 = no)
  -h, --help  Show this help message and exit
"""


def main(argv=None):
    from common import check_help_flag

    check_help_flag(_USAGE, argv)
    args = argv if argv is not None else (sys.argv[2:] if len(sys.argv) > 2 else sys.argv[1:])

    if "--check" in args:
        sys.exit(0 if is_initialized() else 1)

    run_init()


if __name__ == "__main__":
    main()
