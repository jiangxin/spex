"""Unit tests for todo_helper.py — JSON CRUD operations."""

from __future__ import annotations

import json
import logging

import pytest
import todo_helper


@pytest.fixture()
def todo_file(tmp_path):
    return tmp_path / "todo.json"


def _write(path, data):
    path.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8",
    )


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


SAMPLE_DATA = [
    {
        "id": "step-1",
        "name": "First step",
        "details": "Do the first thing",
        "completed_at": "2026-01-01T10:00:00+08:00",
        "commit_title": "feat: first step",
    },
    {
        "id": "step-2",
        "name": "Second step",
        "details": "Do the second thing",
        "completed_at": "",
        "commit_title": "",
    },
    {
        "id": "step-3",
        "name": "Third step",
        "details": "Do the third thing",
        "completed_at": "2026-01-02T12:00:00+08:00",
        "commit_title": "feat: third step",
    },
]


# -----------------------------------------------------------------------
# File locating
# -----------------------------------------------------------------------
class TestFileLocating:
    def test_topic_resolves_todo_json(self, tmp_path, monkeypatch):
        topic_dir = tmp_path / "my-topic"
        topic_dir.mkdir()
        todo = topic_dir / "todo.json"
        _write(todo, SAMPLE_DATA)

        monkeypatch.setattr(
            todo_helper, "resolve_topic_dir",
            lambda name, **kw: topic_dir,
        )
        todo_helper.main([
            "--topic", "my-topic", "validate",
        ])

    def test_todo_file_direct_path(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "validate",
        ])

    def test_both_topic_and_todo_file_error(self, todo_file):
        with pytest.raises(SystemExit):
            todo_helper.main([
                "--topic", "x",
                "--todo-file", str(todo_file),
                "validate",
            ])

    def test_neither_topic_nor_todo_file_error(self):
        with pytest.raises(SystemExit):
            todo_helper.main(["validate"])

    def test_xml_flag_with_topic(
        self, tmp_path, monkeypatch, caplog,
    ):
        topic_dir = tmp_path / "my-topic"
        topic_dir.mkdir()
        xml_file = topic_dir / "todo.xml"
        xml_file.write_text(
            "<todo></todo>\n", encoding="utf-8",
        )

        monkeypatch.setattr(
            todo_helper, "resolve_topic_dir",
            lambda name, **kw: topic_dir,
        )
        with caplog.at_level(logging.INFO):
            todo_helper.main([
                "--topic", "my-topic", "--xml", "validate",
            ])
        assert "OK" in caplog.text

    def test_todo_file_xml_extension_auto_detects(
        self, tmp_path,
    ):
        xml_file = tmp_path / "todo.xml"
        xml_file.write_text("<steps/>", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(xml_file), "validate",
            ])
        assert exc.value.code == 1


# -----------------------------------------------------------------------
# validate
# -----------------------------------------------------------------------
class TestValidate:
    def test_valid_file(self, todo_file, caplog):
        _write(todo_file, SAMPLE_DATA)
        with caplog.at_level(logging.INFO):
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert "OK" in caplog.text

    def test_duplicate_ids_fail(self, todo_file):
        data = [
            {"id": "s1", "name": "A", "details": "",
             "completed_at": "", "commit_title": ""},
            {"id": "s1", "name": "B", "details": "",
             "completed_at": "", "commit_title": ""},
        ]
        _write(todo_file, data)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert exc.value.code == 1

    def test_missing_required_field_fails(self, todo_file):
        data = [{"id": "s1", "name": "A"}]  # missing details etc.
        _write(todo_file, data)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert exc.value.code == 1

    def test_empty_file_ok(self, todo_file, caplog):
        _write(todo_file, [])
        with caplog.at_level(logging.INFO):
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert "OK" in caplog.text


# -----------------------------------------------------------------------
# append
# -----------------------------------------------------------------------
class TestAppend:
    def test_append_to_existing(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--id", "step-4",
            "--name", "Fourth step",
            "--details", "Do the fourth thing",
        ])
        result = _read(todo_file)
        assert len(result) == 4
        assert result[-1]["id"] == "step-4"
        assert result[-1]["name"] == "Fourth step"
        assert result[-1]["completed_at"] == ""
        assert result[-1]["commit_title"] == ""

    def test_append_creates_new_file(self, todo_file):
        assert not todo_file.exists()
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--id", "step-1",
            "--name", "First",
            "--details", "Details here",
        ])
        result = _read(todo_file)
        assert len(result) == 1
        assert result[0]["id"] == "step-1"

    def test_append_duplicate_id_fails(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "append",
                "--id", "step-1",
                "--name", "Dup",
                "--details", "Dup details",
            ])
        assert exc.value.code == 1

    def test_append_with_optional_fields(self, todo_file):
        _write(todo_file, [])
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--id", "s1",
            "--name", "Done task",
            "--details", "Already done",
            "--completed_at", "2026-05-30",
            "--commit_title", "feat: done",
        ])
        result = _read(todo_file)
        assert result[0]["completed_at"] == "2026-05-30"
        assert result[0]["commit_title"] == "feat: done"

    def test_append_details_from_stdin(self, todo_file, monkeypatch):
        _write(todo_file, [])
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(
            "Multi-line details\n\n- Item 1\n- Item 2\n",
        ))
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--id", "s1", "--name", "Stdin step",
            "--details-from-stdin",
        ])
        result = _read(todo_file)
        assert "Multi-line details" in result[0]["details"]
        assert "- Item 1" in result[0]["details"]

    def test_append_no_details_fails(self, todo_file):
        _write(todo_file, [])
        with pytest.raises(SystemExit):
            todo_helper.main([
                "--todo-file", str(todo_file), "append",
                "--id", "s1", "--name", "No details",
            ])


# -----------------------------------------------------------------------
# edit
# -----------------------------------------------------------------------
class TestEdit:
    def test_edit_details_from_stdin(self, todo_file, monkeypatch):
        _write(todo_file, SAMPLE_DATA)
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(
            "Updated multi-line\n\n- New item\n",
        ))
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "step-1", "--details-from-stdin",
        ])
        result = _read(todo_file)
        step1 = [i for i in result if i["id"] == "step-1"][0]
        assert "Updated multi-line" in step1["details"]
        assert "- New item" in step1["details"]
        assert step1["name"] == SAMPLE_DATA[0]["name"]

    def test_update_specific_fields(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "step-2",
            "--name", "Updated name",
        ])
        result = _read(todo_file)
        step2 = [i for i in result if i["id"] == "step-2"][0]
        assert step2["name"] == "Updated name"
        # Unchanged fields remain
        assert step2["details"] == "Do the second thing"
        assert step2["completed_at"] == ""

    def test_unspecified_fields_unchanged(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        original = SAMPLE_DATA[0].copy()
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "step-1",
            "--details", "New details",
        ])
        result = _read(todo_file)
        step1 = [i for i in result if i["id"] == "step-1"][0]
        assert step1["name"] == original["name"]
        assert step1["completed_at"] == original["completed_at"]
        assert step1["commit_title"] == original["commit_title"]
        assert step1["details"] == "New details"

    def test_id_not_found_fails(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "edit",
                "--id", "no-such-id",
                "--name", "X",
            ])
        assert exc.value.code == 1


# -----------------------------------------------------------------------
# edit --completed_at now
# -----------------------------------------------------------------------
class TestEditCompletedAtNow:
    def test_edit_completed_at_now(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "step-2",
            "--completed_at", "now",
        ])
        result = _read(todo_file)
        step2 = [i for i in result if i["id"] == "step-2"][0]
        assert step2["completed_at"].startswith("2026-")

    def test_edit_completed_at_explicit_value(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "step-2",
            "--completed_at", "2026-01-01T00:00:00",
        ])
        result = _read(todo_file)
        step2 = [i for i in result if i["id"] == "step-2"][0]
        assert step2["completed_at"] == "2026-01-01T00:00:00"


# -----------------------------------------------------------------------
# append --completed_at now
# -----------------------------------------------------------------------
class TestAppendCompletedAtNow:
    def test_append_completed_at_now(self, todo_file):
        _write(todo_file, [])
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--id", "s1",
            "--name", "Task done now",
            "--details", "Details",
            "--completed_at", "now",
        ])
        result = _read(todo_file)
        assert result[0]["completed_at"].startswith("2026-")


# -----------------------------------------------------------------------
# remove
# -----------------------------------------------------------------------
class TestRemove:
    def test_remove_by_id(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "remove",
            "--id", "step-2",
        ])
        result = _read(todo_file)
        assert len(result) == 2
        ids = [i["id"] for i in result]
        assert "step-2" not in ids

    def test_id_not_found_fails(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "remove",
                "--id", "no-such-id",
            ])
        assert exc.value.code == 1


# -----------------------------------------------------------------------
# show
# -----------------------------------------------------------------------
class TestShow:
    def test_show_all_items_json(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert len(result) == 3

    def test_show_done_filter(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show", "--done",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert len(result) == 2
        assert all(i["completed_at"] for i in result)

    def test_show_undone_filter(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show", "--undone",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert len(result) == 1
        assert result[0]["id"] == "step-2"

    def test_done_and_undone_mutual_exclusion(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit):
            todo_helper.main([
                "--todo-file", str(todo_file), "show",
                "--done", "--undone",
            ])

    def test_show_format_json(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA[:1])
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "json",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result[0]["id"] == "step-1"

    def test_show_format_markdown_done(self, todo_file, capsys):
        data = [SAMPLE_DATA[0]]  # completed item
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "1. ✅ step-1\n" in out
        assert "   - name: First step\n" in out
        assert "completed_at:" in out
        assert "commit_title:" in out

    def test_show_format_markdown_undone(self, todo_file, capsys):
        data = [SAMPLE_DATA[1]]  # incomplete item
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "1. 🔲 step-2\n" in out
        assert "   - name: Second step\n" in out
        assert "completed_at:" not in out
        assert "commit_title:" not in out

    def test_show_markdown_numbered_list(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "1. ✅ step-1\n" in out
        assert "2. 🔲 step-2\n" in out
        assert "3. ✅ step-3\n" in out

    def test_show_markdown_empty_fields_skipped(
        self, todo_file, capsys,
    ):
        data = [{
            "id": "s1", "name": "Test",
            "details": "", "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "1. 🔲 s1\n" in out
        assert "   - name: Test\n" in out
        assert "details:" not in out
        assert "completed_at:" not in out
        assert "commit_title:" not in out

    def test_show_markdown_no_wrap_by_default(
        self, todo_file, capsys,
    ):
        long_details = "word " * 30  # ~150 chars
        data = [{
            "id": "s1", "name": "Test",
            "details": long_details.strip(),
            "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        detail_lines = [
            line for line in out.split("\n")
            if "details:" in line or "word" in line
        ]
        assert len(detail_lines) == 1
        assert detail_lines[0].startswith("   - details: word")

    def test_show_markdown_wrap(
        self, todo_file, capsys,
    ):
        long_details = "word " * 30  # ~150 chars
        data = [{
            "id": "s1", "name": "Test",
            "details": long_details.strip(),
            "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown", "--wrap",
        ])
        out = capsys.readouterr().out
        detail_lines = [
            line for line in out.split("\n")
            if "details:" in line
            or (line.startswith("              ") and "word" in line)
        ]
        assert len(detail_lines) > 1
        for line in out.split("\n"):
            assert len(line) <= 80

    def test_show_markdown_multiline_details(
        self, todo_file, capsys,
    ):
        details = "First line\nSecond line\nThird line"
        data = [{
            "id": "s1", "name": "Test",
            "details": details,
            "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "   - details: |\n" in out
        assert "       First line\n" in out
        assert "       Second line\n" in out
        assert "       Third line" in out

    def test_show_markdown_multiline_details_wrap(
        self, todo_file, capsys,
    ):
        details = "First line\nSecond line\nThird line"
        data = [{
            "id": "s1", "name": "Test",
            "details": details,
            "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown", "--wrap",
        ])
        out = capsys.readouterr().out
        assert "   - details: |\n" in out
        assert "       First line\n" in out
        assert "       Second line\n" in out
        assert "       Third line" in out
        for line in out.split("\n"):
            assert len(line) <= 80


# -----------------------------------------------------------------------
# remove-undone
# -----------------------------------------------------------------------
# -----------------------------------------------------------------------
# Help flag
# -----------------------------------------------------------------------
class TestHelp:
    def test_main_help(self):
        with pytest.raises(SystemExit) as exc:
            todo_helper.main(["-h"])
        assert exc.value.code == 0

    def test_main_help_long(self, capsys):
        with pytest.raises(SystemExit) as exc:
            todo_helper.main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Subcommands:" in out

    def test_no_args_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([])
        assert exc.value.code == 0
        err = capsys.readouterr().err
        assert "Subcommands:" in err

    def test_subcmd_help_shows_subcmd_usage(self, capsys, todo_file):
        """--help after a subcommand shows subcommand-specific help."""
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file),
                "edit", "--help",
            ])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "edit" in out
        assert "Subcommands:" not in out

    def test_subcmd_help_short_flag(self, capsys, todo_file):
        """Short -h after a subcommand shows subcommand-specific help."""
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file),
                "append", "-h",
            ])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "append" in out
        assert "Subcommands:" not in out


# -----------------------------------------------------------------------
# XML format
# -----------------------------------------------------------------------
SAMPLE_XML = """\
<todo>
  <step>
    <step-id>step-1</step-id>
    <step-name>First step</step-name>
    <step-details>Do the first thing</step-details>
    <completed-at>2026-01-01T10:00:00+08:00</completed-at>
    <commit-title>feat: first step</commit-title>
  </step>
  <step>
    <step-id>step-2</step-id>
    <step-name>Second step</step-name>
    <step-details>Do the second thing</step-details>
    <completed-at></completed-at>
    <commit-title></commit-title>
  </step>
  <step>
    <step-id>step-3</step-id>
    <step-name>Third step</step-name>
    <step-details>Do the third thing</step-details>
    <completed-at>2026-01-02T12:00:00+08:00</completed-at>
    <commit-title>feat: third step</commit-title>
  </step>
</todo>
"""


# -----------------------------------------------------------------------
# xml2json / json2xml conversion
# -----------------------------------------------------------------------
CONVERSION_XML = """\
<todo>
  <step>
    <step-id>step-1</step-id>
    <step-name>First</step-name>
    <step-details>Details one</step-details>
    <completed-at></completed-at>
    <commit-title></commit-title>
  </step>
  <step>
    <step-id>step-2</step-id>
    <step-name>Second</step-name>
    <step-details>Details two</step-details>
    <completed-at>2026-01-01</completed-at>
    <commit-title>feat: second</commit-title>
  </step>
</todo>
"""

CONVERSION_JSON = [
    {
        "id": "step-1",
        "name": "First",
        "details": "Details one",
        "completed_at": "",
        "commit_title": "",
    },
    {
        "id": "step-2",
        "name": "Second",
        "details": "Details two",
        "completed_at": "2026-01-01",
        "commit_title": "feat: second",
    },
]


class TestConversion:
    def test_xml2json_converts(self, tmp_path, caplog):
        xml_file = tmp_path / "todo.xml"
        xml_file.write_text(CONVERSION_XML, encoding="utf-8")
        with caplog.at_level(logging.INFO):
            todo_helper.main([
                "--todo-file", str(xml_file), "xml2json",
            ])
        json_file = tmp_path / "todo.json"
        assert json_file.exists()
        result = _read(json_file)
        assert len(result) == 2
        assert result[0]["id"] == "step-1"
        assert result[1]["id"] == "step-2"
        assert result[1]["completed_at"] == "2026-01-01"
        assert "Converted" in caplog.text

    def test_xml2json_rm(self, tmp_path):
        xml_file = tmp_path / "todo.xml"
        xml_file.write_text(CONVERSION_XML, encoding="utf-8")
        todo_helper.main([
            "--todo-file", str(xml_file), "xml2json", "--rm",
        ])
        json_file = tmp_path / "todo.json"
        assert json_file.exists()
        assert not xml_file.exists()
        result = _read(json_file)
        assert len(result) == 2

    def test_xml2json_output_path(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        xml_file = subdir / "tasks.xml"
        xml_file.write_text(CONVERSION_XML, encoding="utf-8")
        todo_helper.main([
            "--todo-file", str(xml_file), "xml2json",
        ])
        expected = subdir / "tasks.json"
        assert expected.exists()
        assert not (tmp_path / "tasks.json").exists()

    def test_json2xml_converts(self, tmp_path, caplog):
        json_file = tmp_path / "todo.json"
        _write(json_file, CONVERSION_JSON)
        with caplog.at_level(logging.INFO):
            todo_helper.main([
                "--todo-file", str(json_file), "json2xml",
            ])
        xml_file = tmp_path / "todo.xml"
        assert xml_file.exists()
        data = todo_helper.load_todo_xml(xml_file)
        assert len(data) == 2
        assert data[0]["id"] == "step-1"
        assert data[1]["completed_at"] == "2026-01-01"
        assert "Converted" in caplog.text

    def test_json2xml_rm(self, tmp_path):
        json_file = tmp_path / "todo.json"
        _write(json_file, CONVERSION_JSON)
        todo_helper.main([
            "--todo-file", str(json_file), "json2xml", "--rm",
        ])
        xml_file = tmp_path / "todo.xml"
        assert xml_file.exists()
        assert not json_file.exists()
        data = todo_helper.load_todo_xml(xml_file)
        assert len(data) == 2

    def test_json2xml_roundtrip(self, tmp_path):
        json_file = tmp_path / "todo.json"
        _write(json_file, CONVERSION_JSON)
        # JSON -> XML
        todo_helper.main([
            "--todo-file", str(json_file), "json2xml",
        ])
        xml_file = tmp_path / "todo.xml"
        assert xml_file.exists()
        # XML -> JSON (writes back to todo.json via stem)
        # Use the xml file as source
        todo_helper.main([
            "--todo-file", str(xml_file), "xml2json",
        ])
        # xml2json writes to todo.json (same stem)
        result = _read(json_file)
        assert len(result) == len(CONVERSION_JSON)
        for i, expected in enumerate(CONVERSION_JSON):
            for key in (
                "id", "name", "details",
                "completed_at", "commit_title",
            ):
                assert result[i][key] == expected[key]


class TestXmlFormat:
    @pytest.fixture()
    def xml_file(self, tmp_path):
        return tmp_path / "todo.xml"

    def test_load_todo_xml_valid(self, xml_file):
        xml_file.write_text(SAMPLE_XML, encoding="utf-8")
        data = todo_helper.load_todo_xml(xml_file)
        assert len(data) == 3
        assert data[0]["id"] == "step-1"
        assert data[0]["name"] == "First step"
        assert data[0]["details"] == "Do the first thing"
        assert data[0]["completed_at"] == (
            "2026-01-01T10:00:00+08:00"
        )
        assert data[0]["commit_title"] == "feat: first step"
        assert data[1]["completed_at"] == ""
        assert data[1]["commit_title"] == ""

    def test_load_todo_xml_missing_file(self, tmp_path):
        result = todo_helper.load_todo_xml(
            tmp_path / "nonexistent.xml",
        )
        assert result == []

    def test_load_todo_xml_empty_file(self, xml_file):
        xml_file.write_text("", encoding="utf-8")
        result = todo_helper.load_todo_xml(xml_file)
        assert result == []

    def test_load_todo_xml_wrong_root(self, xml_file):
        xml_file.write_text(
            "<steps><step/></steps>", encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc:
            todo_helper.load_todo_xml(xml_file)
        assert exc.value.code == 1

    def test_write_todo_xml_roundtrip(self, xml_file):
        original = [
            {
                "id": "s1", "name": "Task one",
                "details": "Details for one",
                "completed_at": "2026-01-01",
                "commit_title": "feat: one",
            },
            {
                "id": "s2", "name": "Task two",
                "details": "Details for two",
                "completed_at": "",
                "commit_title": "",
            },
        ]
        todo_helper.write_todo_xml(xml_file, original)
        loaded = todo_helper.load_todo_xml(xml_file)
        assert len(loaded) == 2
        for i in range(2):
            for key in (
                "id", "name", "details",
                "completed_at", "commit_title",
            ):
                assert loaded[i][key] == original[i][key]

    def test_validate_xml(self, xml_file, caplog):
        xml_file.write_text(SAMPLE_XML, encoding="utf-8")
        with caplog.at_level(logging.INFO):
            todo_helper.main([
                "--todo-file", str(xml_file), "validate",
            ])
        assert "OK" in caplog.text

    def test_append_to_xml(self, xml_file):
        xml_file.write_text(SAMPLE_XML, encoding="utf-8")
        todo_helper.main([
            "--todo-file", str(xml_file), "append",
            "--id", "step-4",
            "--name", "Fourth step",
            "--details", "Do the fourth thing",
        ])
        data = todo_helper.load_todo_xml(xml_file)
        assert len(data) == 4
        assert data[-1]["id"] == "step-4"
        assert data[-1]["name"] == "Fourth step"

    def test_edit_xml_entry(self, xml_file):
        xml_file.write_text(SAMPLE_XML, encoding="utf-8")
        todo_helper.main([
            "--todo-file", str(xml_file), "edit",
            "--id", "step-2",
            "--name", "Updated name",
        ])
        data = todo_helper.load_todo_xml(xml_file)
        step2 = [
            e for e in data if e["id"] == "step-2"
        ][0]
        assert step2["name"] == "Updated name"
        assert step2["details"] == "Do the second thing"

    def test_show_from_xml(self, xml_file, capsys):
        xml_file.write_text(SAMPLE_XML, encoding="utf-8")
        todo_helper.main([
            "--todo-file", str(xml_file), "show",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert len(result) == 3
        assert result[0]["id"] == "step-1"



class TestSubcommandHelp:
    """Tests for subcommand -h/--help working without --topic/--todo-file."""

    def test_validate_help_exits_0(self, capsys):
        """validate -h should show help and exit 0."""
        with pytest.raises(SystemExit) as exc_info:
            todo_helper.main(["validate", "-h"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "validate" in out.lower()

    def test_append_help_exits_0(self, capsys):
        """append -h should show usage and exit 0."""
        with pytest.raises(SystemExit) as exc_info:
            todo_helper.main(["append", "-h"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "--id" in out

    def test_show_help_exits_0(self, capsys):
        """show -h should show usage and exit 0."""
        with pytest.raises(SystemExit) as exc_info:
            todo_helper.main(["show", "-h"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "--format" in out

    def test_no_locator_errors(self, caplog):
        """Without --topic or --todo-file, should error with exit 2."""
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                todo_helper.main(["validate"])
        assert exc_info.value.code == 2
        assert "--topic" in caplog.text
        assert "--todo-file" in caplog.text
