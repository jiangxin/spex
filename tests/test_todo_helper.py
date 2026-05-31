"""Unit tests for todo_helper.py — JSON CRUD operations."""

from __future__ import annotations

import json

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

    def test_xml_flag_with_topic(self, tmp_path, monkeypatch):
        topic_dir = tmp_path / "my-topic"
        topic_dir.mkdir()

        monkeypatch.setattr(
            todo_helper, "resolve_topic_dir",
            lambda name, **kw: topic_dir,
        )
        with pytest.raises(NotImplementedError, match="XML"):
            todo_helper.main([
                "--topic", "my-topic", "--xml", "validate",
            ])

    def test_todo_file_xml_extension_auto_detects(self, tmp_path):
        xml_file = tmp_path / "todo.xml"
        xml_file.write_text("<tasks/>", encoding="utf-8")
        with pytest.raises(NotImplementedError, match="XML"):
            todo_helper.main([
                "--todo-file", str(xml_file), "validate",
            ])


# -----------------------------------------------------------------------
# validate
# -----------------------------------------------------------------------
class TestValidate:
    def test_valid_file(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "validate",
        ])
        assert "OK" in capsys.readouterr().out

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

    def test_empty_file_ok(self, todo_file, capsys):
        _write(todo_file, [])
        todo_helper.main([
            "--todo-file", str(todo_file), "validate",
        ])
        assert "OK" in capsys.readouterr().out


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


# -----------------------------------------------------------------------
# edit
# -----------------------------------------------------------------------
class TestEdit:
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
        assert "✅" in out  # checkmark
        assert "step-1" in out
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
        assert "⬜" in out  # white square
        assert "step-2" in out
        # Empty fields should be skipped
        assert "completed_at:" not in out
        assert "commit_title:" not in out

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
        assert "details:" not in out
        assert "completed_at:" not in out
        assert "commit_title:" not in out

    def test_show_markdown_long_text_wrapping(
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
            if "details:" in line
            or (line.startswith("    ") and "word" in line)
        ]
        # The long text should have been wrapped to multiple lines
        assert len(detail_lines) > 1


# -----------------------------------------------------------------------
# remove-undone
# -----------------------------------------------------------------------
class TestRemoveUndone:
    def test_removes_incomplete_items(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "remove-undone",
        ])
        result = _read(todo_file)
        assert len(result) == 2
        assert all(i["completed_at"] for i in result)
        out = capsys.readouterr().out
        assert "1 undone" in out

    def test_all_complete_no_change(self, todo_file, capsys):
        data = [SAMPLE_DATA[0], SAMPLE_DATA[2]]  # both completed
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "remove-undone",
        ])
        result = _read(todo_file)
        assert len(result) == 2
        out = capsys.readouterr().out
        assert "0 undone" in out


# -----------------------------------------------------------------------
# Help flag
# -----------------------------------------------------------------------
class TestHelp:
    def test_main_help(self):
        with pytest.raises(SystemExit) as exc:
            todo_helper.main(["-h"])
        assert exc.value.code == 0
