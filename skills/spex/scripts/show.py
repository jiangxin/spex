#!/usr/bin/env python3
"""Show detailed information about a single spec."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from cli import ArgumentParser
from common import (
    Spec,
    format_spec,
    format_spec_metadata,
    format_step_status,
    get_archives_dir,
    resolve_spec,
    same_path,
    select_spec_interactive,
    split_command,
    strip_front_matter,
    todo_step_label,
)


def _paged_output(text):
    """Output text through a pager if stdout is a tty."""
    if not sys.stdout.isatty():
        print(text)
        return
    pager = os.environ.get("PAGER") or "less -R"
    argv = split_command(pager)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE)
        proc.communicate(input=text.encode())
    except (BrokenPipeError, OSError):
        print(text)


def _format_default(spec_dir):
    """Format spec in list -vv style, reused from common."""
    return format_spec(spec_dir, verbose=2, metadata=True)


def _format_verbose(spec_dir, *, archived=False):
    """Format spec with full content and structured todo."""
    t = Spec.from_dir(spec_dir, archived=archived)
    if t is None:
        return f"(unable to load spec: {spec_dir.name})"

    parts = []

    todo = t.todo_data or []
    parts.append(f"{t.icon} ({t.done}/{t.total}) {t.name} [{t.meta.task_mode}]")
    parts.append("")
    parts.extend(format_spec_metadata(t.summary(todo), full=True))
    parts.append("")
    parts.append("# **Specification**")
    parts.append("")
    if t.spec_content is not None:
        parts.append(strip_front_matter(t.spec_content).rstrip())
    else:
        parts.append("(no spec.md found)")

    parts.append("")
    parts.append("----")
    parts.append("")
    parts.append("# **TODO**")
    parts.append("")

    if todo:
        total_steps = len(todo)
        for item in todo:
            if not isinstance(item, dict):
                continue
            step_label = todo_step_label(item["id"], total_steps)
            step_name = item.get("name", "")
            details = item.get("details", "")
            status = format_step_status(t.step_summary(item))
            parts.append(f"- **{step_label}: {step_name}** [{status}]")
            parts.append("")
            if details:
                for line in details.splitlines():
                    parts.append(f"  {line}" if line else "")
                parts.append("")
    else:
        parts.append("(no tasks)")

    return "\n".join(parts).rstrip()


def _build_parser() -> ArgumentParser:
    """Build the argument parser for ``spex show``."""
    parser = ArgumentParser(
        prog="spex show",
        description="Show detailed information about a spec.",
    )
    parser.add_argument("name", nargs="?", metavar="<spec-name>",
                        help="Spec name or substring")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-l", "--list", action="store_true",
                        dest="brief",
                        help="Show brief list format instead of full details")
    group.add_argument(
        "--json",
        action="store_true",
        help="Output a JSON object with spec metadata and step details",
    )
    parser.add_argument(
        "--archives",
        action="store_true",
        help="Include archived specs in search",
    )
    parser.add_argument(
        "--all-projects",
        action="store_true",
        help="Show specs from all projects (disables project filter)",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse(argv)

    if args.name:
        spec_dir = resolve_spec(args.name, include_archives=args.archives)
    else:
        spec_dir = select_spec_interactive(
            include_archives=args.archives,
            all_projects=args.all_projects,
        )

    archived = args.archives and same_path(spec_dir.parent, get_archives_dir())
    if args.json:
        spec = Spec.from_dir(spec_dir, archived=archived)
        if spec is None:
            parser.error(f"unable to load spec: {spec_dir.name}")
        todo = spec.todo_data or []
        items = [item for item in todo if isinstance(item, dict)]
        payload = spec.summary(todo)
        payload["steps"] = [spec.step_summary(item) for item in items]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.brief:
        print(_format_default(spec_dir))
    else:
        _paged_output(_format_verbose(spec_dir, archived=archived))


if __name__ == "__main__":
    main()
