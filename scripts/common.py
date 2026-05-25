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
DEFAULT_SPECS_ROOT_DIR = ".specs"
TEMPLATE_DIR = "templates"
BUILTIN_TEMPLATE_DIR = "builtin"

_spec_root_cache: dict[str | None, str] = {}


def clear_specs_root_cache():
    """Clear the spec_root cache. Useful for testing."""
    _spec_root_cache.clear()


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


def _ensure_repo_specs_dir(repo_root: Path, specs_dir: str):
    """Create specs_root directory if not exists and add to .gitignore.

    Called only from the fallback branch (case 3) of get_specs_root().
    """
    specs_path = repo_root / Path(specs_dir)
    if not specs_path.exists():
        specs_path.mkdir(parents=True, exist_ok=True)
        # Add trailing slash for directory entry in .gitignore
        gitignore_entry = specs_dir.rstrip("/") + "/"
        _ensure_gitignore(repo_root, gitignore_entry)


def get_specs_root(workdir=None):
    """Return the spec root directory path.

    Resolution order:
    1. Environment variable SPECS_ROOT.
    2. Git config key specs.rootdir.
    3. Default: .specs inside the git toplevel.

    Args:
        workdir: The working directory for git lookup. Defaults to cwd.

    Returns:
        Absolute path to the spec root directory.
    """
    cache_key = workdir
    if cache_key in _spec_root_cache:
        return _spec_root_cache[cache_key]

    # 1. Check environment variable
    env_root = os.environ.get("SPECS_ROOT")
    if env_root:
        specs_root = str(Path(env_root).resolve())
        _spec_root_cache[cache_key] = specs_root
        return specs_root

    # 2. Check git config
    cmd = ["git", "config", "--get", "specs.rootdir"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=workdir
    )
    if result.returncode == 0 and result.stdout.strip():
        git_root = result.stdout.strip()
        specs_root = str(Path(git_root).resolve())
        _spec_root_cache[cache_key] = specs_root
        return specs_root

    # 3. Fallback: compute from git toplevel
    cmd = ["git", "rev-parse", "--show-toplevel"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=workdir
    )
    if result.returncode != 0:
        raise RuntimeError("Not inside a git repository")

    repo_root = Path(result.stdout.strip()).resolve()
    specs_root = str(repo_root / DEFAULT_SPECS_ROOT_DIR)
    _ensure_repo_specs_dir(repo_root, DEFAULT_SPECS_ROOT_DIR)
    _spec_root_cache[cache_key] = specs_root
    return specs_root


def get_specs_dir(workdir=None):
    """Return the specs directory: <spec_root>/specs/."""
    return str(Path(get_specs_root(workdir)) / "specs")


def get_archives_dir(workdir=None):
    """Return the archives directory: <spec_root>/archives/."""
    return str(Path(get_specs_root(workdir)) / "archives")


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
    """Sync a built-in template to specs_path/templates/builtin/ if version differs.

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

    specs_root = Path(get_specs_root(workdir))
    builtin_dir = specs_root / TEMPLATE_DIR / BUILTIN_TEMPLATE_DIR
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
    1. Sync built-in template to <specs_root>/templates/builtin/ if needed.
    2. If <specs_root>/templates/<name> exists (user custom), return its content.
    3. Otherwise return <specs_root>/templates/builtin/<name> content.

    The returned content has YAML front-matter stripped.

    Args:
        template_name: Template filename (e.g. "spec.md").
        workdir: Working directory for git lookup.

    Returns:
        Template content as a string (without front-matter).
    """
    _sync_builtin_template(template_name, workdir)

    specs_root = Path(get_specs_root(workdir))
    custom = specs_root / TEMPLATE_DIR / template_name
    builtin = specs_root / TEMPLATE_DIR / BUILTIN_TEMPLATE_DIR / template_name

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
    print(get_specs_root())
