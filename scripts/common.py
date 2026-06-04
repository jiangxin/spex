#!/usr/bin/env python3
"""Shared utilities for the Spex skill."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path

from config import (
    clear_config_cache,
    generate_default_toml,
    get_project_context,
)

TODO_FILE = "todo.json"
META_FILE = "meta.json"
DEFAULT_SPEX_BRANCH_PREFIX = "spex/"
TEMPLATE_DIR = "templates"
EXAMPLES_TEMPLATE_DIR = "examples"

ICON_COMPLETED = "✅"
ICON_IN_PROGRESS = "\U0001f527"
ICON_ARCHIVED = "\U0001f4e6"

# Field names for TopicMeta serialization order.
_TOPIC_META_FIELD_ORDER = [
    "topic", "workdir", "main_worktree", "remote_url", "branch",
    "user_name", "user_email", "created_at", "prompts", "description",
    "spex_branch",
]


@dataclass
class TopicMeta:
    """Typed representation of a topic's meta.json."""

    topic: str = ""
    workdir: str = ""
    main_worktree: str = ""
    remote_url: str = ""
    branch: str = ""
    user_name: str = ""
    user_email: str = ""
    created_at: str = ""
    prompts: list = field(default_factory=list)
    description: str = ""
    spex_branch: str = ""
    extras: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> TopicMeta:
        """Create a TopicMeta from a dict, capturing unknown keys in extras."""
        known = {f.name for f in fields(cls)} - {"extras"}
        kwargs = {k: v for k, v in data.items() if k in known}
        extras = {k: v for k, v in data.items() if k not in known}
        return cls(**kwargs, extras=extras)

    def to_dict(self) -> dict:
        """Serialize to dict in fixed order, omitting empty optional fields."""
        result: dict = {}
        for key in _TOPIC_META_FIELD_ORDER:
            value = getattr(self, key)
            # Omit description and spex_branch when empty
            if key in ("description", "spex_branch") and not value:
                continue
            result[key] = value
        # Merge extras (never include the "extras" key itself)
        result.update(self.extras)
        return result


def normalize_prompt_entry(entry):
    """Normalize a prompt entry to a structured dict.

    If *entry* is a plain string (old format), returns ``{"text": entry}``.
    Otherwise returns *entry* as-is (already structured).
    """
    if isinstance(entry, str):
        return {"text": entry}
    return entry


@dataclass
class Topic:
    """In-memory representation of a topic for display."""

    name: str
    path: Path
    meta: TopicMeta
    done: int = 0
    total: int = 0
    archived: bool = False

    @classmethod
    def from_dir(cls, topic_dir: Path, *, archived: bool = False) -> Topic | None:
        """Create a Topic from a topic directory.

        Returns None if meta.json is missing or invalid.
        """
        meta = load_meta(topic_dir)
        if meta is None:
            return None
        done, total = get_todo_progress(topic_dir)
        return cls(
            name=topic_dir.name,
            path=topic_dir,
            meta=meta,
            done=done,
            total=total,
            archived=archived,
        )

    @property
    def workdir(self) -> str:
        """Delegate to meta.workdir."""
        return self.meta.workdir

    @property
    def main_worktree(self) -> str:
        return self.meta.main_worktree

    @property
    def remote_url(self) -> str:
        return self.meta.remote_url

    @property
    def branch(self) -> str:
        return self.meta.branch

    @property
    def user_name(self) -> str:
        return self.meta.user_name

    @property
    def user_email(self) -> str:
        return self.meta.user_email

    @property
    def spex_branch(self) -> str:
        return self.meta.spex_branch

    @property
    def description(self) -> str:
        """Return meta description, falling back to spec.md front-matter."""
        if self.meta.description:
            return self.meta.description
        return parse_front_matter_description(self.spec_content or "")

    @property
    def created_at(self) -> str:
        """Delegate to meta.created_at."""
        return self.meta.created_at

    @property
    def prompt(self) -> str:
        """Return first prompt text from meta, or empty string."""
        if self.meta.prompts:
            entry = normalize_prompt_entry(self.meta.prompts[0])
            return entry["text"]
        return ""

    @property
    def spec_content(self) -> str | None:
        """Read and return spec.md content, or None if missing."""
        spec_path = self.path / "spec.md"
        if not spec_path.is_file():
            return None
        try:
            return spec_path.read_text(encoding="utf-8")
        except OSError:
            return None

    @property
    def todo_data(self):
        """Delegate to load_todo(self.path)."""
        return load_todo(self.path)

    @property
    def todo_progress(self) -> tuple:
        """Return (done, total) counts."""
        return (self.done, self.total)

    @property
    def is_completed(self) -> bool:
        return self.total > 0 and self.done == self.total

    @property
    def icon(self) -> str:
        if self.archived:
            return ICON_ARCHIVED
        return ICON_COMPLETED if self.is_completed else ICON_IN_PROGRESS

    @property
    def display_text(self) -> str:
        return self.description or self.prompt


def _create_default_toml():
    """Create ~/.spex.toml with default content."""
    target = Path.home() / ".spex.toml"
    target.write_text(generate_default_toml(), encoding="utf-8")



def clear_spex_root_cache():
    """Clear the spex_root configuration cache. Useful for testing."""
    clear_config_cache()


def _sync_all_templates(spex_root_path: Path, verbose=False, dry_run=False):
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
            if dry_run:
                print(f"  Would sync template: {src.name}")
            else:
                _sync_builtin_template(
                    src.name, spex_root=spex_root_path, verbose=verbose,
                )


def _write_internal_gitignore(spex_root_path: Path, verbose=False,
                              dry_run=False):
    """Create .gitignore files inside spex_root to ignore generated content."""
    root_gi = spex_root_path / ".gitignore"
    if not root_gi.exists():
        if dry_run:
            print(f"  Would create: {root_gi}")
        else:
            root_gi.write_text("/specs/\n/archives/\n")
            if verbose:
                print(f"  Created: {root_gi}")
    tpl_dir = spex_root_path / TEMPLATE_DIR
    tpl_gi = tpl_dir / ".gitignore"
    if not dry_run:
        tpl_dir.mkdir(parents=True, exist_ok=True)
    if not tpl_gi.exists():
        if dry_run:
            print(f"  Would create: {tpl_gi}")
        else:
            tpl_gi.write_text("/examples/\n")
            if verbose:
                print(f"  Created: {tpl_gi}")


def _resolve_hook_roots(workdir=None):
    """Return hook root paths in priority order (highest first).

    Builds from all resolved spex_roots: <spex_root>/hooks/ for each.
    """
    ctx = get_project_context(workdir)
    return [Path(sr) / "hooks" for sr in ctx.spex_roots]


def ensure_initialized(spex_root, verbose=False, dry_run=False):
    """Ensure spex_root directory structure is initialized."""
    spex_root_path = Path(spex_root)
    if (spex_root_path / "specs").is_dir():
        if verbose or dry_run:
            print(f"Already initialized: {spex_root_path}")
        return
    if dry_run:
        print(f"Would initialize: {spex_root_path}")
        print(f"  Would create: {spex_root_path}/")
        for subdir in ("specs", "archives", "hooks"):
            print(f"  Would create: {spex_root_path / subdir}/")
        _sync_all_templates(spex_root_path, verbose=verbose, dry_run=True)
        _write_internal_gitignore(spex_root_path, verbose=verbose,
                                  dry_run=True)
        return
    if verbose:
        print(f"Initializing: {spex_root_path}")
    spex_root_path.mkdir(parents=True, exist_ok=True)
    if verbose:
        print(f"  Created: {spex_root_path}/")
    for subdir in ("specs", "archives", "hooks"):
        (spex_root_path / subdir).mkdir(exist_ok=True)
        if verbose:
            print(f"  Created: {spex_root_path / subdir}/")
    _sync_all_templates(spex_root_path, verbose=verbose)
    _write_internal_gitignore(spex_root_path, verbose=verbose)


def get_spex_root(workdir=None, require_git=False, auto_init=True):
    """Return the spex root directory path.

    Resolution order (delegated to config.get_project_context):
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
    ctx = get_project_context(workdir)

    if auto_init and not ctx.spex_tomls:
        _create_default_toml()
        clear_config_cache()
        ctx = get_project_context(workdir)

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
    return get_project_context(workdir).spex_roots


def get_spex_tomls(workdir=None) -> list[str]:
    """Return discovered .spex.toml config paths as strings."""
    return [str(p) for p in get_project_context(workdir).spex_tomls]


def get_specs_dir(workdir=None) -> Path:
    """Return the specs directory: <spex_root>/specs/."""
    return Path(get_spex_root(workdir)) / "specs"


def get_archives_dir(workdir=None) -> Path:
    """Return the archives directory: <spex_root>/archives/."""
    return Path(get_spex_root(workdir)) / "archives"


def same_path(a: str, b: str) -> bool:
    """Return True if two path strings refer to the same filesystem location."""
    return Path(a).resolve() == Path(b).resolve()


def load_meta(topic_dir: Path) -> TopicMeta | None:
    """Load meta.json from a topic directory.

    Returns a TopicMeta instance, or None if missing/invalid.
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
    return TopicMeta.from_dict(data)


def get_topic_workdir(topic_dir: Path) -> str:
    """Read workdir from meta.json in a topic directory.

    Returns the workdir string, or empty string if not found.
    """
    meta = load_meta(topic_dir)
    if meta is None:
        return ""
    return meta.workdir


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


def wrap_text(text: str, width: int = 68) -> str:
    """Wrap text to specified width at word boundaries.

    Joins all lines into a single line (collapsing whitespace), then
    wraps at word boundaries so no line exceeds `width` characters.
    """
    if not text or not text.strip():
        return ""
    import textwrap

    single_line = " ".join(text.split())
    return textwrap.fill(single_line, width=width, break_long_words=False)


def get_spec_description(topic_dir: Path) -> str:
    """Return the topic's description.

    Reads from meta.json first (authoritative source). Falls back to
    spec.md front-matter description for backwards compatibility.
    """
    meta = load_meta(topic_dir)
    if meta and meta.description:
        return meta.description

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
    ctx = get_project_context(workdir)
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
            get_specs_dir(get_project_context().top_workdir).

    Returns:
        Path to the resolved topic directory.
    """
    if specs_dir is None:
        ctx = get_project_context()
        specs_dir = get_specs_dir(str(ctx.top_workdir) if ctx.in_git_workdir() else None)
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


MAX_REPO_WIDTH = 11


def display_width(text: str) -> int:
    """Return the display width of text, counting wide chars as 2."""
    import unicodedata
    w = 0
    for ch in text:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def display_truncate(text: str, width: int) -> str:
    """Truncate text to fit within display width, appending ... if needed."""
    import unicodedata
    if display_width(text) <= width:
        return text
    w = 0
    for i, ch in enumerate(text):
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > width - 3:
            return text[:i] + "..."
        w += cw
    return text


def display_ljust(text: str, width: int) -> str:
    """Left-justify text to display width with space padding."""
    return text + " " * (width - display_width(text))


def repo_label(workdir: str) -> str:
    """Return truncated basename of workdir for display."""
    name = Path(workdir).name if workdir else "?"
    if display_width(name) > MAX_REPO_WIDTH:
        return display_truncate(name, MAX_REPO_WIDTH)
    return name


def format_topic(topic, verbose: int = 0, show_repo: bool = False) -> str:
    """Format a single topic with progress, description, and optional todo steps.

    Args:
        topic: A Topic instance or a Path to a topic directory.
        verbose: 0 = icon+progress+name, 1 = +description, 2 = +todo steps.
        show_repo: If True, prepend a ``[repo]`` label from the topic's workdir.
    """
    if isinstance(topic, Path):
        t = Topic.from_dir(topic)
        if t is None:
            return f"(unable to load topic: {topic.name})"
    else:
        t = topic

    progress = f"({t.done}/{t.total})"
    if show_repo:
        label = repo_label(t.workdir)
        repo_col = display_ljust(f"[{label}]", MAX_REPO_WIDTH + 3)
        header = f"{t.icon} {repo_col}{progress} {t.name}"
    else:
        header = f"{t.icon} {progress} {t.name}"

    lines = [header]

    if verbose >= 1:
        description = t.display_text
        if description:
            lines.append(f"    {description}")

    if verbose >= 2:
        todo = t.todo_data
        if todo:
            lines.append("")
            for item in todo:
                step_id = item.get("id", "")
                step_name = item.get("name", "")
                lines.append(f"    {step_id}: {step_name}")

    return "\n".join(lines)


def gather_topics(
    include_archives: bool = False, all_projects: bool = False,
) -> tuple[list, bool]:
    """Collect and filter topics from specs/archives directories.

    Returns (topics, show_repo) where show_repo indicates whether the
    caller should display repository labels.
    """
    specs_dir = get_specs_dir()
    dirs = [specs_dir]
    archive_dirs: list[Path] = []
    if include_archives:
        ad = get_archives_dir()
        dirs.append(ad)
        archive_dirs.append(ad)

    archive_set = set(archive_dirs)
    topics: list[Topic] = []
    for d in dirs:
        if not d.is_dir():
            continue
        archived = d in archive_set
        for sub in d.iterdir():
            if not sub.is_dir():
                continue
            topic = Topic.from_dir(sub, archived=archived)
            if topic is not None:
                topics.append(topic)

    ctx = get_project_context()
    if not all_projects:
        topics = [t for t in topics if ctx.is_related_to(t)]
        show_repo = not ctx.in_git_workdir()
    else:
        show_repo = True

    return topics, show_repo


def prompt_selection(topics, show_repo=False, allow_empty=False):
    """Show a numbered list of topics and prompt user to choose one.

    Args:
        topics: List of Topic objects or Path objects (must be non-empty).
        show_repo: If True, display repository labels.
        allow_empty: If True, empty input returns None instead of exiting.

    Returns:
        The selected item, or None if allow_empty and user enters nothing.
    """
    display = topics[:10]
    for i, topic in enumerate(display, 1):
        label = format_topic(topic, show_repo=show_repo)
        print(f"  [{i}] {label}", file=sys.stderr)
    if len(topics) > 10:
        print(f"  ... ({len(topics) - 10} more)", file=sys.stderr)

    try:
        sys.stderr.write("Enter number to show: ")
        sys.stderr.flush()
        choice = sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)
    if not choice:
        if allow_empty:
            return None
        sys.exit(1)

    try:
        idx = int(choice) - 1
    except ValueError:
        print(f"Error: invalid number '{choice}'", file=sys.stderr)
        sys.exit(1)
    if idx < 0 or idx >= len(display):
        print(f"Error: number out of range (1-{len(display)})", file=sys.stderr)
        sys.exit(1)

    return display[idx]


def resolve_topic(name, include_archives=False):
    """Resolve a topic name to its directory, with optional archive search.

    Searches specs_dir first. When include_archives is True, also
    searches archives_dir and merges results (deduplicated).  When
    include_archives is False and no match is found, suggests retrying
    with --archives.

    Args:
        name: Topic name or substring to match.
        include_archives: If True, search both specs and archives.

    Returns:
        Path to the resolved topic directory.
    """
    specs_dir = get_specs_dir()

    matches = find_matching_topics(name, specs_dir)

    if include_archives:
        archives_dir = get_archives_dir()
        archive_matches = find_matching_topics(name, archives_dir)
        seen = {m.resolve() for m in matches}
        for m in archive_matches:
            if m.resolve() not in seen:
                matches.append(m)
                seen.add(m.resolve())

    if not matches:
        print(f"Error: no topic matching '{name}' found.", file=sys.stderr)
        if not include_archives:
            print("Hint: try --archives to search archived topics.",
                  file=sys.stderr)
        sys.exit(1)

    if len(matches) == 1:
        return matches[0]

    topics = sorted(
        [t for t in (Topic.from_dir(m) for m in matches) if t],
        key=lambda t: t.name, reverse=True,
    )
    if not topics:
        print(f"Error: no loadable topic matching '{name}'.", file=sys.stderr)
        sys.exit(1)

    selected = prompt_selection(topics)
    return selected.path


def select_topic_interactive(
    include_archives=False, all_projects=False, allow_empty=False,
):
    """List topics and prompt user to select one.

    Args:
        include_archives: If True, include archived topics.
        all_projects: If True, skip is_related_to filtering.
        allow_empty: If True, return None when no topics found or user
            enters empty input, instead of exiting.
    """
    topics, show_repo = gather_topics(
        include_archives=include_archives,
        all_projects=all_projects,
    )

    topics.sort(key=lambda t: t.name, reverse=True)

    if not topics:
        if allow_empty:
            return None
        print("Error: no topics found.", file=sys.stderr)
        sys.exit(1)
    if len(topics) == 1:
        return topics[0].path

    selected = prompt_selection(topics, show_repo=show_repo,
                                allow_empty=allow_empty)
    if selected is None:
        return None
    return selected.path


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
