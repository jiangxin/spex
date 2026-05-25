#!/usr/bin/env python3
"""Shared utilities for the Spex skill."""

import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

SPEC_FILE = "spec.md"
TODO_FILE = "todo.json"
DEFAULT_SPEX_ROOT_DIR = ".spex"
TEMPLATE_DIR = "templates"
BUILTIN_TEMPLATE_DIR = "builtin"

_spex_root_cache: dict[str | None, str] = {}


def clear_spex_root_cache():
    """Clear the spex_root cache. Useful for testing."""
    _spex_root_cache.clear()


def _ensure_gitignore(repo_root: Path, entry: str):
    """Ensure entry is listed in .gitignore.

    Uses git check-ignore to check if entry is already ignored.
    If not, appends it to .gitignore.
    """
    # Check if entry is already ignored using git check-ignore
    result = subprocess.run(
        ["git", "check-ignore", "-q", entry],
        cwd=repo_root,
        capture_output=True
    )
    if result.returncode == 0:
        # Entry is already ignored
        return

    # Entry is not ignored, add it to .gitignore
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if content and not content.endswith("\n"):
            content += "\n"
        content += entry + "\n"
        gitignore.write_text(content)
    else:
        gitignore.write_text(entry + "\n")


def _ensure_repo_spex_dir(repo_root: Path, spex_dir: str):
    """Create spex_root directory if not exists and add to .gitignore.

    Called only from the fallback branch (case 3) of get_spex_root().
    """
    spex_path = repo_root / Path(spex_dir)
    if not spex_path.exists():
        spex_path.mkdir(parents=True, exist_ok=True)
        gitignore_entry = spex_dir.rstrip("/") + "/"
        _ensure_gitignore(repo_root, gitignore_entry)


def _get_repo_root(workdir=None):
    """Return the git repository root, or None if not in a repo."""
    cmd = ["git", "rev-parse", "--show-toplevel"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=workdir
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _read_spex_root_from_yaml(path: Path):
    """Read spex_root value from a YAML config file. Returns None if not found.

    Only supports simple "key: value" lines (no nested structures).
    """
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"spex_root\s*:\s*(.+)", line)
        if m:
            value = m.group(1).strip().strip("\"'")
            if value:
                return str(Path(value).expanduser().resolve())
    return None


def _find_spex_yaml(repo_root):
    """Search for .spex.yaml config and return spex_root value or None.

    Search order:
    1. <repo_root>/.spex.yaml (if repo_root is not None)
    2. ~/.config/spex/config.yaml
    3. ~/.spex.yaml
    """
    if repo_root is not None:
        value = _read_spex_root_from_yaml(repo_root / ".spex.yaml")
        if value:
            return value

    xdg_config = Path.home() / ".config" / "spex" / "config.yaml"
    value = _read_spex_root_from_yaml(xdg_config)
    if value:
        return value

    home_config = Path.home() / ".spex.yaml"
    value = _read_spex_root_from_yaml(home_config)
    if value:
        return value

    return None


def get_spex_root(workdir=None, require_git=False):
    """Return the spex root directory path.

    Resolution order:
    1. Environment variable SPEX_ROOT.
    2. .spex.yaml config file (repo root, ~/.config/spex/, ~/.spex.yaml).
    3. Default: .spex inside the git toplevel.

    Args:
        workdir: The working directory for git lookup. Defaults to cwd.
        require_git: If True, raise when not inside a git worktree even if
            spex_root was resolved via env/config. Used by commands that
            need a git context (apply, create, modify).

    Returns:
        Absolute path to the spex root directory.
    """
    cache_key = workdir
    if cache_key in _spex_root_cache:
        spex_root = _spex_root_cache[cache_key]
        if require_git and _get_repo_root(workdir) is None:
            raise RuntimeError("Not inside a git repository")
        return spex_root

    # 1. Check environment variable
    env_root = os.environ.get("SPEX_ROOT")
    if env_root:
        spex_root = str(Path(env_root).resolve())
        _spex_root_cache[cache_key] = spex_root
        if require_git and _get_repo_root(workdir) is None:
            raise RuntimeError("Not inside a git repository")
        return spex_root

    # 2. Check .spex.yaml config files
    repo_root = _get_repo_root(workdir)
    yaml_root = _find_spex_yaml(repo_root)
    if yaml_root:
        _spex_root_cache[cache_key] = yaml_root
        if require_git and repo_root is None:
            raise RuntimeError("Not inside a git repository")
        return yaml_root

    # 3. Fallback: .spex inside the git toplevel
    if repo_root is None:
        raise RuntimeError(
            "Cannot determine spex_root. "
            "Set SPEX_ROOT, use --spex-root, or configure .spex.yaml."
        )

    spex_root = str(repo_root / DEFAULT_SPEX_ROOT_DIR)
    _ensure_repo_spex_dir(repo_root, DEFAULT_SPEX_ROOT_DIR)
    _spex_root_cache[cache_key] = spex_root
    return spex_root


def get_specs_dir(workdir=None):
    """Return the specs directory: <spex_root>/specs/."""
    return str(Path(get_spex_root(workdir)) / "specs")


def get_archives_dir(workdir=None):
    """Return the archives directory: <spex_root>/archives/."""
    return str(Path(get_spex_root(workdir)) / "archives")


def local_iso_timestamp() -> str:
    """Return current local time as ISO 8601 with timezone offset."""
    now = datetime.now().astimezone()
    base = now.strftime("%Y-%m-%dT%H:%M:%S")
    offset = now.strftime("%z")
    return f"{base}{offset[:3]}:{offset[3:]}"


def _get_skill_path() -> Path:
    """Return the skill root directory (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def _extract_template_version(path: Path) -> str:
    """Extract version from YAML front-matter of a template file.

    Returns empty string if no front-matter or no version field found.
    """
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return ""
    for line in match.group(1).splitlines():
        m = re.match(r'version:\s*["\']?([^"\']*)["\']?', line)
        if m:
            return m.group(1).strip()
    return ""


def _strip_front_matter(content: str) -> str:
    """Remove YAML front-matter from template content."""
    stripped = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)
    return stripped.lstrip("\n")


def _sync_builtin_template(template_name: str, workdir=None):
    """Sync a built-in template to spex_root/templates/builtin/ if version differs.

    Compares the version in the skill's source template against the local
    builtin copy. If they differ (or local copy is missing), overwrites the
    local builtin copy.
    """
    skill_path = _get_skill_path()
    source = skill_path / TEMPLATE_DIR / template_name
    if not source.exists():
        raise FileNotFoundError(
            f"Built-in template not found at {source}"
        )

    spex_root = Path(get_spex_root(workdir))
    builtin_dir = spex_root / TEMPLATE_DIR / BUILTIN_TEMPLATE_DIR
    target = builtin_dir / template_name

    source_version = _extract_template_version(source)
    target_version = _extract_template_version(target)

    if source_version and source_version == target_version:
        return  # Already up-to-date

    builtin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def get_template(template_name: str, workdir=None) -> str:
    """Return template content for the given template name.

    Workflow:
    1. Sync built-in template to <spex_root>/templates/builtin/ if needed.
    2. If <spex_root>/templates/<name> exists (user custom), return its content.
    3. Otherwise return <spex_root>/templates/builtin/<name> content.

    The returned content has YAML front-matter stripped.

    Args:
        template_name: Template filename (e.g. "spec.md").
        workdir: Working directory for git lookup.

    Returns:
        Template content as a string (without front-matter).
    """
    _sync_builtin_template(template_name, workdir)

    spex_root = Path(get_spex_root(workdir))
    custom = spex_root / TEMPLATE_DIR / template_name
    builtin = spex_root / TEMPLATE_DIR / BUILTIN_TEMPLATE_DIR / template_name

    if custom.exists():
        content = custom.read_text(encoding="utf-8")
    else:
        content = builtin.read_text(encoding="utf-8")

    return _strip_front_matter(content)


def get_spec_template(workdir=None) -> str:
    """Return spec template content.

    Convenience wrapper around get_template() for the spec template.
    """
    return get_template(SPEC_FILE, workdir)


if __name__ == "__main__":
    print(get_spex_root())
