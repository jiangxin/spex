"""Tests for xml2json_todo.py."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from xml2json_todo import _strip_blank_lines, convert_xml_to_todo, main


def _make_xml(steps):
    """Build a simple XML string from a list of step tuples.

    Each step is (id, name, details).
    """
    lines = ["<steps>"]
    for step_id, name, details in steps:
        lines.append("  <step>")
        lines.append(f"    <step-id>{step_id}</step-id>")
        lines.append(f"    <step-name>{name}</step-name>")
        lines.append(
            f"    <step-markdown-details>{details}</step-markdown-details>"
        )
        lines.append("  </step>")
    lines.append("</steps>")
    return "\n".join(lines)


def _write_xml(tmp_path, content, filename="todo.xml"):
    """Write XML content to a file and return the path."""
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return path


# ===================== Normal conversion =====================


class TestNormalConversion:
    def test_multi_step_conversion(self, tmp_path):
        xml = _make_xml([
            ("step-1", "First step", "Do the first thing"),
            ("step-2", "Second step", "Do the second thing"),
            ("step-3", "Third step", "Do the third thing"),
        ])
        path = _write_xml(tmp_path, xml)

        result = convert_xml_to_todo(path)

        assert len(result) == 3
        assert result[0]["id"] == "step-1"
        assert result[0]["name"] == "First step"
        assert result[0]["details"] == "Do the first thing"
        assert result[0]["completed_at"] == ""
        assert result[0]["commit_title"] == ""
        assert result[1]["id"] == "step-2"
        assert result[2]["id"] == "step-3"

    def test_single_step(self, tmp_path):
        xml = _make_xml([("only-1", "Only step", "Just one step")])
        path = _write_xml(tmp_path, xml)

        result = convert_xml_to_todo(path)

        assert len(result) == 1
        assert result[0]["id"] == "only-1"
        assert result[0]["name"] == "Only step"
        assert result[0]["details"] == "Just one step"

    def test_multiline_markdown_details(self, tmp_path):
        details = (
            "## Heading\n"
            "\n"
            "- item 1\n"
            "- item 2\n"
            "\n"
            "```python\n"
            "print('hello')\n"
            "```"
        )
        xml = _make_xml([("md-1", "Markdown step", details)])
        path = _write_xml(tmp_path, xml)

        result = convert_xml_to_todo(path)

        assert result[0]["details"] == details


# ===================== Text trimming =====================


class TestTextTrimming:
    def test_strip_leading_trailing_blank_lines(self, tmp_path):
        details = "\n\n\nActual content\nMore content\n\n\n"
        xml = _make_xml([("trim-1", "Trim step", details)])
        path = _write_xml(tmp_path, xml)

        result = convert_xml_to_todo(path)

        assert result[0]["details"] == "Actual content\nMore content"

    def test_strip_blank_lines_function_empty(self):
        assert _strip_blank_lines("") == ""
        assert _strip_blank_lines(None) == ""

    def test_strip_blank_lines_preserves_internal(self):
        text = "\n\nline1\n\nline2\n\n"
        assert _strip_blank_lines(text) == "line1\n\nline2"

    def test_strip_blank_lines_no_trimming_needed(self):
        text = "already clean"
        assert _strip_blank_lines(text) == "already clean"


# ===================== Error cases =====================


class TestMissingStepId:
    def test_missing_step_id_tag(self, tmp_path):
        xml = (
            "<steps>\n"
            "  <step>\n"
            "    <step-name>No ID</step-name>\n"
            "    <step-markdown-details>Details</step-markdown-details>\n"
            "  </step>\n"
            "</steps>"
        )
        path = _write_xml(tmp_path, xml)

        with pytest.raises(SystemExit):
            convert_xml_to_todo(path)

    def test_empty_step_id(self, tmp_path, capsys):
        xml = (
            "<steps>\n"
            "  <step>\n"
            "    <step-id></step-id>\n"
            "    <step-name>Empty ID</step-name>\n"
            "    <step-markdown-details>Details</step-markdown-details>\n"
            "  </step>\n"
            "</steps>"
        )
        path = _write_xml(tmp_path, xml)

        with pytest.raises(SystemExit):
            convert_xml_to_todo(path)

        err = capsys.readouterr().err
        assert "<step-id> is missing or empty" in err


class TestDuplicateIds:
    def test_duplicate_ids_error(self, tmp_path, capsys):
        xml = _make_xml([
            ("dup-1", "First", "Details 1"),
            ("dup-1", "Second", "Details 2"),
        ])
        path = _write_xml(tmp_path, xml)

        with pytest.raises(SystemExit):
            convert_xml_to_todo(path)

        err = capsys.readouterr().err
        assert "duplicate id 'dup-1'" in err


class TestInvalidXml:
    def test_malformed_xml(self, tmp_path, capsys):
        xml = "<steps><step><step-id>1</step-id><unclosed>"
        path = _write_xml(tmp_path, xml)

        with pytest.raises(SystemExit):
            convert_xml_to_todo(path)

        err = capsys.readouterr().err
        assert "invalid XML" in err


class TestEmptySteps:
    def test_no_step_children(self, tmp_path, capsys):
        xml = "<steps></steps>"
        path = _write_xml(tmp_path, xml)

        with pytest.raises(SystemExit):
            convert_xml_to_todo(path)

        err = capsys.readouterr().err
        assert "no <step> elements found" in err


class TestFileNotFound:
    def test_nonexistent_file(self, capsys):
        with pytest.raises(SystemExit):
            convert_xml_to_todo("/nonexistent/todo.xml")

        err = capsys.readouterr().err
        assert "file not found" in err


# ===================== Output path =====================


class TestOutputPath:
    def test_output_in_same_dir(self, tmp_path, monkeypatch, capsys):
        xml = _make_xml([("out-1", "Output step", "Some details")])
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        path = _write_xml(subdir, xml)

        monkeypatch.setattr(sys, "argv", ["xml2json_todo.py", str(path)])
        main()

        output_file = subdir / "todo.json"
        assert output_file.is_file()
        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == "out-1"

        out = capsys.readouterr().out
        assert "OK: 1 step(s) converted." in out


# ===================== Help flag =====================


class TestHelpFlag:
    def test_help_short(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["xml2json_todo.py", "-h"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "Usage:" in out

    def test_help_long(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["xml2json_todo.py", "--help"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "Usage:" in out


# ===================== Missing args =====================


class TestMissingArgs:
    def test_no_args(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["xml2json_todo.py"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "expected exactly one argument" in err
