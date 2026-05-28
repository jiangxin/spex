#!/usr/bin/env python3
"""Convert JSON-formatted todo files to XML format."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli import ArgumentParser
from common import check_help_flag

USAGE = """\
Usage: spex todo json2xml <todo.json>

Convert todo.json to todo.xml in the same directory.

Options:
  -h, --help  Show this help message and exit
"""


def _escape_xml_text(text: str) -> str:
    """Escape XML special characters in text content.

    Escapes &, <, > which are the only special characters needed
    inside element text content (quotes only matter in attributes).

    Args:
        text: Raw text that may contain XML special characters.

    Returns:
        Text with XML special characters properly escaped.
    """
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def convert_todo_to_xml(data):
    """Convert a list of todo item dicts to XML string.

    Args:
        data: List of dicts with at least 'id', 'name', 'details' keys.

    Returns:
        XML string in the canonical todo.xml format, with special
        characters in element text properly escaped.
    """
    lines = ["<steps>"]
    for item in data:
        lines.append("  <step>")
        lines.append(f"    <step-id>{_escape_xml_text(item['id'])}</step-id>")
        lines.append(f"    <step-name>{_escape_xml_text(item['name'])}</step-name>")
        lines.append("    <step-markdown-details>")
        lines.append(_escape_xml_text(item.get("details", "")))
        lines.append("    </step-markdown-details>")
        lines.append("  </step>")
    lines.append("</steps>")
    return "\n".join(lines) + "\n"


def main(argv=None):
    check_help_flag(USAGE)

    parser = ArgumentParser(prog="spex todo json2xml", usage=USAGE)
    parser.add_argument("json_file", help="Path to the JSON file")
    args = parser.parse(argv)

    json_path = Path(args.json_file)

    if not json_path.is_file():
        print(f"Error: file not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print("Error: top-level value must be an array.", file=sys.stderr)
        sys.exit(1)

    if not data:
        print("Error: empty array, nothing to convert.", file=sys.stderr)
        sys.exit(1)

    seen_ids = {}
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            print(f"Error: item[{i}] is not an object.", file=sys.stderr)
            sys.exit(1)
        step_id = item.get("id", "")
        if not step_id:
            print(f"Error: item[{i}]: 'id' is missing or empty.", file=sys.stderr)
            sys.exit(1)
        if step_id in seen_ids:
            print(
                f"Error: item[{i}]: duplicate id '{step_id}'"
                f" (first seen at item[{seen_ids[step_id]}]).",
                file=sys.stderr,
            )
            sys.exit(1)
        seen_ids[step_id] = i
        if not item.get("name"):
            print(f"Error: item[{i}]: 'name' is missing or empty.", file=sys.stderr)
            sys.exit(1)

    xml_content = convert_todo_to_xml(data)
    output_path = json_path.parent / "todo.xml"

    tmp_fd = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=output_path.parent, suffix=".tmp", delete=False,
    )
    try:
        tmp_fd.write(xml_content)
        tmp_fd.close()
        os.replace(tmp_fd.name, str(output_path))
    except BaseException:
        tmp_fd.close()
        if os.path.exists(tmp_fd.name):
            os.unlink(tmp_fd.name)
        raise

    print(f"OK: {len(data)} step(s) converted.")


if __name__ == "__main__":
    main()
