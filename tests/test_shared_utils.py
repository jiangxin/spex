"""Tests for shared utility functions added during scripts-refactor."""

import json
import logging
from unittest.mock import patch

import pytest
from common import (
    escape_xml_preserving_entities,
    escape_xml_text,
    load_and_validate_todo_json,
    validate_unique_ids,
)
from config import safe_update_toml

# ===================== escape_xml_text =====================


class TestEscapeXmlText:
    """Tests for escape_xml_text() shared utility."""

    def test_bare_ampersand(self):
        assert "&amp;" in escape_xml_text("a & b")

    def test_bare_less_than(self):
        assert "&lt;" in escape_xml_text("a < b")

    def test_bare_greater_than(self):
        assert "&gt;" in escape_xml_text("a > b")

    def test_double_escapes_existing_entities(self):
        # escape_xml_text is unconditional — it escapes & in &amp; too
        result = escape_xml_text("already &amp; escaped")
        assert "&amp;amp;" in result

    def test_preserving_variant_keeps_entities(self):
        # escape_xml_preserving_entities does not double-escape
        result = escape_xml_preserving_entities("already &amp; escaped")
        assert "&amp;amp;" not in result
        assert "&amp;" in result

    def test_preserving_variant_mixed_content(self):
        result = escape_xml_preserving_entities("x < y &amp; z > w")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;amp;" not in result

    def test_empty_string(self):
        assert escape_xml_text("") == ""

    def test_no_special_chars(self):
        text = "plain text"
        assert escape_xml_text(text) == text


# ===================== load_and_validate_todo_json =====================


class TestLoadAndValidateTodoJson:
    """Tests for load_and_validate_todo_json() shared utility."""

    def test_valid_file(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text('[{"id": "1", "name": "task"}]', encoding="utf-8")
        result = load_and_validate_todo_json(path)
        assert result == [{"id": "1", "name": "task"}]

    def test_missing_file_exits(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        with pytest.raises(SystemExit):
            load_and_validate_todo_json(path)

    def test_invalid_json_exits(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_and_validate_todo_json(path)

    def test_non_list_exits(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text('{"key": "value"}', encoding="utf-8")
        with pytest.raises(SystemExit):
            load_and_validate_todo_json(path)

    def test_empty_list_exits_by_default(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_and_validate_todo_json(path)

    def test_empty_list_allowed_with_flag(self, tmp_path):
        path = tmp_path / "todo.json"
        path.write_text("[]", encoding="utf-8")
        result = load_and_validate_todo_json(path, allow_empty=True)
        assert result == []


# ===================== validate_unique_ids =====================


class TestValidateUniqueIds:
    """Tests for validate_unique_ids() shared utility."""

    def test_unique_ids_pass(self):
        data = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        # Should not raise
        validate_unique_ids(data)

    def test_empty_id_exits(self):
        data = [{"id": "1"}, {"id": ""}]
        with pytest.raises(SystemExit):
            validate_unique_ids(data)

    def test_missing_id_exits(self):
        data = [{"id": "1"}, {"name": "no id field"}]
        with pytest.raises(SystemExit):
            validate_unique_ids(data)

    def test_duplicate_id_exits(self):
        data = [{"id": "1"}, {"id": "2"}, {"id": "1"}]
        with pytest.raises(SystemExit):
            validate_unique_ids(data)

    def test_non_dict_item_exits(self):
        data = [{"id": "1"}, "not a dict"]
        with pytest.raises(SystemExit):
            validate_unique_ids(data)


# ===================== safe_update_toml =====================


class TestSafeUpdateToml:
    """Tests for safe_update_toml() handling of non-existent files."""

    def test_returns_false_for_nonexistent_file(self, tmp_path):
        path = tmp_path / "nonexistent.toml"
        result = safe_update_toml(path)
        assert result is False


# ===================== archive_single_topic refuses incomplete =====================


class TestArchiveSingleTopicIncomplete:
    """Test that archive_single_topic refuses incomplete topics."""

    def test_refuses_incomplete_without_force(self, tmp_path, caplog):
        from archive import archive_single_topic

        specs = tmp_path / "specs"
        topic = specs / "wip-topic"
        topic.mkdir(parents=True)
        todo = [
            {"id": "1", "name": "Done", "details": "",
             "completed_at": "2026-01-01", "commit_title": "x"},
            {"id": "2", "name": "Pending", "details": "",
             "completed_at": "", "commit_title": ""},
        ]
        (topic / "todo.json").write_text(
            json.dumps(todo), encoding="utf-8"
        )
        archives = tmp_path / "archives"

        with caplog.at_level(logging.INFO):
            result = archive_single_topic("wip-topic", specs, archives)

        assert result is None
        assert not (archives / "wip-topic").exists()
        assert "not completed" in caplog.text

    def test_archives_incomplete_with_force(self, tmp_path, capsys):
        from archive import archive_single_topic

        specs = tmp_path / "specs"
        topic = specs / "wip-topic"
        topic.mkdir(parents=True)
        todo = [
            {"id": "1", "name": "Done", "details": "",
             "completed_at": "2026-01-01", "commit_title": "x"},
            {"id": "2", "name": "Pending", "details": "",
             "completed_at": "", "commit_title": ""},
        ]
        (topic / "todo.json").write_text(
            json.dumps(todo), encoding="utf-8"
        )
        archives = tmp_path / "archives"

        with patch("branch.branch_exists", return_value=False):
            result = archive_single_topic(
                "wip-topic", specs, archives, force=True
            )

        assert result == archives / "wip-topic"
        assert (archives / "wip-topic").is_dir()
