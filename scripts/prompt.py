#!/usr/bin/env python3
"""Render a Jinja2 template with metadata and output the result."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from cli import ArgumentParser
from common import (
    atomic_write_json,
    get_git_info,
    get_spex_root,
    get_template,
    load_meta,
    load_todo,
    local_iso_timestamp,
    resolve_topic_dir,
    strip_front_matter,
)
from remove_undone_todo import filter_completed_todos as _filter_completed_todos


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
            # Match YAML list item format: "  - item_name"
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


def _format_item_verbose(item):
    """Format a single todo item in verbose markdown style."""
    task_id = item.get("id", "")
    name = item.get("name", "")
    details = item.get("details", "")
    lines = [f"- **{task_id}**: {name}"]
    if details:
        for line in details.splitlines():
            lines.append(f"  {line}" if line else "")
    return "\n".join(lines)


def _format_item_brief(item):
    """Format a single todo item as a brief one-liner."""
    return f"- {item.get('id', '')}: {item.get('name', '')} *(details omitted)*"


def _format_item_concise(item):
    """Format a single todo item as a concise one-liner (id + name only)."""
    return f"- **{item.get('id', '')}**: {item.get('name', '')}"


def _build_task_context(topic_dir, verbose_items=20):
    """Extract task context from a topic directory.

    Reads spec.md and todo.json, computes completed/current/future task info.

    Args:
        topic_dir: Path to the topic directory.
        verbose_items: Max number of items to show with full details.
            Items beyond this limit are shown in brief format.

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
        if len(done) <= verbose_items:
            completed_tasks = "\n\n".join(
                _format_item_verbose(item) for item in done
            )
        else:
            brief_items = done[:-verbose_items]
            verbose_part = done[-verbose_items:]
            parts = [_format_item_brief(item) for item in brief_items]
            parts.extend(_format_item_verbose(item) for item in verbose_part)
            completed_tasks = "\n\n".join(parts)
        completed_tasks_concise = "\n".join(
            _format_item_concise(item) for item in done
        )

        undone = [item for item in todo if not item.get("completed_at")]
        if undone:
            current = undone[0]
            task_id = current.get("id", "")
            next_task_id = task_id
            next_task_text = _format_item_verbose(current)

            future = undone[1:]
            if future:
                if len(future) <= verbose_items:
                    future_tasks = "\n\n".join(
                        _format_item_verbose(item) for item in future
                    )
                else:
                    verbose_part = future[:verbose_items]
                    brief_items = future[verbose_items:]
                    parts = [
                        _format_item_verbose(item) for item in verbose_part
                    ]
                    parts.extend(
                        _format_item_brief(item) for item in brief_items
                    )
                    future_tasks = "\n\n".join(parts)
                future_tasks_concise = "\n".join(
                    _format_item_concise(item) for item in future
                )
            else:
                future_tasks = ""
                future_tasks_concise = ""
        else:
            next_task_id = ""
            next_task_text = ""
            future_tasks = ""
            future_tasks_concise = ""
    else:
        completed_tasks = ""
        completed_tasks_concise = ""
        next_task_id = ""
        next_task_text = ""
        future_tasks = ""
        future_tasks_concise = ""

    return {
        "spec_content": spec_content,
        "completed_tasks": completed_tasks,
        "completed_tasks_concise": completed_tasks_concise,
        "next_task_id": next_task_id,
        "next_task_text": next_task_text,
        "future_tasks": future_tasks,
        "future_tasks_concise": future_tasks_concise,
    }


def _log_prompt_to_meta(topic_dir, prompt_text):
    """Append prompt_text to the prompts array in meta.json.

    Loads meta.json, ensures a 'prompts' list exists, appends
    {'text': prompt_text, 'timestamp': local_iso_timestamp()},
    and writes atomically.
    """
    meta = load_meta(topic_dir)
    if meta is None:
        meta = {}
    prompts = meta.get("prompts", [])
    if not isinstance(prompts, list):
        prompts = []
    prompts.append({
        "text": prompt_text,
        "timestamp": local_iso_timestamp(),
    })
    meta["prompts"] = prompts
    atomic_write_json(topic_dir / "meta.json", meta)


def _build_metadata(template_name, topic_name=None):
    """Build the metadata dict for template rendering.

    Different template names may produce different metadata.
    """
    git_info = get_git_info()
    metadata = {
        "timestamp": local_iso_timestamp(),
        "workdir": git_info["workdir"],
        "git_remote": git_info["remote_url"],
        "git_branch": git_info["branch"],
        "git_user": git_info["user_name"],
        "git_email": git_info["user_email"],
    }

    if topic_name:
        topic_dir = resolve_topic_dir(topic_name)
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
    # All topic-based templates except spec-template need task context:
    # apply-commit, apply-one-task, modify-spec, modify-todo
    if template_name != "spec-template" and topic_name:
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
        return ""

    validate_required_meta(content, metadata)
    rendered = Template(content).render(**metadata)
    return strip_front_matter(rendered)


def _output_rendered(rendered, output_path):
    """Write rendered content to file or stdout."""
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


def cli_apply_one_task(argv):
    """CLI handler for apply-one-task subcommand."""
    import json

    from jinja2 import TemplateError

    parser = ArgumentParser(
        prog="spex prompt apply-one-task",
        description="Render apply-one-task template with topic metadata.",
    )
    parser.add_argument("--topic", required=True,
                        help="Topic name (required)")
    parser.add_argument("--json", action="store_true", dest="json_mode",
                        help="Output JSON with task_id and prompt")
    parser.add_argument("-o", "--output",
                        help="Output file path (default: stdout)")
    args = parser.parse(argv)

    try:
        metadata = _build_metadata("apply-one-task", args.topic)

        # Handle all-done in JSON mode
        if args.json_mode and not metadata.get("next_task_text"):
            print(json.dumps({"task_id": "", "prompt": "", "all_done": True}))
            sys.exit(0)

        # Handle all-done in non-JSON mode: exit(0) with empty stdout
        if not args.json_mode and not metadata.get("next_task_text"):
            sys.exit(0)

        # Emit task_id to stderr for orchestrator to capture (non-JSON only)
        if not args.json_mode:
            next_task_id = metadata.get("next_task_id", "")
            if next_task_id:
                print(f"task_id={next_task_id}", file=sys.stderr)

        rendered = render_prompt("apply-one-task", args.topic, metadata=metadata)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except TemplateError as e:
        print(f"Error rendering template: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json_mode:
        task_id = metadata.get("next_task_id", "")
        print(json.dumps({"task_id": task_id, "prompt": rendered}))
    else:
        _output_rendered(rendered, args.output)


def _read_stdin_extra_vars(stdin_flag):
    """Read extra variables from stdin (JSON or raw text with --stdin flag)."""
    import json

    if sys.stdin.isatty():
        return None
    stdin_data = sys.stdin.read().strip()
    if not stdin_data:
        return None
    if stdin_flag:
        return {"prompt_context": stdin_data}
    try:
        return json.loads(stdin_data)
    except json.JSONDecodeError:
        print("Error: stdin must be valid JSON", file=sys.stderr)
        sys.exit(1)


def cli_apply_commit(argv):
    """CLI handler for apply-commit subcommand."""
    from jinja2 import TemplateError

    parser = ArgumentParser(
        prog="spex prompt apply-commit",
        description="Render apply-commit template with topic metadata.",
    )
    parser.add_argument("--topic", help="Topic name")
    parser.add_argument("--stdin", action="store_true", dest="stdin_flag",
                        help="Read raw text from stdin as prompt_context")
    parser.add_argument("-o", "--output",
                        help="Output file path (default: stdout)")
    args = parser.parse(argv)

    extra_vars = _read_stdin_extra_vars(args.stdin_flag)

    try:
        metadata = _build_metadata("apply-commit", args.topic)
        if extra_vars:
            metadata.update(extra_vars)

        # Handle all-done: exit(0) with empty stdout
        if not metadata.get("next_task_text"):
            sys.exit(0)

        rendered = render_prompt("apply-commit", args.topic, metadata=metadata)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except TemplateError as e:
        print(f"Error rendering template: {e}", file=sys.stderr)
        sys.exit(1)

    _output_rendered(rendered, args.output)


def cli_modify_spec(argv):
    """CLI handler for modify-spec subcommand."""
    import json

    from jinja2 import TemplateError

    parser = ArgumentParser(
        prog="spex prompt modify-spec",
        description="Render modify-spec template with topic metadata.",
    )
    parser.add_argument("--topic", required=True,
                        help="Topic name (required)")
    parser.add_argument("--stdin", action="store_true", dest="stdin_flag",
                        help="Read raw text from stdin as prompt_context")
    parser.add_argument("--remove-undone", action="store_true",
                        dest="remove_undone",
                        help="Remove undone tasks from todo.json before rendering")
    parser.add_argument("--json", action="store_true", dest="json_mode",
                        help="Output JSON with rendered prompt")
    parser.add_argument("-o", "--output",
                        help="Output file path (default: stdout)")
    args = parser.parse(argv)

    extra_vars = _read_stdin_extra_vars(args.stdin_flag)

    try:
        # Side-effect: remove undone tasks from todo.json before building metadata
        if args.remove_undone:
            topic_dir = resolve_topic_dir(args.topic)
            todo_path = topic_dir / "todo.json"
            if todo_path.exists():
                try:
                    data = json.loads(todo_path.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        completed = _filter_completed_todos(data)
                        atomic_write_json(todo_path, completed)
                except json.JSONDecodeError:
                    pass  # Silently skip if JSON is invalid

        metadata = _build_metadata("modify-spec", args.topic)
        if extra_vars:
            metadata.update(extra_vars)

        # Side-effect: log prompt_context to meta.json
        prompt_context = metadata.get("prompt_context", "")
        if prompt_context:
            topic_dir = resolve_topic_dir(args.topic)
            _log_prompt_to_meta(topic_dir, prompt_context)

        rendered = render_prompt("modify-spec", args.topic, metadata=metadata)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except TemplateError as e:
        print(f"Error rendering template: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json_mode:
        print(json.dumps({"prompt": rendered}))
    else:
        _output_rendered(rendered, args.output)


def cli_modify_todo(argv):
    """CLI handler for modify-todo subcommand."""
    import json

    from jinja2 import TemplateError

    parser = ArgumentParser(
        prog="spex prompt modify-todo",
        description="Render modify-todo template with topic metadata.",
    )
    parser.add_argument("--topic", required=True,
                        help="Topic name (required)")
    parser.add_argument("--stdin", action="store_true", dest="stdin_flag",
                        help="Read raw text from stdin as prompt_context")
    parser.add_argument("--json", action="store_true", dest="json_mode",
                        help="Output JSON with rendered prompt")
    parser.add_argument("-o", "--output",
                        help="Output file path (default: stdout)")
    args = parser.parse(argv)

    extra_vars = _read_stdin_extra_vars(args.stdin_flag)

    try:
        metadata = _build_metadata("modify-todo", args.topic)
        if extra_vars:
            metadata.update(extra_vars)

        # Side-effect: clean undone todos from todo.json
        topic_dir = resolve_topic_dir(args.topic)
        todo_path = topic_dir / "todo.json"
        if todo_path.exists():
            try:
                data = json.loads(todo_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    completed = _filter_completed_todos(data)
                    atomic_write_json(todo_path, completed)
            except json.JSONDecodeError:
                pass  # Silently skip if JSON is invalid

        rendered = render_prompt("modify-todo", args.topic, metadata=metadata)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except TemplateError as e:
        print(f"Error rendering template: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json_mode:
        print(json.dumps({"prompt": rendered}))
    else:
        _output_rendered(rendered, args.output)


def cli_render(argv):
    """Fallback CLI handler for generic template rendering."""
    from jinja2 import TemplateError

    parser = ArgumentParser(
        prog="spex prompt",
        description="Render a Jinja2 template with metadata.",
    )
    parser.add_argument("name", help="Template name (without .md extension)")
    parser.add_argument("--topic", help="Topic name for topic-specific metadata")
    parser.add_argument("--stdin", action="store_true", dest="stdin_flag",
                        help="Read raw text from stdin as prompt_context")
    parser.add_argument("-o", "--output",
                        help="Output file path (default: stdout)")
    args = parser.parse(argv)

    extra_vars = _read_stdin_extra_vars(args.stdin_flag)

    try:
        metadata = _build_metadata(args.name, args.topic)
        if extra_vars:
            metadata.update(extra_vars)

        rendered = render_prompt(args.name, args.topic, metadata=metadata)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except TemplateError as e:
        print(f"Error rendering template: {e}", file=sys.stderr)
        sys.exit(1)

    _output_rendered(rendered, args.output)


SUBCOMMANDS = {
    "apply-one-task": cli_apply_one_task,
    "apply-commit": cli_apply_commit,
    "modify-spec": cli_modify_spec,
    "modify-todo": cli_modify_todo,
}

USAGE = """\
Usage: spex prompt <subcommand> [options]

Subcommands:
  apply-one-task  Render prompt for the next undone task
  apply-commit    Render commit instructions for the current task
  modify-spec     Render prompt for modifying a spec
  modify-todo     Render prompt for modifying a todo list
  <template-name> Render a generic template (fallback)

Options:
  -h, --help  Show this help message and exit
"""


def main(argv=None):
    """Route prompt subcommands to their handlers."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(USAGE, end="", file=sys.stderr)
        sys.exit(1)

    subcmd = argv[0]
    if subcmd in ("-h", "--help"):
        print(USAGE, end="")
        sys.exit(0)

    handler = SUBCOMMANDS.get(subcmd)
    if handler:
        handler(argv[1:])
    else:
        cli_render(argv)  # fallback: treat argv[0] as template name


if __name__ == "__main__":
    main()
