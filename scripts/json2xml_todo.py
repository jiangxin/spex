#!/usr/bin/env python3
"""Convert JSON-formatted todo files to XML format."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli import ArgumentParser
from common import (
    check_help_flag,
    escape_xml_text,
    load_and_validate_todo_json,
    validate_unique_ids,
)

USAGE = """\
Usage: spex todo json2xml <todo.json>

Convert todo.json to todo.xml in the same directory.

Options:
  -h, --help  Show this help message and exit
"""




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
        lines.append(f"    <step-id>{escape_xml_text(item['id'])}</step-id>")
        lines.append(f"    <step-name>{escape_xml_text(item['name'])}</step-name>")
        lines.append("    <step-markdown-details>")
        lines.append(escape_xml_text(item.get("details", "")))
        lines.append("    </step-markdown-details>")
        lines.append("  </step>")
    lines.append("</steps>")
    return "\n".join(lines) + "\n"


def main(argv=None):
    check_help_flag(USAGE, argv)

    parser = ArgumentParser(prog="spex todo json2xml", usage=USAGE)
    parser.add_argument("json_file", help="Path to the JSON file")
    args = parser.parse(argv)

    json_path = Path(args.json_file)

    data = load_and_validate_todo_json(json_path)

    validate_unique_ids(data)
    for i, item in enumerate(data):
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
