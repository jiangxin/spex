import json

import json2xml_todo
import pytest


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
    def test_converts_and_writes_xml(self, todo_file, capsys):
        data = [
            {"id": "step-1", "name": "First", "details": "Do first thing"},
            {"id": "step-2", "name": "Second", "details": "Do second thing"},
        ]
        _write(todo_file, data)

        json2xml_todo.main([str(todo_file)])

        xml_path = todo_file.parent / "todo.xml"
        assert xml_path.exists()
        content = xml_path.read_text(encoding="utf-8")
        assert "<steps>" in content
        assert "<step-id>step-1</step-id>" in content
        assert "<step-id>step-2</step-id>" in content
        out = capsys.readouterr().out
        assert "2 step(s)" in out

    def test_file_not_found_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main([str(tmp_path / "nope.json")])
        assert exc_info.value.code == 1

    def test_invalid_json_exits(self, todo_file):
        todo_file.write_text("{bad json", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main([str(todo_file)])
        assert exc_info.value.code == 1

    def test_non_list_json_exits(self, todo_file):
        todo_file.write_text('{"key": "value"}', encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main([str(todo_file)])
        assert exc_info.value.code == 1

    def test_empty_array_exits(self, todo_file):
        _write(todo_file, [])

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main([str(todo_file)])
        assert exc_info.value.code == 1

    def test_duplicate_id_exits(self, todo_file):
        data = [
            {"id": "step-1", "name": "A", "details": ""},
            {"id": "step-1", "name": "B", "details": ""},
        ]
        _write(todo_file, data)

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main([str(todo_file)])
        assert exc_info.value.code == 1

    def test_missing_id_exits(self, todo_file):
        data = [{"name": "No ID", "details": ""}]
        _write(todo_file, data)

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main([str(todo_file)])
        assert exc_info.value.code == 1

    def test_missing_name_exits(self, todo_file):
        data = [{"id": "step-1", "details": ""}]
        _write(todo_file, data)

        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main([str(todo_file)])
        assert exc_info.value.code == 1

    def test_no_tmp_files_after_success(self, todo_file):
        data = [{"id": "s1", "name": "X", "details": "content"}]
        _write(todo_file, data)

        json2xml_todo.main([str(todo_file)])

        tmp_files = list(todo_file.parent.glob("*.tmp"))
        assert tmp_files == []

    def test_help_flag(self):
        with pytest.raises(SystemExit) as exc_info:
            json2xml_todo.main(["-h"])
        assert exc_info.value.code == 0


class TestEscapeXmlText:
    def test_escape_angle_brackets(self):
        result = json2xml_todo.escape_xml_text("<repo_root>")
        assert result == "&lt;repo_root&gt;"

    def test_escape_ampersand(self):
        result = json2xml_todo.escape_xml_text("a & b")
        assert result == "a &amp; b"

    def test_escape_all_special_chars(self):
        result = json2xml_todo.escape_xml_text("x < y > z & w")
        assert result == "x &lt; y &gt; z &amp; w"

    def test_no_special_chars_unchanged(self):
        result = json2xml_todo.escape_xml_text("plain text")
        assert result == "plain text"

    def test_already_escaped_text(self):
        result = json2xml_todo.escape_xml_text("&lt;tag&gt;")
        # The & in &lt; is itself escaped, so it becomes &amp;lt;
        assert result == "&amp;lt;tag&amp;gt;"


class TestRoundTrip:
    def test_round_trip_with_special_chars(self):
        import xml.etree.ElementTree as ET

        data = [
            {
                "id": "step-1",
                "name": "Special chars test",
                "details": "Check <repo_root> and use & for refs",
            },
        ]
        xml_str = json2xml_todo.convert_todo_to_xml(data)
        tree = ET.fromstring(xml_str)
        details = tree.find("step/step-markdown-details")
        # ElementTree auto-decodes entities
        assert details.text.strip() == "Check <repo_root> and use & for refs"
