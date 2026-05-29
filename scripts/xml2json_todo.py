#!/usr/bin/env python3
"""Convert XML-formatted todo files to JSON format."""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli import ArgumentParser
from common import atomic_write_json, check_help_flag, load_todo, strip_date_prefix

USAGE = """\
Usage: spex todo xml2json <xml-file> [--append] [--rm] [--post-action --event-type <type>]

Convert todo.xml to todo.json in the same directory.

Options:
  -h, --help              Show this help message and exit
  -a, --append            Append new steps to existing todo.json (preserving completed steps)
  -r, --rm                Remove XML file after successful conversion
  --post-action           Run post-action hook after successful conversion
  --event-type <type>     Event type for the post-action hook (required with --post-action)
"""


def _escape_xml_text(text: str) -> str:
    """Escape unescaped XML special characters inside element text content.

    Replaces &, <, > with their entity equivalents, but skips characters
    that are already part of a valid XML entity (e.g. &lt;, &amp;).

    Args:
        text: Raw text that may contain unescaped special characters.

    Returns:
        Text with special characters properly escaped.
    """
    # Only escape bare &, <, > — skip already-escaped entities like &lt; &gt; &amp;
    # Strategy: split on existing entities, escape non-entity parts, rejoin.
    parts = re.split(r"(&(?:lt|gt|amp|quot|apos);)", text)
    result = []
    for part in parts:
        if re.match(r"&(?:lt|gt|amp|quot|apos);", part):
            result.append(part)  # Already an entity, leave as-is
        else:
            result.append(_escape_bare_xml_chars(part))
    return "".join(result)


def _escape_bare_xml_chars(text: str) -> str:
    """Escape &, <, > in text that contains no XML entities."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _preprocess_xml(xml_text: str) -> str:
    """Preprocess XML text to escape unescaped special characters.

    Scans <step-markdown-details>...</step-markdown-details> blocks and
    escapes any unescaped &, <, > characters inside them so that
    xml.etree.ElementTree can parse the XML without errors.

    Args:
        xml_text: Raw XML string.

    Returns:
        XML string with special characters in details blocks escaped.
    """
    pattern = re.compile(
        r"(<step-markdown-details>)(.*?)(</step-markdown-details>)",
        re.DOTALL,
    )

    def _replacer(match):
        open_tag = match.group(1)
        content = match.group(2)
        close_tag = match.group(3)
        return open_tag + _escape_xml_text(content) + close_tag

    return pattern.sub(_replacer, xml_text)


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
        xml_text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error: cannot read file: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        root = ET.fromstring(_preprocess_xml(xml_text))
    except ET.ParseError as e:
        print(f"Error: invalid XML: {e}", file=sys.stderr)
        sys.exit(1)
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


def main(argv=None):
    check_help_flag(USAGE, argv)

    parser = ArgumentParser(prog="spex todo xml2json", usage=USAGE)
    parser.add_argument("xml_file", help="Path to the XML file")
    parser.add_argument("-a", "--append", action="store_true")
    parser.add_argument("-r", "--rm", action="store_true")
    parser.add_argument("--post-action", action="store_true")
    parser.add_argument("--event-type", metavar="TYPE")
    args = parser.parse(argv)

    if args.post_action and not args.event_type:
        print("Error: --post-action requires --event-type", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    xml_path = Path(args.xml_file)
    results = convert_xml_to_todo(xml_path)

    output_path = xml_path.parent / "todo.json"

    if args.append and output_path.exists():
        existing = load_todo(xml_path.parent)
        if existing and isinstance(existing, list):
            existing_ids = {
                item.get("id", "")
                for item in existing
                if isinstance(item, dict)
            }
            dupes = [
                step.get("id")
                for step in results
                if step.get("id") in existing_ids
            ]
            if dupes:
                print(
                    f"Error: duplicate step ID(s) in append mode: "
                    f"{', '.join(dupes)}",
                    file=sys.stderr,
                )
                sys.exit(1)
            existing.extend(results)
            atomic_write_json(output_path, existing)
            print(f"OK: appended {len(results)} step(s) to {len(existing)} existing.")
        else:
            atomic_write_json(output_path, results)
            print(f"OK: {len(results)} step(s) written (no existing todos).")
            existing = results
        if args.rm and xml_path.exists():
            xml_path.unlink()
    else:
        atomic_write_json(output_path, results)
        print(f"OK: {len(results)} step(s) converted.")
        if args.rm and xml_path.exists():
            xml_path.unlink()
        existing = results

    if args.post_action:
        import common
        import hooks

        topic_dir = xml_path.parent
        meta = common.load_meta(topic_dir)
        topic_name = meta.get("topic", "") if meta else ""
        topic_name = topic_name or strip_date_prefix(topic_dir.name)
        workdir = meta.get("workdir", "") if meta else ""
        if not workdir:
            workdir = common.get_current_workdir()

        done = sum(
            1 for item in (existing or [])
            if isinstance(item, dict) and item.get("completed_at")
        )
        undone = len(existing or []) - done

        hooks.run_post_action(
            args.event_type,
            {"topic": topic_name, "done": done, "undone": undone},
            workdir or None,
            topic_name,
        )


if __name__ == "__main__":
    main()
