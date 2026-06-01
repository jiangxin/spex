#!/usr/bin/env python3
"""Unified CRUD operations for todo files (JSON and XML)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

from cli import ArgumentParser
from common import (
    atomic_write_json,
    check_help_flag,
    escape_xml_text,
    load_and_validate_todo_json,
    local_iso_timestamp,
    resolve_topic_dir,
    validate_unique_ids,
)

USAGE = """\
Usage: spex todo-helper [--topic <name> | --todo-file <path>] [--xml] \
<subcmd>

Operate on todo files (validate, append, edit, remove, show).

Global options:
  --topic <name>    Resolve topic dir, use <topic_dir>/todo.json (or .xml)
  --todo-file <path>  Direct path to todo file
  --xml             Force XML format

Subcommands:
  validate          Validate todo file format and check duplicate IDs
  append            Append a new entry
  edit              Edit an existing entry by ID
  remove            Remove an entry by ID
  show              Display entries with filtering and format options
  xml2json          Convert XML todo file to JSON format
  json2xml          Convert JSON todo file to XML format

Options:
  -h, --help        Show this help message and exit
"""

REQUIRED_FIELDS = ("id", "name", "details", "completed_at", "commit_title")


def _resolve_completed_at(value):
    """Resolve the special value 'now' to a local ISO timestamp."""
    if isinstance(value, str) and value.lower() == "now":
        return local_iso_timestamp()
    return value


# ---------------------------------------------------------------------------
# Load / write dispatchers
# ---------------------------------------------------------------------------

_XML_TO_DICT = {
    "step-id": "id",
    "step-name": "name",
    "step-details": "details",
    "completed-at": "completed_at",
    "commit-title": "commit_title",
}
_DICT_TO_XML = {v: k for k, v in _XML_TO_DICT.items()}


def load_todo_xml(path):
    """Load todo entries from an XML file."""
    path = Path(path)
    if not path.is_file():
        return []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        print(
            f"Error: failed to parse XML '{path}': {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if root.tag != "todo":
        print(
            f"Error: expected root element <todo>,"
            f" got <{root.tag}>.",
            file=sys.stderr,
        )
        sys.exit(1)
    entries = []
    for step in root.findall("step"):
        entry = {}
        for xml_name, dict_key in _XML_TO_DICT.items():
            elem = step.find(xml_name)
            entry[dict_key] = (
                elem.text if elem is not None and elem.text
                else ""
            )
        entries.append(entry)
    return entries


def write_todo_xml(path, data):
    """Write todo entries to an XML file."""
    path = Path(path)
    lines = ["<todo>"]
    for item in data:
        lines.append("  <step>")
        for dict_key in (
            "id", "name", "details",
            "completed_at", "commit_title",
        ):
            xml_name = _DICT_TO_XML[dict_key]
            value = escape_xml_text(str(item.get(dict_key, "")))
            lines.append(
                f"    <{xml_name}>{value}</{xml_name}>",
            )
        lines.append("  </step>")
    lines.append("</todo>\n")
    content = "\n".join(lines)
    path.parent.mkdir(parents=True, exist_ok=True)
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


def load_todo_json(path):
    """Load todo entries from a JSON file.

    Returns an empty list when the file does not exist or is empty.
    """
    path = Path(path)
    if not path.is_file():
        return []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    return load_and_validate_todo_json(path, allow_empty=True)


def load_todo_file(path, is_xml=False):
    """Dispatch to the appropriate loader based on format."""
    if is_xml:
        return load_todo_xml(path)
    return load_todo_json(path)


def write_todo_file(path, data, is_xml=False):
    """Dispatch to the appropriate writer based on format."""
    if is_xml:
        write_todo_xml(path, data)
    else:
        atomic_write_json(Path(path), data)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_validate(todo_path, is_xml):
    """Validate todo file format and check for duplicate IDs."""
    data = load_todo_file(todo_path, is_xml)
    validate_unique_ids(data)
    for i, item in enumerate(data):
        for field in REQUIRED_FIELDS:
            if field not in item:
                print(
                    f"Error: item[{i}]: missing required field"
                    f" '{field}'.",
                    file=sys.stderr,
                )
                sys.exit(1)
    print("OK")


def cmd_append(todo_path, is_xml, argv):
    """Append a new entry to the todo file."""
    usage = (
        "Usage: spex todo-helper ... append"
        " --id <id> --name <name>"
        " [--details <details> | --details-from-stdin]"
        " [--completed_at <ts>] [--commit_title <title>]"
    )
    check_help_flag(usage, argv)

    parser = ArgumentParser(
        prog="spex todo-helper append", usage=usage,
    )
    parser.add_argument("--id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--details", default=None)
    parser.add_argument(
        "--details-from-stdin", action="store_true",
    )
    parser.add_argument("--completed_at", default="")
    parser.add_argument("--commit_title", default="")
    args = parser.parse(argv)

    if args.details_from_stdin:
        details = sys.stdin.read()
    elif args.details is not None:
        details = args.details
    else:
        print(
            "Error: --details or --details-from-stdin required.",
            file=sys.stderr,
        )
        sys.exit(1)

    data = load_todo_file(todo_path, is_xml)

    for item in data:
        if isinstance(item, dict) and item.get("id") == args.id:
            print(
                f"Error: duplicate id '{args.id}'.",
                file=sys.stderr,
            )
            sys.exit(1)

    entry = {
        "id": args.id,
        "name": args.name,
        "details": details,
        "completed_at": _resolve_completed_at(args.completed_at),
        "commit_title": args.commit_title,
    }
    data.append(entry)
    write_todo_file(todo_path, data, is_xml)
    print(f"Appended '{args.id}'.")


def cmd_edit(todo_path, is_xml, argv):
    """Edit an existing entry by ID."""
    usage = (
        "Usage: spex todo-helper ... edit"
        " --id <id> [--name <n>]"
        " [--details <d> | --details-from-stdin]"
        " [--completed_at <ts>] [--commit_title <title>]"
    )
    check_help_flag(usage, argv)

    parser = ArgumentParser(
        prog="spex todo-helper edit", usage=usage,
    )
    parser.add_argument("--id", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--details", default=None)
    parser.add_argument(
        "--details-from-stdin", action="store_true",
    )
    parser.add_argument("--completed_at", default=None)
    parser.add_argument("--commit_title", default=None)
    args = parser.parse(argv)

    details = args.details
    if args.details_from_stdin:
        details = sys.stdin.read()

    if args.completed_at is not None:
        args.completed_at = _resolve_completed_at(args.completed_at)

    data = load_todo_file(todo_path, is_xml)

    found = False
    for item in data:
        if isinstance(item, dict) and item.get("id") == args.id:
            if args.name is not None:
                item["name"] = args.name
            if details is not None:
                item["details"] = details
            if args.completed_at is not None:
                item["completed_at"] = args.completed_at
            if args.commit_title is not None:
                item["commit_title"] = args.commit_title
            found = True
            break

    if not found:
        print(
            f"Error: id '{args.id}' not found.",
            file=sys.stderr,
        )
        sys.exit(1)

    write_todo_file(todo_path, data, is_xml)
    print(f"Updated '{args.id}'.")


def cmd_remove(todo_path, is_xml, argv):
    """Remove an entry by ID."""
    usage = "Usage: spex todo-helper ... remove --id <id>"
    check_help_flag(usage, argv)

    parser = ArgumentParser(
        prog="spex todo-helper remove", usage=usage,
    )
    parser.add_argument("--id", required=True)
    args = parser.parse(argv)

    data = load_todo_file(todo_path, is_xml)

    new_data = [
        item for item in data
        if not (isinstance(item, dict) and item.get("id") == args.id)
    ]

    if len(new_data) == len(data):
        print(
            f"Error: id '{args.id}' not found.",
            file=sys.stderr,
        )
        sys.exit(1)

    write_todo_file(todo_path, new_data, is_xml)
    print(f"Removed '{args.id}'.")


def _wrap_field(label, text, indent, width=10**9):
    """Wrap a sub-bullet field."""
    prefix = f"{indent}- {label}: "
    cont = " " * len(prefix)
    result = []
    for i, paragraph in enumerate(text.split("\n")):
        if i == 0:
            result.append(textwrap.fill(
                paragraph, width=width,
                initial_indent=prefix,
                subsequent_indent=cont,
            ))
        else:
            result.append(textwrap.fill(
                paragraph, width=width,
                initial_indent=cont,
                subsequent_indent=cont,
            ) if paragraph.strip() else cont.rstrip())
    return "\n".join(result)


def _format_block_details(text, indent, width=10**9):
    """Format multi-line details using block scalar syntax."""
    content_indent = " " * (len(indent) + 4)
    lines = [f"{indent}- details: |"]
    for paragraph in text.split("\n"):
        if paragraph.strip():
            lines.append(textwrap.fill(
                paragraph, width=width,
                initial_indent=content_indent,
                subsequent_indent=content_indent,
            ))
        else:
            lines.append("")
    return "\n".join(lines)


def _format_markdown(data, width=0):
    """Format todo entries as markdown.

    width=0 disables wrapping (lines may exceed 80 chars).
    """
    w = width if width > 0 else 10**9
    lines = []
    for idx, item in enumerate(data, 1):
        step_id = item.get("id", "")
        completed = bool(item.get("completed_at"))
        icon = "✅" if completed else "🔲"
        prefix = f"{idx}. "
        indent = " " * len(prefix)
        lines.append(f"{prefix}{icon} {step_id}")

        name = item.get("name", "")
        if name:
            lines.append(f"{indent}- name: {name}")

        details = item.get("details", "")
        if details:
            if "\n" in details:
                lines.append(
                    _format_block_details(details, indent, w),
                )
            else:
                lines.append(
                    _wrap_field("details", details, indent, w),
                )

        completed_at = item.get("completed_at", "")
        if completed_at:
            lines.append(f"{indent}- completed_at: {completed_at}")

        commit_title = item.get("commit_title", "")
        if commit_title:
            lines.append(
                _wrap_field("commit_title", commit_title, indent, w),
            )

    return "\n".join(lines)


def cmd_show(todo_path, is_xml, argv):
    """Display entries with optional filtering and format."""
    usage = (
        "Usage: spex todo-helper ... show"
        " [--done | --undone] [--format json|markdown]"
        " [--wrap | --no-wrap]"
    )
    check_help_flag(usage, argv)

    parser = ArgumentParser(
        prog="spex todo-helper show", usage=usage,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--done", action="store_true")
    group.add_argument("--undone", action="store_true")
    parser.add_argument(
        "--format", dest="fmt", choices=["json", "markdown"],
        default="json",
    )
    wrap_group = parser.add_mutually_exclusive_group()
    wrap_group.add_argument(
        "--wrap", action="store_true", default=False,
    )
    wrap_group.add_argument(
        "--no-wrap", dest="wrap", action="store_false",
    )
    args = parser.parse(argv)

    data = load_todo_file(todo_path, is_xml)

    if args.done:
        data = [
            item for item in data
            if isinstance(item, dict) and item.get("completed_at")
        ]
    elif args.undone:
        data = [
            item for item in data
            if isinstance(item, dict) and not item.get("completed_at")
        ]

    if args.fmt == "markdown":
        print(_format_markdown(data, width=80 if args.wrap else 0))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_xml2json(todo_path, is_xml, argv):
    """Convert an XML todo file to JSON format."""
    usage = "Usage: spex todo-helper ... xml2json [--rm]"
    check_help_flag(usage, argv)

    parser = ArgumentParser(
        prog="spex todo-helper xml2json", usage=usage,
    )
    parser.add_argument("--rm", action="store_true")
    args = parser.parse(argv)

    data = load_todo_xml(todo_path)
    output_path = todo_path.with_suffix(".json")
    atomic_write_json(output_path, data)
    if args.rm:
        todo_path.unlink()
    print(f"Converted {todo_path} -> {output_path}")


def cmd_json2xml(todo_path, is_xml, argv):
    """Convert a JSON todo file to XML format."""
    usage = "Usage: spex todo-helper ... json2xml [--rm]"
    check_help_flag(usage, argv)

    parser = ArgumentParser(
        prog="spex todo-helper json2xml", usage=usage,
    )
    parser.add_argument("--rm", action="store_true")
    args = parser.parse(argv)

    data = load_todo_json(todo_path)
    output_path = todo_path.with_suffix(".xml")
    write_todo_xml(output_path, data)
    if args.rm:
        todo_path.unlink()
    print(f"Converted {todo_path} -> {output_path}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _resolve_todo_path(args):
    """Resolve the todo file path from parsed global arguments.

    Returns (todo_path, is_xml) tuple.
    """
    is_xml = args.xml

    if args.todo_file:
        todo_path = Path(args.todo_file)
        if not is_xml and todo_path.suffix == ".xml":
            is_xml = True
        return (todo_path, is_xml)

    # --topic mode
    topic_dir = resolve_topic_dir(args.topic)
    filename = "todo.xml" if is_xml else "todo.json"
    return (topic_dir / filename, is_xml)


def main(argv=None):
    """Parse global args, resolve todo path, route to subcommand."""
    if argv is None:
        argv = sys.argv[1:]

    # Show top-level help only when no subcommand is present.
    # Subcommand handlers have their own check_help_flag calls.
    subcmds = {
        "validate", "append", "edit", "remove",
        "show", "xml2json", "json2xml",
    }
    if not subcmds.intersection(argv) and (
        not argv or {"-h", "--help"}.intersection(argv)
    ):
        print(USAGE, end="")
        sys.exit(0)

    parser = ArgumentParser(
        prog="spex todo-helper", usage=USAGE, add_help=False,
    )
    locator = parser.add_mutually_exclusive_group(required=True)
    locator.add_argument("--topic")
    locator.add_argument("--todo-file")
    parser.add_argument("--xml", action="store_true")
    parser.add_argument("subcmd", choices=[
        "validate", "append", "edit", "remove",
        "show", "xml2json", "json2xml",
    ])
    args, rest = parser.parse_known(argv)

    todo_path, is_xml = _resolve_todo_path(args)

    if args.subcmd == "validate":
        cmd_validate(todo_path, is_xml)
    elif args.subcmd == "append":
        cmd_append(todo_path, is_xml, rest)
    elif args.subcmd == "edit":
        cmd_edit(todo_path, is_xml, rest)
    elif args.subcmd == "remove":
        cmd_remove(todo_path, is_xml, rest)
    elif args.subcmd == "show":
        cmd_show(todo_path, is_xml, rest)
    elif args.subcmd == "xml2json":
        cmd_xml2json(todo_path, is_xml, rest)
    elif args.subcmd == "json2xml":
        cmd_json2xml(todo_path, is_xml, rest)


if __name__ == "__main__":
    main()
