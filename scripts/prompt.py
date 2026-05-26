#!/usr/bin/env python3
"""Render a Jinja2 template with metadata and output the result."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_specs_dir,
    get_spex_root,
    get_template,
    load_meta,
    load_todo,
    local_iso_timestamp,
    strip_front_matter,
)


def _get_git_info():
    """Retrieve git repository metadata."""
    commands = {
        "workdir": ["git", "rev-parse", "--show-toplevel"],
        "git_remote": ["git", "remote", "get-url", "origin"],
        "git_branch": ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        "git_user": ["git", "config", "user.name"],
        "git_email": ["git", "config", "user.email"],
    }
    info = {}
    for key, cmd in commands.items():
        result = subprocess.run(cmd, capture_output=True, text=True)
        info[key] = result.stdout.strip() if result.returncode == 0 else ""
    return info


def _resolve_topic_dir(topic_name):
    """Resolve a topic name to its directory path."""
    specs_dir = Path(get_specs_dir())
    if not specs_dir.is_dir():
        print(f"Error: specs directory does not exist: {specs_dir}", file=sys.stderr)
        sys.exit(1)

    direct = specs_dir / topic_name
    if direct.is_dir():
        return direct

    matches = sorted(
        d for d in specs_dir.iterdir() if d.is_dir() and topic_name in d.name
    )
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


def validate_required_meta(content, metadata):
    """Check that all keys listed in front-matter 'required' are present in metadata."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return

    front_matter = match.group(1)
    required = []
    in_required = False
    for line in front_matter.splitlines():
        if re.match(r"required:\s*$", line):
            in_required = True
            continue
        if in_required:
            m = re.match(r"\s+-\s+(.+)", line)
            if m:
                required.append(m.group(1).strip().strip("\"'"))
            else:
                break

    missing = [key for key in required if key not in metadata]
    if missing:
        print(
            f"Error: missing required metadata: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)


def _build_task_context(topic_dir):
    """Extract task context from a topic directory.

    Reads spec.md and todo.json, computes completed/current/future task info.

    Args:
        topic_dir: Path to the topic directory.

    Returns:
        Dict with keys: spec_content, completed_tasks, next_task_id,
        next_task_text, future_tasks.
    """
    spec_path = topic_dir / "spec.md"
    if spec_path.exists():
        spec_content = spec_path.read_text(encoding="utf-8")
    else:
        spec_content = ""

    todo = load_todo(topic_dir)
    if todo:
        done = [item for item in todo if item.get("completed_at")]
        completed_tasks = "\n".join(
            f"{item.get('id', '')}: {item.get('name', '')}" for item in done
        )
        undone = [item for item in todo if not item.get("completed_at")]
        if undone:
            current = undone[0]
            task_id = current.get("id", "")
            name = current.get("name", "")
            details = current.get("details", "")
            next_task_id = task_id
            next_task_text = (
                f"**Task**: {task_id} - {name}\n\n"
                f"**Implementation Details**:\n\n"
                f"<details>\n{details}\n\n</details>"
            )
            future = undone[1:]
            future_tasks = (
                "\n".join(
                    f"- {item.get('id', '')}: {item.get('name', '')}"
                    for item in future
                )
                if future
                else ""
            )
        else:
            next_task_id = ""
            next_task_text = ""
            future_tasks = ""
    else:
        completed_tasks = ""
        next_task_id = ""
        next_task_text = ""
        future_tasks = ""

    return {
        "spec_content": spec_content,
        "completed_tasks": completed_tasks,
        "next_task_id": next_task_id,
        "next_task_text": next_task_text,
        "future_tasks": future_tasks,
    }


def _build_metadata(template_name, topic_name=None):
    """Build the metadata dict for template rendering.

    Different template names may produce different metadata.
    """
    git_info = _get_git_info()
    metadata = {
        "timestamp": local_iso_timestamp(),
        **git_info,
    }

    if topic_name:
        topic_dir = _resolve_topic_dir(topic_name)
        metadata["topic_name"] = topic_dir.name
        meta = load_meta(topic_dir)
        if meta:
            metadata.update(meta)

    if template_name == "apply-commit":
        metadata["spex_root"] = ""
        workdir = metadata.get("workdir", "")
        if workdir:
            try:
                spex_root = get_spex_root()
                rel = os.path.relpath(spex_root, workdir)
                if not rel.startswith(".."):
                    metadata["spex_root"] = rel
            except (ValueError, RuntimeError):
                pass
        if topic_name:
            metadata.update(_build_task_context(topic_dir))

    if template_name == "apply-one-task" and topic_name:
        metadata.update(_build_task_context(topic_dir))

    return metadata


def render_prompt(name, topic_name=None, extra_vars=None, metadata=None):
    """Render a template by name and return the result string.

    Args:
        name: Template name without .md extension (e.g. "spec-template").
        topic_name: Optional topic name for topic-specific metadata.
        extra_vars: Optional dict of additional variables to merge into metadata.
        metadata: Optional pre-built metadata dict. Skips _build_metadata when provided.

    Returns:
        Rendered template content with front-matter stripped.
    """
    from jinja2 import Template

    content = get_template(name + ".md")
    if metadata is None:
        metadata = _build_metadata(name, topic_name)
        if extra_vars:
            metadata.update(extra_vars)

    # All-done detection for task-based templates
    if name in ("apply-one-task", "apply-commit") and not metadata.get(
        "next_task_text"
    ):
        print(
            "Error: all tasks are completed, nothing to apply.",
            file=sys.stderr,
        )
        sys.exit(1)

    validate_required_meta(content, metadata)
    rendered = Template(content).render(**metadata)
    return strip_front_matter(rendered)


def main():
    import json

    parser = argparse.ArgumentParser(
        description="Render a Jinja2 template with metadata."
    )
    parser.add_argument("name", help="Template name (without .md extension)")
    parser.add_argument("--topic", help="Topic name for topic-specific metadata")
    parser.add_argument("--stdin", action="store_true",
                        help="Read raw text from stdin as prompt_context")
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    try:
        from jinja2 import TemplateError
    except ImportError:
        print("Error: jinja2 is required. Install with: pip install jinja2", file=sys.stderr)
        sys.exit(1)

    extra_vars = None
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            if args.stdin:
                extra_vars = {"prompt_context": stdin_data}
            else:
                try:
                    extra_vars = json.loads(stdin_data)
                except json.JSONDecodeError:
                    print("Error: stdin must be valid JSON", file=sys.stderr)
                    sys.exit(1)

    try:
        metadata = _build_metadata(args.name, args.topic)
        if extra_vars:
            metadata.update(extra_vars)

        # Emit task_id to stderr for orchestrator to capture
        if args.name == "apply-one-task":
            next_task_id = metadata.get("next_task_id", "")
            if next_task_id:
                print(f"task_id={next_task_id}", file=sys.stderr)

        rendered = render_prompt(args.name, args.topic, metadata=metadata)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except TemplateError as e:
        print(f"Error rendering template: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
