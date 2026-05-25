import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import get_todo_progress, load_meta
from list_specs import (
    collect_topics,
    format_output,
    parse_prompt_log,
)


def _make_meta(topic_dir, created_at="2026-05-20T10:00:00+08:00",
               prompts=None):
    """Create a meta.json file in topic_dir."""
    if prompts is None:
        prompts = ["some prompt text"]
    topic_dir.mkdir(parents=True, exist_ok=True)
    data = {"created_at": created_at, "prompts": prompts}
    (topic_dir / "meta.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _make_prompt_log(topic_dir, timestamp="2026-05-20T10:00:00+08:00",
                     prompt="some prompt text"):
    """Create a prompt.log file in topic_dir."""
    topic_dir.mkdir(parents=True, exist_ok=True)
    content = f'**[{timestamp}]**\n\n```prompt\n    {prompt}\n```\n'
    (topic_dir / "prompt.log").write_text(content, encoding="utf-8")


def _make_todo(topic_dir, tasks):
    """Create a todo.json file in topic_dir."""
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "todo.json").write_text(
        json.dumps(tasks), encoding="utf-8"
    )


def _task(task_id, completed=True):
    return {
        "id": task_id,
        "name": f"Task {task_id}",
        "details": "details",
        "completed_at": "2026-01-01T00:00:00+08:00" if completed else "",
        "commit_title": "abc: done" if completed else "",
    }


class TestLoadMeta:
    def test_normal_read(self, tmp_path):
        topic = tmp_path / "my-topic"
        _make_meta(topic, "2026-05-24T20:00:00+08:00", ["hello world"])

        result = load_meta(topic)

        assert result["created_at"] == "2026-05-24T20:00:00+08:00"
        assert result["prompts"] == ["hello world"]

    def test_missing_file(self, tmp_path):
        assert load_meta(tmp_path / "nonexistent") is None

    def test_invalid_json(self, tmp_path):
        topic = tmp_path / "bad"
        topic.mkdir(parents=True)
        (topic / "meta.json").write_text("not json", encoding="utf-8")

        assert load_meta(topic) is None

    def test_empty_prompts(self, tmp_path):
        topic = tmp_path / "empty"
        _make_meta(topic, "2026-05-24T20:00:00+08:00", [])

        result = load_meta(topic)

        assert result["created_at"] == "2026-05-24T20:00:00+08:00"
        assert result["prompts"] == []

    def test_missing_fields(self, tmp_path):
        topic = tmp_path / "minimal"
        topic.mkdir(parents=True)
        (topic / "meta.json").write_text("{}", encoding="utf-8")

        result = load_meta(topic)

        assert result == {}


class TestParsePromptLog:
    def test_normal_parse(self, tmp_path):
        topic = tmp_path / "my-topic"
        _make_prompt_log(topic, "2026-05-20T18:00:00+08:00", "hello world")

        ts, prompt = parse_prompt_log(topic / "prompt.log")

        assert ts == "2026-05-20T18:00:00+08:00"
        assert prompt == "hello world"

    def test_missing_file(self, tmp_path):
        ts, prompt = parse_prompt_log(tmp_path / "nonexistent" / "prompt.log")

        assert ts == ""
        assert prompt == ""

    def test_multiline_prompt(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir(parents=True)
        content = (
            "**[2026-05-20T10:00:00+08:00]**\n\n"
            "```prompt\n"
            "    line one\n"
            "    line two\n"
            "```\n"
        )
        (topic / "prompt.log").write_text(content, encoding="utf-8")

        ts, prompt = parse_prompt_log(topic / "prompt.log")

        assert ts == "2026-05-20T10:00:00+08:00"
        assert prompt == "line one line two"


class TestGetTodoProgress:
    def test_all_done(self, tmp_path):
        topic = tmp_path / "t"
        _make_todo(topic, [_task("1"), _task("2")])

        assert get_todo_progress(topic) == (2, 2)

    def test_partial(self, tmp_path):
        topic = tmp_path / "t"
        _make_todo(topic, [_task("1"), _task("2", completed=False)])

        assert get_todo_progress(topic) == (1, 2)

    def test_missing_file(self, tmp_path):
        assert get_todo_progress(tmp_path / "no-topic") == (0, 0)


class TestFormatOutput:
    def test_empty_list(self):
        assert format_output([]) == "No specs found."

    def test_sort_descending(self):
        topics = [
            {"name": "older", "timestamp": "2026-05-01T10:00:00+08:00",
             "n": 1, "m": 2, "prompt": "old"},
            {"name": "newer", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "new"},
        ]
        output = format_output(topics)
        lines = output.splitlines()
        assert "newer" in lines[0]
        assert "older" in lines[1]

    def test_topic_truncation(self):
        long_name = "a" * 40
        topics = [
            {"name": long_name, "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "test"},
        ]
        output = format_output(topics)
        assert "..." in output
        assert len(output.splitlines()[0]) <= 80

    def test_line_width_limit(self):
        topics = [
            {"name": "topic", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 1, "m": 3, "prompt": "x" * 200},
        ]
        output = format_output(topics)
        for line in output.splitlines():
            assert len(line) <= 80


class TestCollectTopics:
    def test_collects_from_dirs(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "my-topic"
        _make_prompt_log(topic, "2026-05-20T10:00:00+08:00", "hello")
        _make_todo(topic, [_task("1", completed=False)])

        result = collect_topics([specs])

        assert len(result) == 1
        assert result[0]["name"] == "my-topic"
        assert result[0]["n"] == 0
        assert result[0]["m"] == 1
        assert result[0]["prompt"] == "hello"

    def test_prefers_meta_over_prompt_log(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "my-topic"
        _make_meta(topic, "2026-05-24T20:00:00+08:00", ["from meta"])
        _make_prompt_log(topic, "2026-05-20T10:00:00+08:00", "from log")

        result = collect_topics([specs])

        assert len(result) == 1
        assert result[0]["timestamp"] == "2026-05-24T20:00:00+08:00"
        assert result[0]["prompt"] == "from meta"

    def test_falls_back_to_prompt_log(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "old-topic"
        _make_prompt_log(topic, "2026-05-20T10:00:00+08:00", "legacy prompt")

        result = collect_topics([specs])

        assert len(result) == 1
        assert result[0]["timestamp"] == "2026-05-20T10:00:00+08:00"
        assert result[0]["prompt"] == "legacy prompt"

    def test_workdir_stored(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "my-topic"
        topic.mkdir(parents=True)
        data = {
            "created_at": "2026-05-24T20:00:00+08:00",
            "prompts": ["test"],
            "workdir": "/home/user/project-a",
        }
        (topic / "meta.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

        result = collect_topics([specs])

        assert result[0]["workdir"] == "/home/user/project-a"


class TestFormatOutputRepoPrefix:
    def test_show_repo_false(self):
        topics = [
            {"name": "topic-a", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "x", "workdir": "/foo/bar"},
        ]
        output = format_output(topics, show_repo=False)
        assert "[" not in output

    def test_show_repo_true_short_name(self):
        topics = [
            {"name": "topic-a", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "x", "workdir": "/foo/bar"},
        ]
        output = format_output(topics, show_repo=True)
        assert "[bar]" in output

    def test_show_repo_true_long_name(self):
        topics = [
            {"name": "topic-a", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "x",
             "workdir": "/foo/my-very-long-project-name"},
        ]
        output = format_output(topics, show_repo=True)
        assert "[my-very-..." in output

    def test_show_repo_alignment(self):
        topics = [
            {"name": "topic-a", "timestamp": "2026-05-21T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "x", "workdir": "/foo/ab"},
            {"name": "topic-b", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 1, "m": 1, "prompt": "y",
             "workdir": "/foo/longername"},
        ]
        output = format_output(topics, show_repo=True)
        lines = output.splitlines()
        # Both lines should have the icon at the same column position
        icon_pos_0 = lines[0].index("\U0001f527")
        icon_pos_1 = lines[1].index("✅")
        assert icon_pos_0 == icon_pos_1
