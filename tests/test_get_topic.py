import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import has_undone_tasks
from get_topic import main, resolve_topic


def _make_topic(specs_dir, name, completed=False):
    """Create a topic directory with todo.json."""
    topic = specs_dir / name
    topic.mkdir(parents=True, exist_ok=True)
    task = {
        "id": "t1",
        "name": "task",
        "details": "d",
        "completed_at": "2026-01-01T00:00:00+08:00" if completed else "",
        "commit_title": "done" if completed else "",
    }
    (topic / "todo.json").write_text(
        json.dumps([task]), encoding="utf-8"
    )


class TestHasUndoneTasks:
    def test_no_todo_file(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        assert has_undone_tasks(topic_dir) is False

    def test_invalid_json(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        (topic_dir / "todo.json").write_text("{bad", encoding="utf-8")
        assert has_undone_tasks(topic_dir) is False

    def test_not_a_list(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        (topic_dir / "todo.json").write_text('{}', encoding="utf-8")
        assert has_undone_tasks(topic_dir) is False

    def test_all_completed(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        tasks = [{"id": "1", "completed_at": "2026-01-01T00:00:00Z"}]
        (topic_dir / "todo.json").write_text(json.dumps(tasks), encoding="utf-8")
        assert has_undone_tasks(topic_dir) is False

    def test_has_undone(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        tasks = [{"id": "1", "completed_at": ""}]
        (topic_dir / "todo.json").write_text(json.dumps(tasks), encoding="utf-8")
        assert has_undone_tasks(topic_dir) is True


class TestResolveTopic:
    def test_exact_match(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        result = resolve_topic("2026-05-20-14-30-my-topic", specs)
        assert result == ["2026-05-20-14-30-my-topic"]

    def test_fuzzy_single_match(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-fuzzy-topic")
        _make_topic(specs, "2026-05-20-14-30-other-thing")

        result = resolve_topic("fuzzy", specs)
        assert result == ["2026-05-20-14-30-fuzzy-topic"]

    def test_fuzzy_multiple_matches(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-edit-alpha")
        _make_topic(specs, "2026-05-20-14-30-edit-beta")

        result = resolve_topic("edit", specs)
        assert result == ["2026-05-20-14-30-edit-alpha", "2026-05-20-14-30-edit-beta"]

    def test_fuzzy_no_match(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-something")

        with pytest.raises(SystemExit):
            resolve_topic("nonexistent", specs)

    def test_fuzzy_skips_completed(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done-topic", completed=True)
        _make_topic(specs, "2026-05-20-14-30-active-topic")

        result = resolve_topic("topic", specs)
        assert result == ["2026-05-20-14-30-active-topic"]

    def test_no_name_lists_all_undone(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-alpha")
        _make_topic(specs, "2026-05-20-14-30-beta")
        _make_topic(specs, "2026-05-20-14-30-done", completed=True)

        result = resolve_topic("", specs)
        assert result == ["2026-05-20-14-30-alpha", "2026-05-20-14-30-beta"]

    def test_no_name_no_undone_exits(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done", completed=True)

        with pytest.raises(SystemExit):
            resolve_topic("", specs)

    def test_no_name_specs_dir_missing(self, tmp_path):
        specs = tmp_path / "nonexistent"

        with pytest.raises(SystemExit):
            resolve_topic("", specs)


class TestMainJsonFlag:
    def test_plain_output(self, tmp_path, monkeypatch, capsys):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        monkeypatch.setattr(
            sys, "argv", ["get_topic", "2026-05-20-14-30-my-topic"]
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: str(specs)
        )
        main()
        out = capsys.readouterr().out
        assert out.strip() == "2026-05-20-14-30-my-topic"

    def test_json_single_result(self, tmp_path, monkeypatch, capsys):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        monkeypatch.setattr(
            sys, "argv",
            ["get_topic", "2026-05-20-14-30-my-topic", "--json"],
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: str(specs)
        )
        main()
        out = capsys.readouterr().out
        items = json.loads(out)
        assert len(items) == 1
        assert items[0]["topic_name"] == "2026-05-20-14-30-my-topic"
        assert items[0]["topic_path"] == str(specs / "2026-05-20-14-30-my-topic")

    def test_json_multiple_results(self, tmp_path, monkeypatch, capsys):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-edit-alpha")
        _make_topic(specs, "2026-05-20-14-30-edit-beta")

        monkeypatch.setattr(
            sys, "argv", ["get_topic", "--json", "edit"]
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: str(specs)
        )
        main()
        out = capsys.readouterr().out
        items = json.loads(out)
        assert len(items) == 2
        assert items[0]["topic_name"] == "2026-05-20-14-30-edit-alpha"
        assert items[0]["topic_path"] == str(
            specs / "2026-05-20-14-30-edit-alpha"
        )
        assert items[1]["topic_name"] == "2026-05-20-14-30-edit-beta"
        assert items[1]["topic_path"] == str(
            specs / "2026-05-20-14-30-edit-beta"
        )
