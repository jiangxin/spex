import json
import logging
import sys
from pathlib import Path

import pytest
from common import has_undone_tasks
from config import ProjectContext
from get_topic import main, resolve_topic


def _mock_project_context(top_workdir=None):
    """Create a ProjectContext with the given top_workdir for mocking."""
    tw = Path(top_workdir) if top_workdir else None
    return ProjectContext(
        cwd=Path.cwd(),
        top_workdir=tw,
        main_worktree=tw,
        remote_url="",
        branch="",
        user_name="",
        user_email="",
    )


def _make_topic(specs_dir, name, completed=False, workdir=None):
    """Create a topic directory with todo.json and optional meta.json."""
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
    if workdir is not None:
        meta = {"workdir": workdir}
        (topic / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
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
        assert result == [("2026-05-20-14-30-my-topic", specs)]

    def test_exact_match_no_undone_tasks(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done-topic", completed=True)

        # Default (no filter) returns the topic unconditionally
        result = resolve_topic("2026-05-20-14-30-done-topic", specs)
        assert result == [("2026-05-20-14-30-done-topic", specs)]

    def test_fuzzy_single_match(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-fuzzy-topic")
        _make_topic(specs, "2026-05-20-14-30-other-thing")

        result = resolve_topic("fuzzy", specs)
        assert result == [("2026-05-20-14-30-fuzzy-topic", specs)]

    def test_fuzzy_multiple_matches(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-edit-alpha")
        _make_topic(specs, "2026-05-20-14-30-edit-beta")

        result = resolve_topic("edit", specs)
        assert result == [
            ("2026-05-20-14-30-edit-alpha", specs),
            ("2026-05-20-14-30-edit-beta", specs),
        ]

    def test_fuzzy_no_match(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-something")

        with pytest.raises(SystemExit):
            resolve_topic("nonexistent", specs)

    def test_fuzzy_includes_completed(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done-topic", completed=True)
        _make_topic(specs, "2026-05-20-14-30-active-topic")

        # Default (no filter) returns both done and undone topics
        result = resolve_topic("topic", specs)
        assert result == [
            ("2026-05-20-14-30-active-topic", specs),
            ("2026-05-20-14-30-done-topic", specs),
        ]

    def test_no_name_lists_all(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-alpha")
        _make_topic(specs, "2026-05-20-14-30-beta")
        _make_topic(specs, "2026-05-20-14-30-done", completed=True)

        # Default (no filter) returns all topics
        result = resolve_topic("", specs)
        assert result == [
            ("2026-05-20-14-30-alpha", specs),
            ("2026-05-20-14-30-beta", specs),
            ("2026-05-20-14-30-done", specs),
        ]

    def test_no_name_all_done_still_listed(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done", completed=True)

        # Default (no filter) returns done topics without exiting
        result = resolve_topic("", specs)
        assert result == [("2026-05-20-14-30-done", specs)]

    def test_no_name_specs_dir_missing(self, tmp_path):
        specs = tmp_path / "nonexistent"

        with pytest.raises(SystemExit):
            resolve_topic("", specs)


class TestResolveTopicMustDone:
    def test_exact_match_must_done(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic", completed=True)

        result = resolve_topic("2026-05-20-14-30-my-topic", specs, must_done=True)
        assert result == [("2026-05-20-14-30-my-topic", specs)]

    def test_exact_match_must_done_not_completed(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit):
                resolve_topic("2026-05-20-14-30-my-topic", specs, must_done=True)
        assert "topic '2026-05-20-14-30-my-topic' is not completed." in caplog.text

    def test_fuzzy_match_must_done(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done-topic", completed=True)
        _make_topic(specs, "2026-05-20-14-30-active-topic")

        result = resolve_topic("topic", specs, must_done=True)
        assert result == [("2026-05-20-14-30-done-topic", specs)]

    def test_fuzzy_match_must_done_no_match(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-active-topic")

        with pytest.raises(SystemExit):
            resolve_topic("topic", specs, must_done=True)

    def test_no_name_must_done(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-alpha", completed=True)
        _make_topic(specs, "2026-05-20-14-30-beta", completed=True)
        _make_topic(specs, "2026-05-20-14-30-active")

        result = resolve_topic("", specs, must_done=True)
        assert result == [
            ("2026-05-20-14-30-alpha", specs),
            ("2026-05-20-14-30-beta", specs),
        ]

    def test_no_name_must_done_none_completed(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-active")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit):
                resolve_topic("", specs, must_done=True)
        assert "no completed topics found" in caplog.text


class TestResolveTopicWorkdirFilter:
    def test_filter_by_workdir(self, tmp_path):
        specs = tmp_path / "specs"
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace_a))
        _make_topic(specs, "2026-05-20-14-30-beta", workdir=str(workspace_b))

        ctx = _mock_project_context(top_workdir=str(workspace_a))
        result = resolve_topic("", specs, ctx=ctx)
        assert result == [("2026-05-20-14-30-alpha", specs)]

    def test_filter_returns_multiple(self, tmp_path):
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _make_topic(specs, "2026-05-20-14-30-one", workdir=str(workspace))
        _make_topic(specs, "2026-05-20-14-30-two", workdir=str(workspace))

        ctx = _mock_project_context(top_workdir=str(workspace))
        result = resolve_topic("", specs, ctx=ctx)
        assert result == [
            ("2026-05-20-14-30-one", specs),
            ("2026-05-20-14-30-two", specs),
        ]

    def test_filter_no_match_exits_with_hint(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace_a))

        ctx = _mock_project_context(top_workdir=str(workspace_b))
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit):
                resolve_topic("", specs, ctx=ctx)
        assert "--all-topics" in caplog.text

    def test_filter_skips_topics_without_meta(self, tmp_path):
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _make_topic(specs, "2026-05-20-14-30-has-meta", workdir=str(workspace))
        _make_topic(specs, "2026-05-20-14-30-no-meta")  # no workdir

        ctx = _mock_project_context(top_workdir=str(workspace))
        result = resolve_topic("", specs, ctx=ctx)
        assert result == [
            ("2026-05-20-14-30-has-meta", specs),
            ("2026-05-20-14-30-no-meta", specs),
        ]

    def test_no_filter_returns_all(self, tmp_path):
        specs = tmp_path / "specs"
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace_a))
        _make_topic(specs, "2026-05-20-14-30-beta", workdir=str(workspace_b))

        result = resolve_topic("", specs, ctx=None)
        assert result == [
            ("2026-05-20-14-30-alpha", specs),
            ("2026-05-20-14-30-beta", specs),
        ]

    def test_filter_with_symlink(self, tmp_path):
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        link = tmp_path / "workspace-link"
        link.symlink_to(workspace)
        _make_topic(specs, "2026-05-20-14-30-sym", workdir=str(workspace))

        # Filter using the symlink path — is_related_to should resolve it
        ctx = _mock_project_context(top_workdir=str(link))
        result = resolve_topic("", specs, ctx=ctx)
        assert result == [("2026-05-20-14-30-sym", specs)]

    def test_topic_name_ignores_filter(self, tmp_path):
        """When topic_name is given, ctx filter is not applied."""
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        _make_topic(
            specs, "2026-05-20-14-30-target", workdir=str(other)
        )

        # Even though ctx doesn't match, topic_name takes precedence
        ctx = _mock_project_context(top_workdir=str(workspace))
        result = resolve_topic(
            "2026-05-20-14-30-target", specs, ctx=ctx
        )
        assert result == [("2026-05-20-14-30-target", specs)]


class TestMainAllFlag:
    def test_all_flag_mutual_exclusion(self, tmp_path, monkeypatch, caplog):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        monkeypatch.setattr(
            sys, "argv", ["get_topic", "--all-topics", "my-topic"]
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: specs
        )
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit):
                main()
        assert "--all-topics cannot be used with a topic name" in caplog.text

    def test_all_flag_no_filter(self, tmp_path, monkeypatch, capsys):
        specs = tmp_path / "specs"
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace_a))
        _make_topic(specs, "2026-05-20-14-30-beta", workdir=str(workspace_b))

        monkeypatch.setattr(
            sys, "argv", ["get_topic", "--all-topics"]
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda workdir: specs
        )
        # Mock get_project_context to return workspace_a (should be ignored)
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(workspace_a)),
        )
        main()
        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert lines == ["2026-05-20-14-30-alpha", "2026-05-20-14-30-beta"]

    def test_default_filters_by_workspace(self, tmp_path, monkeypatch, capsys):
        specs = tmp_path / "specs"
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace_a))
        _make_topic(specs, "2026-05-20-14-30-beta", workdir=str(workspace_b))

        monkeypatch.setattr(sys, "argv", ["get_topic"])
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda workdir: specs
        )
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(workspace_a)),
        )
        main()
        out = capsys.readouterr().out
        assert out.strip() == "2026-05-20-14-30-alpha"

    def test_not_in_git_repo_exits(self, tmp_path, monkeypatch, caplog):
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace))

        monkeypatch.setattr(sys, "argv", ["get_topic"])
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: specs
        )
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(None),
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
        assert "not inside a git working directory" in caplog.text


class TestMainMustDoneFlag:
    def test_must_done_and_must_undone_mutual_exclusion(
        self, tmp_path, monkeypatch, capsys
    ):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        monkeypatch.setattr(
            sys, "argv",
            ["get_topic", "--must-done", "--must-undone", "my-topic"],
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: specs
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "not allowed with argument" in err

    def test_must_done_flag_passes_to_resolve(
        self, tmp_path, monkeypatch, capsys
    ):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic", completed=True)

        monkeypatch.setattr(
            sys, "argv",
            ["get_topic", "--must-done", "2026-05-20-14-30-my-topic"],
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda workdir: specs
        )
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(tmp_path)),
        )

        captured_kwargs = {}
        original_resolve = resolve_topic

        def mock_resolve(topic_name, specs_dir, **kwargs):
            captured_kwargs.update(kwargs)
            return original_resolve(topic_name, specs_dir, **kwargs)

        monkeypatch.setattr("get_topic.resolve_topic", mock_resolve)
        main()
        assert captured_kwargs.get("must_done") is True

    def test_no_filter_is_default(
        self, tmp_path, monkeypatch, capsys
    ):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        monkeypatch.setattr(
            sys, "argv",
            ["get_topic", "2026-05-20-14-30-my-topic"],
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda workdir: specs
        )
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(tmp_path)),
        )

        captured_kwargs = {}
        original_resolve = resolve_topic

        def mock_resolve(topic_name, specs_dir, **kwargs):
            captured_kwargs.update(kwargs)
            return original_resolve(topic_name, specs_dir, **kwargs)

        monkeypatch.setattr("get_topic.resolve_topic", mock_resolve)
        main()
        assert captured_kwargs.get("must_done") is False
        assert captured_kwargs.get("must_undone") is False


class TestMainJsonFlag:
    def test_plain_output(self, tmp_path, monkeypatch, capsys):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        monkeypatch.setattr(
            sys, "argv", ["get_topic", "2026-05-20-14-30-my-topic"]
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda workdir: specs
        )
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(tmp_path)),
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
            "get_topic.get_specs_dir", lambda workdir: specs
        )
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(tmp_path)),
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
            "get_topic.get_specs_dir", lambda workdir: specs
        )
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(tmp_path)),
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


class TestResolveTopicMustUndone:
    def test_exact_match_undone(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-active-topic")

        result = resolve_topic(
            "2026-05-20-14-30-active-topic", specs, must_undone=True
        )
        assert result == [("2026-05-20-14-30-active-topic", specs)]

    def test_exact_match_completed_returns_empty(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done-topic", completed=True)

        with caplog.at_level(logging.WARNING):
            result = resolve_topic(
                "2026-05-20-14-30-done-topic", specs, must_undone=True
            )
        assert result == []
        assert "no undone tasks" in caplog.text

    def test_fuzzy_match_filters_undone(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-active-topic")
        _make_topic(specs, "2026-05-20-14-30-done-topic", completed=True)

        result = resolve_topic("topic", specs, must_undone=True)
        assert result == [("2026-05-20-14-30-active-topic", specs)]

    def test_fuzzy_match_all_done_exits(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done-topic", completed=True)

        with pytest.raises(SystemExit):
            resolve_topic("topic", specs, must_undone=True)

    def test_no_name_lists_undone_only(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-alpha")
        _make_topic(specs, "2026-05-20-14-30-beta", completed=True)
        _make_topic(specs, "2026-05-20-14-30-gamma")

        result = resolve_topic("", specs, must_undone=True)
        assert result == [
            ("2026-05-20-14-30-alpha", specs),
            ("2026-05-20-14-30-gamma", specs),
        ]

    def test_no_name_all_done_exits(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done", completed=True)

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit):
                resolve_topic("", specs, must_undone=True)
        assert "no topics with undone tasks found" in caplog.text


class TestResolveTopicWithArchives:
    def test_both_dirs_searched(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_topic(specs, "2026-05-20-14-30-active-topic")
        _make_topic(archives, "2026-05-10-10-00-archived-topic")

        result = resolve_topic("", [specs, archives])
        # Entries are sorted within each directory, appended in dir order
        assert result == [
            ("2026-05-20-14-30-active-topic", specs),
            ("2026-05-10-10-00-archived-topic", archives),
        ]

    def test_parent_dir_correct_for_each_source(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_topic(specs, "2026-05-20-14-30-in-specs")
        _make_topic(archives, "2026-05-10-10-00-in-archives")

        result = resolve_topic("", [specs, archives])
        result_dict = {name: parent for name, parent in result}
        assert result_dict["2026-05-20-14-30-in-specs"] == specs
        assert result_dict["2026-05-10-10-00-in-archives"] == archives

    def test_fuzzy_match_across_dirs(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_topic(specs, "2026-05-20-14-30-feature-auth")
        _make_topic(archives, "2026-05-10-10-00-feature-login")

        result = resolve_topic("feature", [specs, archives])
        assert result == [
            ("2026-05-10-10-00-feature-login", archives),
            ("2026-05-20-14-30-feature-auth", specs),
        ]

    def test_must_done_across_dirs(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_topic(specs, "2026-05-20-14-30-active-topic")
        _make_topic(specs, "2026-05-20-14-30-done-specs", completed=True)
        _make_topic(archives, "2026-05-10-10-00-done-archive", completed=True)
        _make_topic(archives, "2026-05-10-10-00-active-archive")

        result = resolve_topic("", [specs, archives], must_done=True)
        assert result == [
            ("2026-05-20-14-30-done-specs", specs),
            ("2026-05-10-10-00-done-archive", archives),
        ]

    def test_must_undone_across_dirs(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_topic(specs, "2026-05-20-14-30-active-topic")
        _make_topic(specs, "2026-05-20-14-30-done-specs", completed=True)
        _make_topic(archives, "2026-05-10-10-00-done-archive", completed=True)
        _make_topic(archives, "2026-05-10-10-00-active-archive")

        result = resolve_topic("", [specs, archives], must_undone=True)
        assert result == [
            ("2026-05-20-14-30-active-topic", specs),
            ("2026-05-10-10-00-active-archive", archives),
        ]

    def test_single_dir_backward_compat(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        # Single Path (not a list) should still work
        result = resolve_topic("", specs)
        assert result == [("2026-05-20-14-30-my-topic", specs)]


class TestMainWithArchives:
    def test_archived_topics_appear_with_flag(
        self, tmp_path, monkeypatch, capsys
    ):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_topic(specs, "2026-05-20-14-30-active-topic")
        _make_topic(archives, "2026-05-10-10-00-archived-topic")

        monkeypatch.setattr(
            sys, "argv", ["get_topic", "--archives", "--all-topics"]
        )
        monkeypatch.setattr("get_topic.get_specs_dir", lambda workdir: specs)
        monkeypatch.setattr(
            "get_topic.get_archives_dir", lambda workdir: archives
        )
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(tmp_path)),
        )
        main()
        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert "2026-05-10-10-00-archived-topic" in lines
        assert "2026-05-20-14-30-active-topic" in lines

    def test_archived_topics_not_shown_without_flag(
        self, tmp_path, monkeypatch, capsys
    ):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_topic(specs, "2026-05-20-14-30-active-topic")
        _make_topic(archives, "2026-05-10-10-00-archived-topic")

        monkeypatch.setattr(
            sys, "argv", ["get_topic", "--all-topics"]
        )
        monkeypatch.setattr("get_topic.get_specs_dir", lambda workdir: specs)
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(tmp_path)),
        )
        main()
        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert "2026-05-10-10-00-archived-topic" not in lines
        assert "2026-05-20-14-30-active-topic" in lines

    def test_json_output_correct_topic_path(
        self, tmp_path, monkeypatch, capsys
    ):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_topic(specs, "2026-05-20-14-30-active-topic")
        _make_topic(archives, "2026-05-10-10-00-archived-topic")

        monkeypatch.setattr(
            sys, "argv",
            ["get_topic", "--archives", "--all-topics", "--json"],
        )
        monkeypatch.setattr("get_topic.get_specs_dir", lambda workdir: specs)
        monkeypatch.setattr(
            "get_topic.get_archives_dir", lambda workdir: archives
        )
        monkeypatch.setattr(
            "get_topic.get_project_context",
            lambda: _mock_project_context(str(tmp_path)),
        )
        main()
        out = capsys.readouterr().out
        items = json.loads(out)
        assert len(items) == 2

        # Build a lookup by topic_name
        by_name = {item["topic_name"]: item for item in items}
        assert by_name["2026-05-20-14-30-active-topic"]["topic_path"] == str(
            specs / "2026-05-20-14-30-active-topic"
        )
        assert by_name["2026-05-10-10-00-archived-topic"]["topic_path"] == str(
            archives / "2026-05-10-10-00-archived-topic"
        )


