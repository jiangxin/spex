import json
from pathlib import Path

import common as common_mod
import pytest
from common import Topic, TopicMeta, get_todo_progress, load_meta
from config import ProjectContext
from list import (  # noqa: A004
    _wrap_text,
    collect_topics,
    format_output,
    format_verbose_output,
    main,
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

        assert result.created_at == "2026-05-24T20:00:00+08:00"
        assert result.prompts == ["hello world"]

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

        assert result.created_at == "2026-05-24T20:00:00+08:00"
        assert result.prompts == []

    def test_missing_fields(self, tmp_path):
        from common import TopicMeta

        topic = tmp_path / "minimal"
        topic.mkdir(parents=True)
        (topic / "meta.json").write_text("{}", encoding="utf-8")

        result = load_meta(topic)

        assert isinstance(result, TopicMeta)
        assert result.topic == ""
        assert result.prompts == []


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
        p = Path("/tmp")
        topics = [
            Topic(name="older", path=p,
                  meta=TopicMeta(created_at="2026-05-01T10:00:00+08:00",
                                 prompts=["old"]),
                  done=1, total=2),
            Topic(name="newer", path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["new"]),
                  done=0, total=1),
        ]
        output = format_output(topics)
        lines = output.splitlines()
        assert "newer" in lines[0]
        assert "older" in lines[1]

    def test_topic_truncation(self):
        p = Path("/tmp")
        long_name = "a" * 40
        topics = [
            Topic(name=long_name, path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["test"]),
                  done=0, total=1),
        ]
        output = format_output(topics)
        assert "..." in output
        assert len(output.splitlines()[0]) <= 80

    def test_line_width_limit(self):
        p = Path("/tmp")
        topics = [
            Topic(name="topic", path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["x" * 200]),
                  done=1, total=3),
        ]
        output = format_output(topics)
        for line in output.splitlines():
            assert len(line) <= 80


class TestCollectTopics:
    def test_collects_from_dirs(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "my-topic"
        _make_meta(topic, "2026-05-20T10:00:00+08:00", ["hello"])
        _make_todo(topic, [_task("1", completed=False)])

        result = collect_topics([specs])

        assert len(result) == 1
        assert isinstance(result[0], Topic)
        assert result[0].name == "my-topic"
        assert result[0].done == 0
        assert result[0].total == 1
        assert result[0].prompt == "hello"

    def test_prefers_meta_over_prompt_log(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "my-topic"
        _make_meta(topic, "2026-05-24T20:00:00+08:00", ["from meta"])
        _make_prompt_log(topic, "2026-05-20T10:00:00+08:00", "from log")

        result = collect_topics([specs])

        assert len(result) == 1
        assert result[0].created_at == "2026-05-24T20:00:00+08:00"
        assert result[0].prompt == "from meta"

    def test_skips_dirs_without_meta(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "old-topic"
        _make_prompt_log(topic, "2026-05-20T10:00:00+08:00", "legacy prompt")

        result = collect_topics([specs])

        assert len(result) == 0

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

        assert result[0].workdir == "/home/user/project-a"


class TestFormatOutputRepoPrefix:
    def test_show_repo_false(self):
        p = Path("/tmp")
        topics = [
            Topic(name="topic-a", path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["x"], workdir="/foo/bar"),
                  done=0, total=1),
        ]
        output = format_output(topics, show_repo=False)
        assert "[" not in output

    def test_show_repo_true_short_name(self):
        p = Path("/tmp")
        topics = [
            Topic(name="topic-a", path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["x"], workdir="/foo/bar"),
                  done=0, total=1),
        ]
        output = format_output(topics, show_repo=True)
        assert "[bar]" in output

    def test_show_repo_true_long_name(self):
        p = Path("/tmp")
        topics = [
            Topic(name="topic-a", path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["x"],
                                 workdir="/foo/my-very-long-project-name"),
                  done=0, total=1),
        ]
        output = format_output(topics, show_repo=True)
        assert "[my-very-..." in output

    def test_show_repo_alignment(self):
        p = Path("/tmp")
        topics = [
            Topic(name="topic-a", path=p,
                  meta=TopicMeta(created_at="2026-05-21T10:00:00+08:00",
                                 prompts=["x"], workdir="/foo/ab"),
                  done=0, total=1),
            Topic(name="topic-b", path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["y"],
                                 workdir="/foo/longername"),
                  done=1, total=1),
        ]
        output = format_output(topics, show_repo=True)
        lines = output.splitlines()
        # Both lines should have the icon at the same column position
        icon_pos_0 = lines[0].index("\U0001f527")
        icon_pos_1 = lines[1].index("✅")
        assert icon_pos_0 == icon_pos_1


class TestDescriptionDisplay:
    def test_description_shown_over_prompt(self):
        p = Path("/tmp")
        topics = [
            Topic(name="topic-a", path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["old prompt"],
                                 description="Better description"),
                  done=0, total=1),
        ]
        output = format_output(topics)
        assert "Better description" in output
        assert "old prompt" not in output

    def test_prompt_fallback_when_no_description(self):
        p = Path("/tmp")
        topics = [
            Topic(name="topic-a", path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["fallback prompt"]),
                  done=0, total=1),
        ]
        output = format_output(topics)
        assert "fallback prompt" in output

    def test_prompt_fallback_when_description_missing(self):
        p = Path("/tmp")
        topics = [
            Topic(name="topic-a", path=p,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["shown prompt"]),
                  done=0, total=1),
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
        assert topics[0].description == "From spec"


class TestVerboseOutput:
    def test_level1_brackets_and_description(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        (topic_dir / "spec.md").write_text(
            '---\ndescription: "Full description text here"\n---\n',
            encoding="utf-8",
        )
        topics = [
            Topic(name="my-topic", path=topic_dir,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["old prompt"],
                                 description="Full description text here"),
                  done=1, total=3),
        ]
        output = format_verbose_output(topics, verbosity=1)
        lines = output.splitlines()
        assert "[1/3]" in lines[0]
        assert "topic" in lines[0]
        assert lines[1] == "    Full description text here"

    def test_level1_prompt_fallback(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        topics = [
            Topic(name="my-topic", path=topic_dir,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["fallback prompt"]),
                  done=0, total=1),
        ]
        output = format_verbose_output(topics, verbosity=1)
        lines = output.splitlines()
        assert "[0/1]" in lines[0]
        assert "topic" in lines[0]
        assert lines[1] == "    fallback prompt"

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
            Topic(name="topic-a", path=dir1,
                  meta=TopicMeta(created_at="2026-05-21T10:00:00+08:00",
                                 prompts=["p1"], description="D1"),
                  done=0, total=1),
            Topic(name="topic-b", path=dir2,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["p2"], description="D2"),
                  done=1, total=1),
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
            Topic(name="my-topic", path=topic_dir,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 description=long_desc.strip()),
                  done=0, total=1),
        ]
        output = format_verbose_output(topics, verbosity=1)
        lines = output.splitlines()
        # format_topic doesn't wrap -- description is raw from spec front-matter
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
            Topic(name="my-topic", path=topic_dir,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["some prompt"],
                                 description="Desc"),
                  done=1, total=2),
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
            Topic(name="my-topic", path=topic_dir,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["p"], description="Desc"),
                  done=0, total=0),
        ]
        output = format_verbose_output(topics, verbosity=2)
        lines = output.splitlines()
        assert len(lines) == 2
        assert "step-" not in output

    def test_level3_hint_message(self, tmp_path):
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        topics = [
            Topic(name="my-topic", path=topic_dir,
                  meta=TopicMeta(created_at="2026-05-20T10:00:00+08:00",
                                 prompts=["p"], description="D"),
                  done=0, total=1),
        ]
        output = format_verbose_output(topics, verbosity=3)
        assert "spex show" in output
        assert "my-topic" not in output


class TestBuildParser:
    """Test argparse-based argument parsing for ``spex list``."""

    def _parse(self, argv):
        from list import _build_parser  # noqa: A004

        return _build_parser().parse(argv)

    def test_no_flags(self):
        args = self._parse([])
        assert args.archives is False
        assert args.all_projects is False
        assert args.verbose == 0

    def test_archives_flag(self):
        args = self._parse(["--archives"])
        assert args.archives is True

    def test_all_projects_flag(self):
        args = self._parse(["--all-projects"])
        assert args.all_projects is True

    def test_single_v(self):
        args = self._parse(["-v"])
        assert args.verbose == 1

    def test_double_v(self):
        args = self._parse(["-vv"])
        assert args.verbose == 2

    def test_verbose_long(self):
        args = self._parse(["--verbose"])
        assert args.verbose == 1

    def test_multiple_v_flags(self):
        args = self._parse(["-v", "-v"])
        assert args.verbose == 2

    def test_combined_flags(self):
        args = self._parse(["--archives", "-vv", "--all-projects"])
        assert args.archives is True
        assert args.all_projects is True
        assert args.verbose == 2

    def test_unknown_flag_exits(self):
        with pytest.raises(SystemExit):
            self._parse(["--unknown"])

    def test_help_exits(self):
        with pytest.raises(SystemExit):
            self._parse(["-h"])


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


def _setup_topic(topic_dir, workdir, main_worktree=None):
    """Create a topic directory with meta.json and todo.json."""
    topic_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "created_at": "2026-05-20T10:00:00+08:00",
        "prompts": ["prompt for " + topic_dir.name],
        "workdir": workdir,
        "main_worktree": main_worktree or workdir,
    }
    (topic_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (topic_dir / "todo.json").write_text("[]", encoding="utf-8")


def _make_project_context(top_workdir, main_worktree=None):
    """Create a ProjectContext for testing."""
    tw = Path(top_workdir)
    mw = Path(main_worktree) if main_worktree else tw
    return ProjectContext(
        cwd=tw,
        top_workdir=tw,
        main_worktree=mw,
        remote_url="",
        branch="main",
        user_name="test",
        user_email="test@test.com",
    )


class TestMainFlags:
    """Test main() with --archives, --all-projects, and --all flags."""

    def _setup(self, tmp_path, monkeypatch):
        """Set up specs/archives dirs and monkeypatches."""
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir()
        archives.mkdir()

        project_workdir = str(tmp_path / "project-a")
        other_workdir = str(tmp_path / "project-b")

        # Related topics (same workdir as project context)
        _setup_topic(specs / "related-spec", project_workdir)
        _setup_topic(archives / "related-archive", project_workdir)

        # Unrelated topics (different workdir)
        _setup_topic(specs / "other-spec", other_workdir)
        _setup_topic(archives / "other-archive", other_workdir)

        ctx = _make_project_context(project_workdir)

        monkeypatch.setattr(common_mod, "get_specs_dir", lambda _w=None: specs)
        monkeypatch.setattr(common_mod, "get_archives_dir", lambda _w=None: archives)
        monkeypatch.setattr(common_mod, "get_project_context", lambda _w=None: ctx)

        return specs, archives

    def test_default_only_related_specs(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path, monkeypatch)

        main([])

        out = capsys.readouterr().out
        assert "related-spec" in out
        assert "related-archive" not in out
        assert "other-spec" not in out
        assert "other-archive" not in out
        # No [repo] prefix in default mode
        assert "[project-a]" not in out

    def test_archives_includes_related_archives(
        self, tmp_path, monkeypatch, capsys,
    ):
        self._setup(tmp_path, monkeypatch)

        main(["--archives"])

        out = capsys.readouterr().out
        assert "related-spec" in out
        assert "related-archive" in out
        assert "other-spec" not in out
        assert "other-archive" not in out

    def test_all_projects_shows_all_with_repo_prefix(
        self, tmp_path, monkeypatch, capsys,
    ):
        self._setup(tmp_path, monkeypatch)

        main(["--all-projects"])

        out = capsys.readouterr().out
        assert "related-spec" in out
        assert "other-spec" in out
        # Archives not included without --archives
        assert "related-archive" not in out
        assert "other-archive" not in out
        # [repo] prefix visible
        assert "[project-a]" in out
        assert "[project-b]" in out

    def test_all_projects_with_archives(
        self, tmp_path, monkeypatch, capsys,
    ):
        self._setup(tmp_path, monkeypatch)

        main(["--all-projects", "--archives"])

        out = capsys.readouterr().out
        assert "related-spec" in out
        assert "related-archive" in out
        assert "other-spec" in out
        assert "other-archive" in out
        # [repo] prefix visible
        assert "[project-a]" in out
        assert "[project-b]" in out

    def test_old_all_flag_rejected(
        self, tmp_path, monkeypatch,
    ):
        self._setup(tmp_path, monkeypatch)

        # --all is not a recognized flag; argparse rejects it
        with pytest.raises(SystemExit):
            main(["--all"])
