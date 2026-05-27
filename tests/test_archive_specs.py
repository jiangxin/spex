import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import archive_specs
from archive_specs import archive_single_topic, find_completed_topics, move_topic
from common import is_topic_completed


def _write_todo(topic_dir, tasks):
    """Write a todo.json file into topic_dir."""
    topic_dir.mkdir(parents=True, exist_ok=True)
    todo_path = topic_dir / "todo.json"
    todo_path.write_text(json.dumps(tasks), encoding="utf-8")


def _make_task(task_id, completed=True):
    """Create a single todo item dict."""
    return {
        "id": task_id,
        "name": f"Task {task_id}",
        "details": "Some details",
        "completed_at": "2026-01-01T00:00:00Z" if completed else "",
        "commit_title": f"feat: task {task_id}" if completed else "",
    }


class TestIsTopicCompleted:
    """Tests for is_topic_completed."""

    def test_all_completed_returns_true(self, tmp_path):
        topic = tmp_path / "my-topic"
        _write_todo(topic, [_make_task("1"), _make_task("2")])

        assert is_topic_completed(topic) is True

    def test_partial_completed_returns_false(self, tmp_path):
        topic = tmp_path / "my-topic"
        _write_todo(topic, [_make_task("1"), _make_task("2", completed=False)])

        assert is_topic_completed(topic) is False

    def test_missing_todo_returns_false(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir()

        assert is_topic_completed(topic) is False

    def test_empty_list_returns_false(self, tmp_path):
        topic = tmp_path / "my-topic"
        _write_todo(topic, [])

        assert is_topic_completed(topic) is False

    def test_invalid_json_returns_false(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir(parents=True, exist_ok=True)
        (topic / "todo.json").write_text("not json", encoding="utf-8")

        assert is_topic_completed(topic) is False


class TestFindCompletedTopics:
    """Tests for find_completed_topics."""

    def test_returns_only_completed(self, tmp_path):
        specs = tmp_path / "specs"
        # Completed topic
        _write_todo(specs / "done-topic", [_make_task("1")])
        # Incomplete topic
        _write_todo(
            specs / "wip-topic",
            [_make_task("1"), _make_task("2", completed=False)],
        )
        # No todo.json
        (specs / "empty-topic").mkdir(parents=True)

        result = find_completed_topics(specs)

        assert len(result) == 1
        assert result[0].name == "done-topic"

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        result = find_completed_topics(tmp_path / "nonexistent")

        assert result == []

    def test_multiple_completed_sorted(self, tmp_path):
        specs = tmp_path / "specs"
        _write_todo(specs / "beta-topic", [_make_task("1")])
        _write_todo(specs / "alpha-topic", [_make_task("1")])

        result = find_completed_topics(specs)

        assert [d.name for d in result] == ["alpha-topic", "beta-topic"]

    def test_filters_by_current_workdir(self, tmp_path):
        specs = tmp_path / "specs"
        # Topic matching current workdir
        topic_a = specs / "topic-a"
        _write_todo(topic_a, [_make_task("1")])
        (topic_a / "meta.json").write_text(
            json.dumps({"workdir": "/repo/a"}), encoding="utf-8"
        )
        # Topic for a different workdir
        topic_b = specs / "topic-b"
        _write_todo(topic_b, [_make_task("1")])
        (topic_b / "meta.json").write_text(
            json.dumps({"workdir": "/repo/b"}), encoding="utf-8"
        )
        # Topic without workdir (should be included)
        topic_c = specs / "topic-c"
        _write_todo(topic_c, [_make_task("1")])

        result = find_completed_topics(specs, current_workdir="/repo/a")

        names = [d.name for d in result]
        assert "topic-a" in names
        assert "topic-c" in names
        assert "topic-b" not in names

    def test_no_filter_when_workdir_is_none(self, tmp_path):
        specs = tmp_path / "specs"
        topic_a = specs / "topic-a"
        _write_todo(topic_a, [_make_task("1")])
        (topic_a / "meta.json").write_text(
            json.dumps({"workdir": "/repo/a"}), encoding="utf-8"
        )
        topic_b = specs / "topic-b"
        _write_todo(topic_b, [_make_task("1")])
        (topic_b / "meta.json").write_text(
            json.dumps({"workdir": "/repo/b"}), encoding="utf-8"
        )

        result = find_completed_topics(specs, current_workdir=None)

        assert len(result) == 2


class TestMoveTopic:
    """Tests for move_topic."""

    def test_normal_move(self, tmp_path):
        topic = tmp_path / "specs" / "my-topic"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"
        archives.mkdir()

        dest = move_topic(topic, archives)

        assert dest == archives / "my-topic"
        assert dest.is_dir()
        assert not topic.exists()

    def test_conflict_appends_suffix(self, tmp_path):
        topic = tmp_path / "specs" / "my-topic"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"
        # Pre-existing conflict
        (archives / "my-topic").mkdir(parents=True)

        dest = move_topic(topic, archives)

        assert dest == archives / "my-topic-2"
        assert dest.is_dir()
        assert not topic.exists()

    def test_multiple_conflicts_increment(self, tmp_path):
        topic = tmp_path / "specs" / "my-topic"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"
        # Pre-existing conflicts at base and -2
        (archives / "my-topic").mkdir(parents=True)
        (archives / "my-topic-2").mkdir(parents=True)

        dest = move_topic(topic, archives)

        assert dest == archives / "my-topic-3"
        assert dest.is_dir()
        assert not topic.exists()


class TestMain:
    """Tests for the main() CLI entry point."""

    def test_no_completed_topics(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"
        with patch.object(
            archive_specs, "get_specs_dir", return_value=str(specs)
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=str(archives)
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "No completed topics" in output

    def test_archives_completed_topics(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        _write_todo(specs / "done-topic", [_make_task("1")])
        _write_todo(
            specs / "wip-topic",
            [_make_task("1", completed=False)],
        )
        archives = tmp_path / "archives"
        with patch.object(
            archive_specs, "get_specs_dir", return_value=str(specs)
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=str(archives)
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "done-topic" in output
        assert "wip-topic" not in output
        assert (archives / "done-topic").is_dir()
        assert (specs / "wip-topic").is_dir()

    def test_dry_run_does_not_move(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        _write_todo(specs / "done-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(sys, "argv", ["archive_specs.py", "--dry-run"])
        with patch.object(
            archive_specs, "get_specs_dir", return_value=str(specs)
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=str(archives)
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "Would archive 1 topic(s)" in output
        assert "done-topic" in output
        assert (specs / "done-topic").is_dir()
        assert not archives.exists()

    def test_dry_run_short_flag(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        _write_todo(specs / "done-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(sys, "argv", ["archive_specs.py", "-n"])
        with patch.object(
            archive_specs, "get_specs_dir", return_value=str(specs)
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=str(archives)
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "Would archive" in output
        assert (specs / "done-topic").is_dir()

    def test_topic_flag_archives_single(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        _write_todo(specs / "target-topic", [_make_task("1")])
        _write_todo(specs / "other-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys, "argv", ["archive_specs.py", "--topic", "target-topic"]
        )
        with patch.object(
            archive_specs, "get_specs_dir", return_value=str(specs)
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=str(archives)
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "target-topic" in output
        assert (archives / "target-topic").is_dir()
        assert not (specs / "target-topic").exists()
        # other-topic should remain untouched
        assert (specs / "other-topic").is_dir()

    def test_topic_flag_missing_value(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"
        monkeypatch.setattr(sys, "argv", ["archive_specs.py", "--topic"])
        with patch.object(
            archive_specs, "get_specs_dir", return_value=str(specs)
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=str(archives)
        ):
            with pytest.raises(SystemExit) as exc_info:
                archive_specs.main()
            assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "--topic requires a value" in err


class TestArchiveSingleTopic:
    """Tests for archive_single_topic."""

    def test_archive_single_existing_topic(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        _write_todo(specs / "my-topic", [_make_task("1")])
        archives = tmp_path / "archives"

        dest = archive_single_topic("my-topic", specs, archives)

        assert dest == archives / "my-topic"
        assert dest.is_dir()
        assert not (specs / "my-topic").exists()
        output = capsys.readouterr().out
        assert "my-topic" in output

    def test_archive_single_nonexistent_topic(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"

        with pytest.raises(SystemExit) as exc_info:
            archive_single_topic("no-such-topic", specs, archives)
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "no-such-topic" in err
        assert "not found" in err

    def test_archive_single_topic_conflict(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        _write_todo(specs / "my-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        (archives / "my-topic").mkdir(parents=True)

        dest = archive_single_topic("my-topic", specs, archives)

        assert dest == archives / "my-topic-2"
        assert dest.is_dir()
        assert not (specs / "my-topic").exists()
