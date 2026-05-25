#!/usr/bin/env python3
"""Convert XML-formatted todo files to JSON format."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import atomic_write_json, check_help_flag

USAGE = """\
Usage: spex todo xml2json <xml-file>

Convert todo.xml to todo.json in the same directory.

Options:
  -h, --help  Show this help message and exit
"""


def _strip_blank_lines(text):
    """Strip leading/trailing blank lines, preserve internal content."""
    if not text:
        return ""
    lines = text.split('\n')
    # strip leading blank lines
    while lines and not lines[0].strip():
        lines.pop(0)
    # strip trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


def convert_xml_to_todo(xml_path):
    """Parse an XML file and return a list of todo item dicts.

    Args:
        xml_path: Path to the XML file to parse.

    Returns:
        List of dicts with keys: id, name, details, completed_at, commit_title.
    """
    path = Path(xml_path)

    if not path.is_file():
        print(f"Error: file not found: {xml_path}", file=sys.stderr)
        sys.exit(1)

    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        print(f"Error: invalid XML: {e}", file=sys.stderr)
        sys.exit(1)

    root = tree.getroot()
    if root.tag != "steps":
        print(
            f"Error: root element must be <steps>, got <{root.tag}>",
            file=sys.stderr,
        )
        sys.exit(1)

    steps = root.findall("step")
    if not steps:
        print("Error: no <step> elements found.", file=sys.stderr)
        sys.exit(1)

    results = []
    seen_ids = {}

    for i, step in enumerate(steps):
        # Extract step-id
        id_elem = step.find("step-id")
        if id_elem is None or not (id_elem.text and id_elem.text.strip()):
            print(
                f"Error: step[{i}]: <step-id> is missing or empty.",
                file=sys.stderr,
            )
            sys.exit(1)
        step_id = id_elem.text.strip()

        # Check duplicate ids
        if step_id in seen_ids:
            print(
                f"Error: step[{i}]: duplicate id '{step_id}'"
                f" (first seen at step[{seen_ids[step_id]}]).",
                file=sys.stderr,
            )
            sys.exit(1)
        seen_ids[step_id] = i

        # Extract step-name
        name_elem = step.find("step-name")
        if name_elem is None or not (name_elem.text and name_elem.text.strip()):
            print(
                f"Error: step[{i}]: <step-name> is missing or empty.",
                file=sys.stderr,
            )
            sys.exit(1)
        step_name = name_elem.text.strip()

        # Extract step-markdown-details
        details_elem = step.find("step-markdown-details")
        if details_elem is None:
            print(
                f"Error: step[{i}]: <step-markdown-details> is missing.",
                file=sys.stderr,
            )
            sys.exit(1)
        details_text = _strip_blank_lines(details_elem.text or "")

        results.append({
            "id": step_id,
            "name": step_name,
            "details": details_text,
            "completed_at": "",
            "commit_title": "",
        })

    return results


def main():
    check_help_flag(USAGE)

    if len(sys.argv) != 2:
        print(
            "Error: expected exactly one argument (XML file path).",
            file=sys.stderr,
        )
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    xml_path = Path(sys.argv[1])
    results = convert_xml_to_todo(xml_path)

    output_path = xml_path.parent / "todo.json"
    atomic_write_json(output_path, results)
    print(f"OK: {len(results)} step(s) converted.")


if __name__ == "__main__":
    main()
