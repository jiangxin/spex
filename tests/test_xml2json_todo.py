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


class TestAppendMode:
    def test_append_new_steps(self, tmp_path, monkeypatch, capsys):
        # Write existing todo.json
        existing = [{
            "id": "step-1", "name": "Done", "details": "...",
            "completed_at": "now", "commit_title": "",
        }]
        todo_path = tmp_path / "todo.json"
        todo_path.write_text(json.dumps(existing), encoding="utf-8")

        xml = _make_xml([
            ("step-2", "New step", "New details"),
            ("step-3", "Another step", "More details"),
        ])
        xml_path = _write_xml(tmp_path, xml)

        monkeypatch.setattr(sys, "argv", ["xml2json_todo.py", str(xml_path), "--append"])
        main()

        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert len(data) == 3
        assert data[0]["id"] == "step-1"
        assert data[1]["id"] == "step-2"
        assert data[2]["id"] == "step-3"
        out = capsys.readouterr().out
        assert "appended 2 step(s)" in out

    def test_append_duplicate_ids_error(self, tmp_path, monkeypatch, capsys):
        existing = [
            {
                "id": "step-1", "name": "Done", "details": "...",
                "completed_at": "now", "commit_title": "",
            },
            {
                "id": "step-2", "name": "In progress", "details": "...",
                "completed_at": "", "commit_title": "",
            },
        ]
        todo_path = tmp_path / "todo.json"
        todo_path.write_text(json.dumps(existing), encoding="utf-8")

        xml = _make_xml([
            ("step-2", "Duplicate", "This ID already exists"),
            ("step-3", "New step", "New details"),
        ])
        xml_path = _write_xml(tmp_path, xml)

        monkeypatch.setattr(sys, "argv", ["xml2json_todo.py", str(xml_path), "--append"])
        with pytest.raises(SystemExit):
            main()

        err = capsys.readouterr().err
        assert "duplicate step ID(s) in append mode" in err
        assert "step-2" in err

    def test_append_no_existing_file(self, tmp_path, monkeypatch, capsys):
        # No todo.json exists — should write fresh
        xml = _make_xml([("step-1", "First", "Details")])
        xml_path = _write_xml(tmp_path, xml)

        monkeypatch.setattr(sys, "argv", ["xml2json_todo.py", str(xml_path), "--append"])
        main()

        todo_path = tmp_path / "todo.json"
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == "step-1"
        out = capsys.readouterr().out
        assert "1 step(s) converted" in out

    def test_append_corrupt_existing_json(self, tmp_path, monkeypatch, capsys):
        todo_path = tmp_path / "todo.json"
        todo_path.write_text("not valid json{{{", encoding="utf-8")

        xml = _make_xml([("step-1", "First", "Details")])
        xml_path = _write_xml(tmp_path, xml)

        monkeypatch.setattr(sys, "argv", ["xml2json_todo.py", str(xml_path), "--append"])
        main()

        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == "step-1"
        out = capsys.readouterr().out
        assert "written (no existing todos)" in out


class TestRmFlag:
    def test_rm_flag_deletes_xml(self, tmp_path, monkeypatch, capsys):
        xml = _make_xml([("step-1", "First", "Details")])
        xml_path = _write_xml(tmp_path, xml)
        assert xml_path.exists()

        monkeypatch.setattr(
            sys, "argv", ["xml2json_todo.py", str(xml_path), "--rm"]
        )
        main()

        assert not xml_path.exists()
        out = capsys.readouterr().out
        assert "1 step(s) converted." in out

    def test_rm_flag_short(self, tmp_path, monkeypatch, capsys):
        xml = _make_xml([("step-1", "First", "Details")])
        xml_path = _write_xml(tmp_path, xml)

        monkeypatch.setattr(
            sys, "argv", ["xml2json_todo.py", "-r", str(xml_path)]
        )
        main()

        assert not xml_path.exists()

    def test_rm_flag_in_append_mode(self, tmp_path, monkeypatch, capsys):
        existing = [{
            "id": "step-1", "name": "Done", "details": "...",
            "completed_at": "now", "commit_title": "",
        }]
        todo_path = tmp_path / "todo.json"
        todo_path.write_text(json.dumps(existing), encoding="utf-8")

        xml = _make_xml([("step-2", "New step", "New details")])
        xml_path = _write_xml(tmp_path, xml)

        monkeypatch.setattr(
            sys,
            "argv",
            ["xml2json_todo.py", "--append", "--rm", str(xml_path)],
        )
        main()

        assert not xml_path.exists()
        data = json.loads(todo_path.read_text(encoding="utf-8"))
        assert len(data) == 2
        out = capsys.readouterr().out
        assert "appended 1 step(s)" in out

    def test_rm_flag_append_short_flags(self, tmp_path, monkeypatch, capsys):
        existing = [{
            "id": "step-1", "name": "Done", "details": "...",
            "completed_at": "now", "commit_title": "",
        }]
        todo_path = tmp_path / "todo.json"
        todo_path.write_text(json.dumps(existing), encoding="utf-8")

        xml = _make_xml([("step-2", "New", "Details")])
        xml_path = _write_xml(tmp_path, xml)

        monkeypatch.setattr(
            sys,
            "argv",
            ["xml2json_todo.py", "-a", "-r", str(xml_path)],
        )
        main()

        assert not xml_path.exists()

    def test_rm_not_added_to_json2xml(self, monkeypatch, capsys):
        import json2xml_todo

        # Verify json2xml USAGE does not mention --rm
        assert "--rm" not in json2xml_todo.USAGE
        assert "-r" not in json2xml_todo.USAGE


class TestMissingArgs:
    def test_no_args(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["xml2json_todo.py"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "xml_file" in err


# ===================== Special character handling =====================


class TestSpecialCharacters:
    def test_unescaped_angle_brackets_in_details(self, tmp_path):
        xml = (
            "<steps>\n"
            "  <step>\n"
            "    <step-id>step-1</step-id>\n"
            "    <step-name>Unescaped</step-name>\n"
            "    <step-markdown-details>\n"
            "Check <repo_root> for config\n"
            "    </step-markdown-details>\n"
            "  </step>\n"
            "</steps>"
        )
        path = _write_xml(tmp_path, xml)

        result = convert_xml_to_todo(path)

        assert result[0]["details"] == "Check <repo_root> for config"

    def test_escaped_entities_in_details(self, tmp_path):
        xml = _make_xml([("ent-1", "Escaped", "Check &lt;tag&gt; entity")])
        path = _write_xml(tmp_path, xml)

        result = convert_xml_to_todo(path)

        # ElementTree decodes &lt; → < and &gt; → >
        assert result[0]["details"] == "Check <tag> entity"

    def test_ampersand_in_details(self, tmp_path):
        xml = (
            "<steps>\n"
            "  <step>\n"
            "    <step-id>step-1</step-id>\n"
            "    <step-name>Ampersand</step-name>\n"
            "    <step-markdown-details>\n"
            "Use foo &amp; bar\n"
            "    </step-markdown-details>\n"
            "  </step>\n"
            "</steps>"
        )
        path = _write_xml(tmp_path, xml)

        result = convert_xml_to_todo(path)

        assert result[0]["details"] == "Use foo & bar"

    def test_mixed_escaped_and_unescaped(self, tmp_path):
        xml = (
            "<steps>\n"
            "  <step>\n"
            "    <step-id>step-1</step-id>\n"
            "    <step-name>Mixed</step-name>\n"
            "    <step-markdown-details>\n"
            "Bare &lt;foo&gt; and escaped &amp;lt;bar&amp;gt; and bare &amp;\n"
            "    </step-markdown-details>\n"
            "  </step>\n"
            "</steps>"
        )
        path = _write_xml(tmp_path, xml)

        result = convert_xml_to_todo(path)

        expected = "Bare <foo> and escaped &lt;bar&gt; and bare &"
        assert result[0]["details"] == expected

    def test_round_trip_from_xml(self, tmp_path):
        import json2xml_todo

        data = [
            {
                "id": "step-1",
                "name": "Special",
                "details": "Use <repo_root> & check &lt;old&gt;",
            },
        ]
        xml_str = json2xml_todo.convert_todo_to_xml(data)
        xml_path = _write_xml(tmp_path, xml_str)

        result = convert_xml_to_todo(xml_path)

        assert len(result) == 1
        assert result[0]["id"] == "step-1"
        assert result[0]["name"] == "Special"
        # json2xml escapes <repo_root> to &lt;repo_root&gt;
        # convert_xml_to_todo decodes entities back
        assert result[0]["details"] == data[0]["details"]


# ===================== --post-action flag =====================


class TestPostActionFlag:
    def test_post_action_without_event_type_error(self, tmp_path, monkeypatch, capsys):
        xml = _make_xml([("step-1", "First", "Details")])
        xml_path = _write_xml(tmp_path, xml)

        monkeypatch.setattr(
            sys, "argv", ["xml2json_todo.py", str(xml_path), "--post-action"]
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "--post-action requires --event-type" in err

    def test_event_type_value_parsed_correctly(self, tmp_path, monkeypatch, capsys):
        """Regression: --event-type create should parse 'create' as value, not positional."""
        xml = _make_xml([("step-1", "First", "Details")])
        xml_path = _write_xml(tmp_path, xml)

        captured = {}

        def _fake_run_post_action(event_type, payload, workdir=None, topic_name=None):
            captured["event_type"] = event_type
            captured["payload"] = payload
            captured["topic_name"] = topic_name

        import hooks
        monkeypatch.setattr(hooks, "run_post_action", _fake_run_post_action)

        main([str(xml_path), "--post-action", "--event-type", "create"])

        assert captured["event_type"] == "create"
        assert captured["payload"]["done"] == 0
        assert captured["payload"]["undone"] == 1

    def test_post_action_done_undone_counts(self, tmp_path, monkeypatch, capsys):
        """Post-action payload should include correct done/undone counts."""
        xml = _make_xml([("step-1", "Done", "Details")])
        xml_path = _write_xml(tmp_path, xml)

        existing = [
            {
                "id": "step-0", "name": "Old", "details": "...",
                "completed_at": "2026-01-01T00:00:00", "commit_title": "",
            },
        ]
        todo_path = tmp_path / "todo.json"
        todo_path.write_text(json.dumps(existing), encoding="utf-8")

        captured = {}

        def _fake_run_post_action(event_type, payload, workdir=None, topic_name=None):
            captured["event_type"] = event_type
            captured["payload"] = payload

        import hooks
        monkeypatch.setattr(hooks, "run_post_action", _fake_run_post_action)

        main([str(xml_path), "--append", "--post-action", "--event-type", "modify"])

        assert captured["payload"]["done"] == 1
        assert captured["payload"]["undone"] == 1

    def test_post_action_with_equals_event_type(self, tmp_path, monkeypatch, capsys):
        """--event-type=VALUE should also work (argparse native)."""
        xml = _make_xml([("step-1", "Step", "Details")])
        xml_path = _write_xml(tmp_path, xml)

        captured = {}

        def _fake_run_post_action(event_type, payload, workdir=None, topic_name=None):
            captured["event_type"] = event_type

        import hooks
        monkeypatch.setattr(hooks, "run_post_action", _fake_run_post_action)

        main([str(xml_path), "--post-action", "--event-type=create"])

        assert captured["event_type"] == "create"

    def test_unknown_flag_error(self, tmp_path, capsys):
        xml = _write_xml(tmp_path, _make_xml([("s", "n", "d")]))

        with pytest.raises(SystemExit) as exc_info:
            main([str(xml), "--bogus"])

        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "unrecognized" in err.lower() or "unknown" in err.lower()

    def test_multiple_extra_args_not_allowed(self, tmp_path, capsys):
        """Two positional args should error."""
        xml = _write_xml(tmp_path, _make_xml([("s", "n", "d")]))

        with pytest.raises(SystemExit) as exc_info:
            main([str(xml), "extra.xml"])

        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "unrecognized arguments" in err.lower() or "error" in err.lower()
