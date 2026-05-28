#!/usr/bin/env python3
"""Initialize the spex environment."""

import subprocess
import sys
from pathlib import Path

from common import (
    EXAMPLES_TEMPLATE_DIR,
    TEMPLATE_DIR,
    ensure_initialized,
    get_current_workdir,
    get_spex_root,
)


def is_initialized(workdir=None):
    """Check if spex environment is initialized.

    Returns True if specs_dir, archives_dir, hooks_dir, and
    templates/examples/ all exist.
    """
    try:
        spex_root = Path(get_spex_root(workdir, auto_init=False))
    except (SystemExit, RuntimeError):
        return False
    return (
        (spex_root / "specs").is_dir()
        and (spex_root / "archives").is_dir()
        and (spex_root / "hooks").is_dir()
        and (spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR).is_dir()
    )


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


_DEFAULT_TOML = 'spex_root = ".spex"\n'


def _create_toml_config(repo_root=None):
    """Create .spex.toml at the appropriate location."""
    if repo_root is not None:
        target = repo_root / ".spex.toml"
    else:
        target = Path.home() / ".spex" / "config.toml"
        target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        print(f"Config already exists: {target}")
        return

    target.write_text(_DEFAULT_TOML, encoding="utf-8")
    print(f"Created: {target}")


def run_init(workdir=None):
    """Run full spex initialization."""
    if workdir is None:
        workdir = get_current_workdir()

    repo_root = Path(get_current_workdir()) if get_current_workdir() else None

    _install_deps()
    ensure_initialized(get_spex_root(workdir))
    _install_cli()
    _create_toml_config(repo_root)

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
