import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import json2xml_todo


@pytest.fixture()
def todo_file(tmp_path):
    path = tmp_path / "todo.json"
    return path


def _write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class TestConvertTodoToXml:
    def test_basic_conversion(self):
        data = [
            {"id": "step-1", "name": "First step", "details": "Do something"},
        ]
        xml = json2xml_todo.convert_todo_to_xml(data)
        assert "<steps>" in xml
        assert "<step-id>step-1</step-id>" in xml
        assert "<step-name>First step</step-name>" in xml
        assert "Do something" in xml
        assert xml.endswith("</steps>\n")

    def test_multiple_steps(self):
        data = [
            {"id": "step-1", "name": "A", "details": "Detail A"},
            {"id": "step-2", "name": "B", "details": "Detail B"},
        ]
        xml = json2xml_todo.convert_todo_to_xml(data)
        assert xml.count("<step>") == 2
        assert xml.count("</step>") == 2

    def test_missing_details_uses_empty(self):
        data = [{"id": "step-1", "name": "No details"}]
        xml = json2xml_todo.convert_todo_to_xml(data)
        assert "<step-markdown-details>\n\n    </step-markdown-details>" in xml


class TestMainJson2Xml:
    def test_converts_and_writes_xml(self, todo_file, monkeypatch, capsys):
        data = [
            {"id": "step-1", "name": "First", "details": "Do first thing"},
            {"id": "step-2", "name": "Second", "details": "Do second thing"},
        ]
        _write(todo_file, data)
        monkeypatch.setattr(sys, "argv", ["prog", str(todo_file)])

        json2xml_todo.main()

        xml_path = todo_file.parent / "todo.xml"
        assert xml_path.exists()
        content = xml_path.read_text(encoding="utf-8")
        assert "<steps>" in content
        assert "<step-id>step-1</step-id>" in content
        assert "<step-id>step-2</step-id>" in content
        out = capsys.readouterr().out
        assert "2 step(s)" in out

    def test_file_not_found_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path / "nope.json")])

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main()
        assert exc_info.value.code == 1

    def test_invalid_json_exits(self, todo_file, monkeypatch):
        todo_file.write_text("{bad json", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["prog", str(todo_file)])

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main()
        assert exc_info.value.code == 1

    def test_non_list_json_exits(self, todo_file, monkeypatch):
        todo_file.write_text('{"key": "value"}', encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["prog", str(todo_file)])

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main()
        assert exc_info.value.code == 1

    def test_empty_array_exits(self, todo_file, monkeypatch):
        _write(todo_file, [])
        monkeypatch.setattr(sys, "argv", ["prog", str(todo_file)])

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main()
        assert exc_info.value.code == 1

    def test_duplicate_id_exits(self, todo_file, monkeypatch):
        data = [
            {"id": "step-1", "name": "A", "details": ""},
            {"id": "step-1", "name": "B", "details": ""},
        ]
        _write(todo_file, data)
        monkeypatch.setattr(sys, "argv", ["prog", str(todo_file)])

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main()
        assert exc_info.value.code == 1

    def test_missing_id_exits(self, todo_file, monkeypatch):
        data = [{"name": "No ID", "details": ""}]
        _write(todo_file, data)
        monkeypatch.setattr(sys, "argv", ["prog", str(todo_file)])

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main()
        assert exc_info.value.code == 1

    def test_missing_name_exits(self, todo_file, monkeypatch):
        data = [{"id": "step-1", "details": ""}]
        _write(todo_file, data)
        monkeypatch.setattr(sys, "argv", ["prog", str(todo_file)])

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main()
        assert exc_info.value.code == 1

    def test_no_tmp_files_after_success(self, todo_file, monkeypatch):
        data = [{"id": "s1", "name": "X", "details": "content"}]
        _write(todo_file, data)
        monkeypatch.setattr(sys, "argv", ["prog", str(todo_file)])

        json2xml_todo.main()

        tmp_files = list(todo_file.parent.glob("*.tmp"))
        assert tmp_files == []

    def test_help_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "-h"])

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main()
        assert exc_info.value.code == 0
