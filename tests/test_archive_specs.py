import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from archive_specs import find_completed_topics, is_topic_completed, move_topic


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
