#!/usr/bin/env python3
"""Render a Jinja2 template with metadata and output the result."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_specs_dir,
    get_template,
    load_meta,
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

    missing = [key for key in required if key not in metadata or not metadata[key]]
    if missing:
        print(
            f"Error: missing required metadata: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)


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

    if template_name == "spec":
        pass  # spec uses common + topic metadata only

    return metadata


def render_prompt(name, topic_name=None):
    """Render a template by name and return the result string.

    Args:
        name: Template name without .md extension (e.g. "spec-template").
        topic_name: Optional topic name for topic-specific metadata.

    Returns:
        Rendered template content with front-matter stripped.
    """
    from jinja2 import Template

    content = get_template(name + ".md")
    metadata = _build_metadata(name, topic_name)
    validate_required_meta(content, metadata)
    rendered = Template(content).render(**metadata)
    return strip_front_matter(rendered)


def main():
    parser = argparse.ArgumentParser(
        description="Render a Jinja2 template with metadata."
    )
    parser.add_argument("name", help="Template name (without .md extension)")
    parser.add_argument("--topic", help="Topic name for topic-specific metadata")
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    try:
        from jinja2 import TemplateError
    except ImportError:
        print("Error: jinja2 is required. Install with: pip install jinja2", file=sys.stderr)
        sys.exit(1)

    try:
        rendered = render_prompt(args.name, args.topic)
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
