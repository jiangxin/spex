import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import get_todo_progress, load_meta
from list_specs import (
    _parse_verbosity,
    _wrap_text,
    collect_topics,
    format_output,
    format_verbose_output,
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


class TestDescriptionDisplay:
    def test_description_shown_over_prompt(self):
        topics = [
            {"name": "topic-a", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "old prompt",
             "description": "Better description"},
        ]
        output = format_output(topics)
        assert "Better description" in output
        assert "old prompt" not in output

    def test_prompt_fallback_when_no_description(self):
        topics = [
            {"name": "topic-a", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "fallback prompt",
             "description": ""},
        ]
        output = format_output(topics)
        assert "fallback prompt" in output

    def test_prompt_fallback_when_description_missing(self):
        topics = [
            {"name": "topic-a", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "shown prompt"},
        ]
        output = format_output(topics)
        assert "shown prompt" in output

    def test_collect_topics_includes_description(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "my-topic"
        topic.mkdir(parents=True)
        _make_meta(topic)
        spec = topic / "spec.md"
        spec.write_text(
            '---\ndescription: "From spec"\n---\n\n# Spec',
            encoding="utf-8",
        )
        topics = collect_topics([specs])
        assert topics[0]["description"] == "From spec"


class TestVerboseOutput:
    def test_level1_brackets_and_description(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        (topic_dir / "spec.md").write_text(
            '---\ndescription: "Full description text here"\n---\n',
            encoding="utf-8",
        )
        topics = [
            {"name": "my-topic", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 1, "m": 3, "prompt": "old prompt", "path": topic_dir,
             "description": "Full description text here"},
        ]
        output = format_verbose_output(topics, verbosity=1)
        lines = output.splitlines()
        # format_topic reads n/m from filesystem (no todo.json → 0/0)
        assert "[0/0]" in lines[0]
        assert "topic" in lines[0]
        assert lines[1] == "    Full description text here"

    def test_level1_prompt_fallback(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        # No spec.md → no description
        topics = [
            {"name": "my-topic", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "fallback prompt", "path": topic_dir,
             "description": ""},
        ]
        output = format_verbose_output(topics, verbosity=1)
        lines = output.splitlines()
        # Without description, only header line is output
        assert len(lines) == 1
        assert "topic" in lines[0]

    def test_level1_blank_line_between_topics(self, tmp_path):
        dir1 = tmp_path / "t1"
        dir1.mkdir()
        dir2 = tmp_path / "t2"
        dir2.mkdir()
        (dir1 / "spec.md").write_text(
            '---\ndescription: "D1"\n---\n', encoding="utf-8",
        )
        (dir2 / "spec.md").write_text(
            '---\ndescription: "D2"\n---\n', encoding="utf-8",
        )
        topics = [
            {"name": "topic-a", "timestamp": "2026-05-21T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "p1", "path": dir1, "description": "D1"},
            {"name": "topic-b", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 1, "m": 1, "prompt": "p2", "path": dir2, "description": "D2"},
        ]
        output = format_verbose_output(topics, verbosity=1)
        assert "\n\n" in output

    def test_level1_word_wrap(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        long_desc = "word " * 20  # 100 chars
        (topic_dir / "spec.md").write_text(
            f'---\ndescription: "{long_desc.strip()}"\n---\n',
            encoding="utf-8",
        )
        topics = [
            {"name": "my-topic", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "", "path": topic_dir,
             "description": long_desc.strip()},
        ]
        output = format_verbose_output(topics, verbosity=1)
        lines = output.splitlines()
        # format_topic doesn't wrap — description is raw from spec front-matter
        assert any("word word" in line for line in lines[1:])

    def test_level2_shows_steps(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        (topic_dir / "spec.md").write_text(
            '---\ndescription: "Desc"\n---\n', encoding="utf-8",
        )
        _make_todo(topic_dir, [
            _task("step-1", completed=True),
            _task("step-2", completed=False),
        ])
        topics = [
            {"name": "my-topic", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 1, "m": 2, "prompt": "some prompt", "path": topic_dir,
             "description": "Desc"},
        ]
        output = format_verbose_output(topics, verbosity=2)
        lines = output.splitlines()
        assert "[1/2]" in lines[0]
        assert lines[1] == "    Desc"
        assert lines[2] == ""
        assert "step-1:" in lines[3]
        assert "step-2:" in lines[4]

    def test_level2_no_steps_when_no_todo(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        (topic_dir / "spec.md").write_text(
            '---\ndescription: "Desc"\n---\n', encoding="utf-8",
        )
        topics = [
            {"name": "my-topic", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 0, "prompt": "p", "path": topic_dir,
             "description": "Desc"},
        ]
        output = format_verbose_output(topics, verbosity=2)
        lines = output.splitlines()
        assert len(lines) == 2
        assert "step-" not in output

    def test_level3_hint_message(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        topics = [
            {"name": "my-topic", "timestamp": "2026-05-20T10:00:00+08:00",
             "n": 0, "m": 1, "prompt": "p", "path": topic_dir,
             "description": "D"},
        ]
        output = format_verbose_output(topics, verbosity=3)
        assert "spex show" in output
        assert "my-topic" not in output


class TestParseVerbosity:
    def test_no_flag(self):
        assert _parse_verbosity(["--all"]) == 0

    def test_single_v(self):
        assert _parse_verbosity(["-v"]) == 1

    def test_double_v(self):
        assert _parse_verbosity(["-vv"]) == 2

    def test_verbose_flag(self):
        assert _parse_verbosity(["--verbose"]) == 1

    def test_multiple_v_flags(self):
        assert _parse_verbosity(["-v", "-v"]) == 2

    def test_combined_with_all(self):
        assert _parse_verbosity(["--all", "-vv"]) == 2


class TestWrapText:
    def test_short_text_no_wrap(self):
        result = _wrap_text("short text", width=80, indent=4)
        assert result == "    short text"

    def test_long_text_wraps(self):
        text = "word " * 20  # 100 chars
        result = _wrap_text(text.strip(), width=80, indent=4)
        lines = result.splitlines()
        assert len(lines) > 1
        for line in lines:
            assert len(line) <= 80
            assert line.startswith("    ")

    def test_exact_boundary(self):
        text = "a" * 76  # exactly 76 + 4 indent = 80
        result = _wrap_text(text, width=80, indent=4)
        assert result == "    " + text
