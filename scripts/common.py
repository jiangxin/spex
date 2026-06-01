#!/usr/bin/env python3
"""Shared utilities for the Spex skill."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import (
    clear_config_cache,
    generate_default_toml,
    get_context,
)
from config import (
    get_top_workdir as _cfg_get_top_workdir,
)

TODO_FILE = "todo.json"
META_FILE = "meta.json"
DEFAULT_SPEX_BRANCH_PREFIX = "spex/"
TEMPLATE_DIR = "templates"
EXAMPLES_TEMPLATE_DIR = "examples"

ICON_COMPLETED = "✅"
ICON_IN_PROGRESS = "\U0001f527"
ICON_ARCHIVED = "\U0001f4e6"

def _create_default_toml():
    """Create ~/.spex.toml with default content."""
    target = Path.home() / ".spex.toml"
    target.write_text(generate_default_toml(), encoding="utf-8")




def check_help_flag(usage_text, argv=None):
    """If -h or --help is in argv, print usage and exit."""
    if argv is None:
        argv = sys.argv
    if "-h" in argv or "--help" in argv:
        print(usage_text, end="")
        sys.exit(0)


def clear_spex_root_cache():
    """Clear the spex_root configuration cache. Useful for testing."""
    clear_config_cache()


def _sync_all_templates(spex_root_path: Path, verbose=False):
    """Sync all built-in templates to spex_root/templates/examples/.

    Iterates every .md file in the skill's templates/ directory and calls
    _sync_builtin_template to copy (if missing) or overwrite (if outdated).
    """
    skill_path = _get_skill_path()
    source_dir = skill_path / TEMPLATE_DIR
    if not source_dir.is_dir():
        return
    for src in source_dir.iterdir():
        if src.is_file() and src.suffix == ".md":
            _sync_builtin_template(
                src.name, spex_root=spex_root_path, verbose=verbose,
            )


def _write_internal_gitignore(spex_root_path: Path, verbose=False):
    """Create .gitignore files inside spex_root to ignore generated content."""
    root_gi = spex_root_path / ".gitignore"
    if not root_gi.exists():
        root_gi.write_text("/specs/\n/archives/\n")
        if verbose:
            print(f"  Created: {root_gi}")
    tpl_dir = spex_root_path / TEMPLATE_DIR
    tpl_dir.mkdir(parents=True, exist_ok=True)
    tpl_gi = tpl_dir / ".gitignore"
    if not tpl_gi.exists():
        tpl_gi.write_text("/examples/\n")
        if verbose:
            print(f"  Created: {tpl_gi}")


def _resolve_hook_roots(workdir=None):
    """Return hook root paths in priority order (highest first).

    Builds from all resolved spex_roots: <spex_root>/hooks/ for each.
    """
    ctx = get_context(workdir)
    return [Path(sr) / "hooks" for sr in ctx.spex_roots]


def ensure_initialized(spex_root, verbose=False):
    """Ensure spex_root directory structure is initialized."""
    spex_root_path = Path(spex_root)
    if (spex_root_path / "specs").is_dir():
        if verbose:
            print(f"Already initialized: {spex_root_path}")
        return
    if verbose:
        print(f"Initializing: {spex_root_path}")
    spex_root_path.mkdir(parents=True, exist_ok=True)
    for subdir in ("specs", "archives", "hooks"):
        (spex_root_path / subdir).mkdir(exist_ok=True)
        if verbose:
            print(f"  Created: {spex_root_path / subdir}/")
    _sync_all_templates(spex_root_path, verbose=verbose)
    _write_internal_gitignore(spex_root_path, verbose=verbose)


def get_spex_root(workdir=None, require_git=False, auto_init=True):
    """Return the spex root directory path.

    Resolution order (delegated to config.get_context):
      1. Merged .spex.toml files (repo-root/.spex.toml, parent dirs,
         ~/.spex.toml).
      2. Default: .spex inside the git toplevel.
      3. Default: .spex inside the git toplevel.

    Args:
        workdir: The working directory for git lookup. Defaults to cwd.
        require_git: If True, raise when not inside a git worktree even if
            spex_root was resolved via env/config. Used by commands that
            need a git context (apply, create, modify).
        auto_init: If True (default), auto-initialize the directory structure.

    Returns:
        Absolute path to the spex root directory.
    """
    ctx = get_context(workdir)

    if auto_init and not ctx.spex_tomls:
        _create_default_toml()
        clear_config_cache()
        ctx = get_context(workdir)

    if not ctx.spex_root:
        raise RuntimeError(
            "Cannot determine spex_root. "
            "Configure .spex.toml with spex_root."
        )

    if require_git and ctx.main_worktree is None:
        raise RuntimeError("Not inside a git repository")
    if auto_init:
        ensure_initialized(ctx.spex_root)
    return ctx.spex_root


def get_spex_roots(workdir=None) -> list[str]:
    """Return all resolved spex root directories (highest priority first)."""
    return get_context(workdir).spex_roots


def get_spex_tomls(workdir=None) -> list[str]:
    """Return discovered .spex.toml config paths as strings."""
    return [str(p) for p in get_context(workdir).spex_tomls]


def get_specs_dir(workdir=None) -> Path:
    """Return the specs directory: <spex_root>/specs/."""
    return Path(get_spex_root(workdir)) / "specs"


def get_archives_dir(workdir=None) -> Path:
    """Return the archives directory: <spex_root>/archives/."""
    return Path(get_spex_root(workdir)) / "archives"


def get_current_workdir():
    """Return the current git toplevel path, or None if not in a repo."""
    root = _cfg_get_top_workdir()
    return str(root) if root else None


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


def load_and_validate_todo_json(path, allow_empty=False):
    """Load a JSON file, validate it is a list, return data.

    Args:
        path: Path to the JSON file.
        allow_empty: If False (default), exit on empty list.

    Returns:
        Parsed list data.

    Exits with code 1 on: file not found, invalid JSON, non-list data,
    or empty list (when allow_empty is False).
    """
    path = Path(path)
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print("Error: top-level value must be an array.", file=sys.stderr)
        sys.exit(1)

    if not allow_empty and not data:
        print("Error: empty array, nothing to process.", file=sys.stderr)
        sys.exit(1)

    return data


def validate_unique_ids(data):
    """Check all items have unique non-empty 'id' fields.

    Args:
        data: List of dicts, each expected to have an 'id' key.

    Exits with code 1 if any item is not a dict, or if any id is
    empty or duplicated.
    """
    seen_ids = {}
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            print(f"Error: item[{i}] is not an object.", file=sys.stderr)
            sys.exit(1)
        step_id = item.get("id", "")
        if not step_id:
            print(
                f"Error: item[{i}]: 'id' is missing or empty.",
                file=sys.stderr,
            )
            sys.exit(1)
        if step_id in seen_ids:
            print(
                f"Error: item[{i}]: duplicate id '{step_id}'"
                f" (first seen at item[{seen_ids[step_id]}]).",
                file=sys.stderr,
            )
            sys.exit(1)
        seen_ids[step_id] = i


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


def strip_date_prefix(topic_name: str) -> str:
    """Remove the YYYY-MM-DD-HH-MM- datetime prefix from a topic name."""
    return re.sub(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-", "", topic_name)


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


def parse_front_matter_description(content: str) -> str:
    """Extract description from YAML front-matter.

    Handles single-line, quoted, and block scalar (|, >) formats.
    Returns the description as a single line (multi-line joined with spaces),
    or empty string if not found.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return ""

    lines = match.group(1).splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"description:\s*(.*)", line)
        if not m:
            continue
        value = m.group(1).strip()
        if not value or value in ("|", ">"):
            # Block scalar: collect indented continuation lines
            parts = []
            for cont_line in lines[i + 1:]:
                if cont_line and (cont_line[0] == " " or cont_line[0] == "\t"):
                    parts.append(cont_line.strip())
                else:
                    break
            return " ".join(parts)
        # Single-line value (strip surrounding quotes)
        return value.strip("\"'")
    return ""


def get_spec_description(topic_dir: Path) -> str:
    """Return the topic's description.

    Reads from meta.json first (authoritative source). Falls back to
    spec.md front-matter description for backwards compatibility.
    """
    meta = load_meta(topic_dir)
    if meta and meta.get("description"):
        return meta["description"]

    spec_path = topic_dir / "spec.md"
    if not spec_path.is_file():
        return ""
    try:
        content = spec_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return parse_front_matter_description(content)


def _sync_builtin_template(
    template_name: str, workdir=None, spex_root=None, verbose=False,
):
    """Sync a built-in template to spex_root/templates/examples/ if version differs.

    If the target file does not exist, copy it directly.
    If it exists:
    - mtime+size differ → overwrite
    - mtime+size match → compare versions; same version skip, else overwrite
    """
    skill_path = _get_skill_path()
    source = skill_path / TEMPLATE_DIR / template_name
    if not source.exists():
        raise FileNotFoundError(
            f"Built-in template not found at {source}"
        )

    if spex_root is None:
        spex_root = Path(get_spex_root(workdir))
    else:
        spex_root = Path(spex_root)
    examples_dir = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
    target = examples_dir / template_name

    if not target.exists():
        examples_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if verbose:
            print(f"  Synced template: {template_name}")
        return

    src_stat = source.stat()
    tgt_stat = target.stat()
    if (tgt_stat.st_mtime != src_stat.st_mtime
            or tgt_stat.st_size != src_stat.st_size):
        shutil.copy2(source, target)
        if verbose:
            print(f"  Updated template: {template_name}")
        return

    source_version = _extract_template_version(source)
    target_version = _extract_template_version(target)
    if source_version and source_version == target_version:
        if verbose:
            print(f"  Template up-to-date: {template_name}")
        return

    shutil.copy2(source, target)
    if verbose:
        print(f"  Updated template: {template_name}")


def _resolve_template_roots(workdir=None):
    """Return template root paths in priority order (highest first).

    Builds from all resolved spex_roots: <spex_root>/templates/ for each,
    then appends the skill's built-in templates directory last.
    """
    ctx = get_context(workdir)
    roots = [Path(sr) / TEMPLATE_DIR for sr in ctx.spex_roots]
    roots.append(_get_skill_path() / TEMPLATE_DIR)
    return roots


def get_template(template_name: str, workdir=None) -> str:
    """Return raw template content for the given template name.

    Workflow:
    1. Sync built-in template to <spex_root>/templates/examples/ if needed.
    2. Search template roots in priority order (derived from spex_roots):
       a. <spex_root>/templates/ for each discovered spex_root
       b. <skill_path>/templates/ (built-in fallback)
    3. Return content of the first matching file.

    The returned content includes YAML front-matter. Use strip_front_matter()
    to remove it after rendering.

    Args:
        template_name: Template filename (e.g. "spec-template.md").
        workdir: Working directory for git lookup.

    Returns:
        Template content as a string (with front-matter intact).

    Raises:
        FileNotFoundError: If the template is not found in any root.
    """
    _sync_builtin_template(template_name, workdir)

    for root in _resolve_template_roots(workdir):
        candidate = root / template_name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")

    raise FileNotFoundError(
        f"Template '{template_name}' not found in any template root"
    )



def find_matching_topics(topic_name, specs_dir):
    """Find topic directories matching a name or substring.

    Tries exact match first; if found, returns a single-element list.
    Otherwise returns all directories whose name contains topic_name
    as a substring, sorted alphabetically.

    Args:
        topic_name: Topic name or substring to match.
        specs_dir: Path to the specs directory.

    Returns:
        List of Path objects for matching topic directories.
    """
    specs_dir = Path(specs_dir)
    if not specs_dir.is_dir():
        return []

    direct = specs_dir / topic_name
    if direct.is_dir():
        return [direct]

    return sorted(
        d for d in specs_dir.iterdir() if d.is_dir() and topic_name in d.name
    )


def resolve_topic_dir(topic_name, specs_dir=None):
    """Resolve a topic name to its directory path.

    Tries exact match first, then fuzzy substring match against directory
    names in specs_dir. Exits with an error if no match or multiple matches.

    Args:
        topic_name: Topic name or substring to match.
        specs_dir: Path to the specs directory. If None, computed via
            get_specs_dir(get_current_workdir()).

    Returns:
        Path to the resolved topic directory.
    """
    if specs_dir is None:
        specs_dir = get_specs_dir(get_current_workdir())
    else:
        specs_dir = Path(specs_dir)

    if not specs_dir.is_dir():
        print(f"Error: specs directory does not exist: {specs_dir}", file=sys.stderr)
        sys.exit(1)

    matches = find_matching_topics(topic_name, specs_dir)
    if not matches:
        print(f"Error: no topic matching '{topic_name}' found.", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        names = "\n  ".join(m.name for m in matches)
        print(
            f"Error: multiple topics match '{topic_name}':\n  {names}",
            file=sys.stderr,
        )
        sys.exit(1)
    return matches[0]


def format_topic(topic_dir: Path, verbose: int = 0) -> str:
    """Format a single topic with progress, description, and optional todo steps.

    Verbosity levels:
        0: Icon + progress + name only.
        1: + description line.
        2: + todo step list (id + name).
    """
    done, total = get_todo_progress(topic_dir)
    icon = ICON_COMPLETED if done > 0 and done == total else ICON_IN_PROGRESS

    lines = [f"{icon} [{done}/{total}] {topic_dir.name}"]

    if verbose >= 1:
        description = get_spec_description(topic_dir)
        if description:
            lines.append(f"    {description}")

    if verbose >= 2:
        todo = load_todo(topic_dir)
        if todo:
            lines.append("")
            for item in todo:
                step_id = item.get("id", "")
                step_name = item.get("name", "")
                lines.append(f"    {step_id}: {step_name}")

    return "\n".join(lines)


def get_git_info():
    """Retrieve git repository metadata via subprocess calls."""
    commands = {
        "workdir": ["git", "rev-parse", "--show-toplevel"],
        "remote_url": ["git", "remote", "get-url", "origin"],
        "branch": ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        "user_name": ["git", "config", "user.name"],
        "user_email": ["git", "config", "user.email"],
    }
    info = {}
    for key, cmd in commands.items():
        result = subprocess.run(cmd, capture_output=True, text=True)
        info[key] = result.stdout.strip() if result.returncode == 0 else ""
    return info


def escape_xml_text(text: str) -> str:
    """Escape &, <, > unconditionally in text content."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def escape_xml_preserving_entities(text: str) -> str:
    """Escape unescaped XML special characters, preserving existing entities.

    Replaces &, <, > with their entity equivalents, but skips characters
    that are already part of a valid XML entity (e.g. &lt;, &amp;).
    Use this when preprocessing user-written XML that may already contain
    entity references.
    """
    parts = re.split(r"(&(?:lt|gt|amp|quot|apos);)", text)
    result = []
    for part in parts:
        if re.match(r"&(?:lt|gt|amp|quot|apos);", part):
            result.append(part)
        else:
            result.append(escape_xml_text(part))
    return "".join(result)


def filter_completed_todos(data):
    """Filter a list of todo dicts, returning only completed ones.

    Args:
        data: List of todo item dicts.

    Returns:
        List of only the completed items.
    """
    return [
        item for item in data
        if isinstance(item, dict) and item.get("completed_at")
    ]


if __name__ == "__main__":
    print(get_spex_root())
