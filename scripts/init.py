#!/usr/bin/env python3
"""Initialize the spex environment."""

import subprocess
import sys
from pathlib import Path

from common import (
    EXAMPLES_TEMPLATE_DIR,
    TEMPLATE_DIR,
    get_current_workdir,
    get_spex_root,
)


def _get_skill_dir():
    return Path(__file__).resolve().parent.parent


def is_initialized(workdir=None):
    """Check if spex environment is initialized.

    Returns True if specs_dir, archives_dir, and templates/examples/ all exist.
    """
    try:
        spex_root = Path(get_spex_root(workdir))
    except SystemExit:
        return False
    return (
        (spex_root / "specs").is_dir()
        and (spex_root / "archives").is_dir()
        and (spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR).is_dir()
    )


def _install_deps():
    """Install Python dependencies from the skill's pyproject.toml."""
    skill_dir = _get_skill_dir()
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


def _sync_templates(spex_root):
    """Sync all built-in templates to spex_root/templates/examples/."""
    import shutil

    skill_dir = _get_skill_dir()
    source_dir = skill_dir / TEMPLATE_DIR
    if not source_dir.is_dir():
        return

    examples_dir = Path(spex_root) / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
    examples_dir.mkdir(parents=True, exist_ok=True)

    for src_file in source_dir.iterdir():
        if src_file.is_file() and src_file.suffix == ".md":
            shutil.copy2(src_file, examples_dir / src_file.name)

    print(f"Synced templates to {examples_dir}")


def _install_cli():
    """Install spex CLI symlink to ~/.local/bin."""
    import shutil as _shutil

    script_path = _get_skill_dir() / "scripts" / "spex"
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


def _ensure_gitignore(spex_root):
    """Create .gitignore files inside spex_root to ignore generated content."""
    spex_root_path = Path(spex_root).resolve()

    root_gitignore = spex_root_path / ".gitignore"
    if not root_gitignore.exists():
        root_gitignore.write_text("/specs/\n/archives/\n")

    templates_dir = spex_root_path / TEMPLATE_DIR
    templates_dir.mkdir(parents=True, exist_ok=True)
    tpl_gitignore = templates_dir / ".gitignore"
    if not tpl_gitignore.exists():
        tpl_gitignore.write_text("/examples/\n")


def run_init(workdir=None):
    """Run full spex initialization."""
    if workdir is None:
        workdir = get_current_workdir()

    _install_deps()

    spex_root = get_spex_root(workdir)
    spex_root_path = Path(spex_root)
    spex_root_path.mkdir(parents=True, exist_ok=True)
    (spex_root_path / "specs").mkdir(exist_ok=True)
    (spex_root_path / "archives").mkdir(exist_ok=True)

    _sync_templates(spex_root)
    _install_cli()
    _ensure_gitignore(spex_root)

    print("Initialization complete.")


_USAGE = """\
Usage: spex init [--check]

Initialize the spex environment.

Options:
  --check     Check if initialized (exit 0 = yes, exit 1 = no)
  -h, --help  Show this help message and exit
"""


def main():
    from common import check_help_flag

    check_help_flag(_USAGE)

    args = sys.argv[2:] if len(sys.argv) > 2 else sys.argv[1:]

    if "--check" in args:
        sys.exit(0 if is_initialized() else 1)

    run_init()


if __name__ == "__main__":
    main()
