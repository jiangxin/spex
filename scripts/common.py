#!/usr/bin/env python3
"""Shared utilities for the Spex skill."""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TODO_FILE = "todo.json"
META_FILE = "meta.json"
DEFAULT_SPEX_ROOT_DIR = ".spex"
TEMPLATE_DIR = "templates"
EXAMPLES_TEMPLATE_DIR = "examples"

_spex_root_cache: dict[str | None, str] = {}


def check_help_flag(usage_text):
    """If -h or --help is in sys.argv, print usage and exit."""
    if "-h" in sys.argv or "--help" in sys.argv:
        print(usage_text, end="")
        sys.exit(0)


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


def _resolve_spex_path(value: str, repo_root) -> str:
    """Resolve a spex_root path value to an absolute path.

    - ~/... paths are expanded to the user's home directory.
    - Relative paths resolve from repo_root (if in a git repo) or cwd.
    - Absolute paths are returned as-is.
    """
    p = Path(value).expanduser()
    if not p.is_absolute():
        base = repo_root if repo_root is not None else Path.cwd()
        p = base / p
    return str(p.resolve())


def _read_spex_root_from_yaml(path: Path, repo_root=None):
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
                return _resolve_spex_path(value, repo_root)
    return None


def _find_spex_yaml(repo_root):
    """Search for .spex.yaml config and return spex_root value or None.

    Search order:
    1. <repo_root>/.spex.yaml (if repo_root is not None)
    2. ~/.config/spex/config.yaml
    3. ~/.spex.yaml
    """
    if repo_root is not None:
        value = _read_spex_root_from_yaml(repo_root / ".spex.yaml", repo_root)
        if value:
            return value

    xdg_config = Path.home() / ".config" / "spex" / "config.yaml"
    value = _read_spex_root_from_yaml(xdg_config, repo_root)
    if value:
        return value

    home_config = Path.home() / ".spex.yaml"
    value = _read_spex_root_from_yaml(home_config, repo_root)
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
        repo_root = _get_repo_root(workdir)
        spex_root = _resolve_spex_path(env_root, repo_root)
        _spex_root_cache[cache_key] = spex_root
        if require_git and repo_root is None:
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


def get_current_workdir():
    """Return the current git toplevel path, or None if not in a repo."""
    repo_root = _get_repo_root()
    return str(repo_root) if repo_root else None


def same_path(a: str, b: str) -> bool:
    """Return True if two path strings refer to the same filesystem location."""
    return Path(a).resolve() == Path(b).resolve()


def load_meta(topic_dir: Path):
    """Load meta.json from a topic directory.

    Returns the parsed dict, or None if missing/invalid.
    """
    meta_path = topic_dir / META_FILE
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def get_topic_workdir(topic_dir: Path) -> str:
    """Read workdir from meta.json in a topic directory.

    Returns the workdir string, or empty string if not found.
    """
    data = load_meta(topic_dir)
    if data is None:
        return ""
    return data.get("workdir", "")


def load_todo(topic_dir: Path):
    """Load todo.json from a topic directory.

    Returns the parsed list, or None if missing/invalid/empty.
    """
    todo_path = topic_dir / TODO_FILE
    if not todo_path.is_file():
        return None
    try:
        data = json.loads(todo_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, list) or len(data) == 0:
        return None
    return data


def is_topic_completed(topic_dir: Path) -> bool:
    """Return True if all tasks in todo.json have non-empty completed_at."""
    data = load_todo(topic_dir)
    if data is None:
        return False
    return all(
        isinstance(item, dict) and item.get("completed_at")
        for item in data
    )


def has_undone_tasks(topic_dir: Path) -> bool:
    """Return True if the topic's todo.json has incomplete items."""
    data = load_todo(topic_dir)
    if data is None:
        return False
    return any(
        isinstance(item, dict) and not item.get("completed_at")
        for item in data
    )


def get_todo_progress(topic_dir: Path) -> tuple:
    """Return (completed_count, total_count) from todo.json."""
    data = load_todo(topic_dir)
    if data is None:
        return (0, 0)
    total = len(data)
    done = sum(
        1 for item in data
        if isinstance(item, dict) and item.get("completed_at")
    )
    return (done, total)


def atomic_write_json(path: Path, data) -> None:
    """Atomically write JSON data to a file using tempfile + os.replace."""
    import tempfile

    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp_fd = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        suffix=".tmp",
        delete=False,
    )
    try:
        tmp_fd.write(content)
        tmp_fd.close()
        os.replace(tmp_fd.name, str(path))
    except BaseException:
        tmp_fd.close()
        if os.path.exists(tmp_fd.name):
            os.unlink(tmp_fd.name)
        raise


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


def strip_front_matter(content: str) -> str:
    """Remove YAML front-matter from template content."""
    stripped = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)
    return stripped.lstrip("\n")


def _sync_builtin_template(template_name: str, workdir=None):
    """Sync a built-in template to spex_root/templates/examples/ if version differs.

    Compares the version in the skill's source template against the local
    examples copy. If they differ (or local copy is missing), overwrites the
    local examples copy.
    """
    skill_path = _get_skill_path()
    source = skill_path / TEMPLATE_DIR / template_name
    if not source.exists():
        raise FileNotFoundError(
            f"Built-in template not found at {source}"
        )

    spex_root = Path(get_spex_root(workdir))
    examples_dir = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
    target = examples_dir / template_name

    source_version = _extract_template_version(source)
    target_version = _extract_template_version(target)

    if source_version and source_version == target_version:
        return  # Already up-to-date

    examples_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def get_template(template_name: str, workdir=None) -> str:
    """Return raw template content for the given template name.

    Workflow:
    1. Sync built-in template to <spex_root>/templates/examples/ if needed.
    2. If <spex_root>/templates/<name> exists (user custom), return its content.
    3. Otherwise return the built-in template from the skill's source.

    The returned content includes YAML front-matter. Use strip_front_matter()
    to remove it after rendering.

    Args:
        template_name: Template filename (e.g. "spec-template.md").
        workdir: Working directory for git lookup.

    Returns:
        Template content as a string (with front-matter intact).
    """
    _sync_builtin_template(template_name, workdir)

    spex_root = Path(get_spex_root(workdir))
    custom = spex_root / TEMPLATE_DIR / template_name

    if custom.exists():
        return custom.read_text(encoding="utf-8")

    skill_path = _get_skill_path()
    source = skill_path / TEMPLATE_DIR / template_name
    return source.read_text(encoding="utf-8")



if __name__ == "__main__":
    print(get_spex_root())
