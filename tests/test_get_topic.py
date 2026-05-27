import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import has_undone_tasks
from get_topic import main, resolve_topic


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
        assert result == ["2026-05-20-14-30-my-topic"]

    def test_exact_match_no_undone_tasks(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done-topic", completed=True)

        result = resolve_topic("2026-05-20-14-30-done-topic", specs)
        assert result == []
        err = capsys.readouterr().err
        assert "Warning: topic '2026-05-20-14-30-done-topic' has no undone tasks." in err

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


class TestResolveTopicMustDone:
    def test_exact_match_must_done(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic", completed=True)

        result = resolve_topic("2026-05-20-14-30-my-topic", specs, must_done=True)
        assert result == ["2026-05-20-14-30-my-topic"]

    def test_exact_match_must_done_not_completed(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        with pytest.raises(SystemExit):
            resolve_topic("2026-05-20-14-30-my-topic", specs, must_done=True)
        err = capsys.readouterr().err
        assert "Error: topic '2026-05-20-14-30-my-topic' is not completed." in err

    def test_fuzzy_match_must_done(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-done-topic", completed=True)
        _make_topic(specs, "2026-05-20-14-30-active-topic")

        result = resolve_topic("topic", specs, must_done=True)
        assert result == ["2026-05-20-14-30-done-topic"]

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
        assert result == ["2026-05-20-14-30-alpha", "2026-05-20-14-30-beta"]

    def test_no_name_must_done_none_completed(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-active")

        with pytest.raises(SystemExit):
            resolve_topic("", specs, must_done=True)
        err = capsys.readouterr().err
        assert "no completed topics found" in err


class TestResolveTopicWorkdirFilter:
    def test_filter_by_workdir(self, tmp_path):
        specs = tmp_path / "specs"
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace_a))
        _make_topic(specs, "2026-05-20-14-30-beta", workdir=str(workspace_b))

        result = resolve_topic("", specs, filter_workdir=str(workspace_a))
        assert result == ["2026-05-20-14-30-alpha"]

    def test_filter_returns_multiple(self, tmp_path):
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _make_topic(specs, "2026-05-20-14-30-one", workdir=str(workspace))
        _make_topic(specs, "2026-05-20-14-30-two", workdir=str(workspace))

        result = resolve_topic("", specs, filter_workdir=str(workspace))
        assert result == ["2026-05-20-14-30-one", "2026-05-20-14-30-two"]

    def test_filter_no_match_exits_with_hint(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace_a))

        with pytest.raises(SystemExit):
            resolve_topic("", specs, filter_workdir=str(workspace_b))
        err = capsys.readouterr().err
        assert "--all" in err

    def test_filter_skips_topics_without_meta(self, tmp_path):
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _make_topic(specs, "2026-05-20-14-30-has-meta", workdir=str(workspace))
        _make_topic(specs, "2026-05-20-14-30-no-meta")  # no workdir

        result = resolve_topic("", specs, filter_workdir=str(workspace))
        assert result == ["2026-05-20-14-30-has-meta"]

    def test_no_filter_returns_all(self, tmp_path):
        specs = tmp_path / "specs"
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace_a))
        _make_topic(specs, "2026-05-20-14-30-beta", workdir=str(workspace_b))

        result = resolve_topic("", specs, filter_workdir=None)
        assert result == ["2026-05-20-14-30-alpha", "2026-05-20-14-30-beta"]

    def test_filter_with_symlink(self, tmp_path):
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        link = tmp_path / "workspace-link"
        link.symlink_to(workspace)
        _make_topic(specs, "2026-05-20-14-30-sym", workdir=str(workspace))

        # Filter using the symlink path — same_path should resolve it
        result = resolve_topic("", specs, filter_workdir=str(link))
        assert result == ["2026-05-20-14-30-sym"]

    def test_topic_name_ignores_filter(self, tmp_path):
        """When topic_name is given, filter_workdir is not applied."""
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        _make_topic(
            specs, "2026-05-20-14-30-target", workdir=str(other)
        )

        # Even though filter_workdir doesn't match, topic_name takes precedence
        result = resolve_topic(
            "2026-05-20-14-30-target", specs, filter_workdir=str(workspace)
        )
        assert result == ["2026-05-20-14-30-target"]


class TestMainAllFlag:
    def test_all_flag_mutual_exclusion(self, tmp_path, monkeypatch, capsys):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        monkeypatch.setattr(
            sys, "argv", ["get_topic", "--all", "my-topic"]
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: str(specs)
        )
        with pytest.raises(SystemExit):
            main()
        err = capsys.readouterr().err
        assert "--all cannot be used with a topic name" in err

    def test_all_flag_no_filter(self, tmp_path, monkeypatch, capsys):
        specs = tmp_path / "specs"
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace_a))
        _make_topic(specs, "2026-05-20-14-30-beta", workdir=str(workspace_b))

        monkeypatch.setattr(
            sys, "argv", ["get_topic", "--all"]
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: str(specs)
        )
        # Mock get_current_workdir to return workspace_a (should be ignored)
        monkeypatch.setattr(
            "get_topic.get_current_workdir", lambda: str(workspace_a)
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
            "get_topic.get_specs_dir", lambda: str(specs)
        )
        monkeypatch.setattr(
            "get_topic.get_current_workdir", lambda: str(workspace_a)
        )
        main()
        out = capsys.readouterr().out
        assert out.strip() == "2026-05-20-14-30-alpha"

    def test_not_in_git_repo_no_filter(self, tmp_path, monkeypatch, capsys):
        specs = tmp_path / "specs"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _make_topic(specs, "2026-05-20-14-30-alpha", workdir=str(workspace))
        _make_topic(specs, "2026-05-20-14-30-beta")

        monkeypatch.setattr(sys, "argv", ["get_topic"])
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: str(specs)
        )
        # Not in a git repo — get_current_workdir returns None
        monkeypatch.setattr(
            "get_topic.get_current_workdir", lambda: None
        )
        main()
        out = capsys.readouterr().out
        lines = out.strip().splitlines()
        assert lines == ["2026-05-20-14-30-alpha", "2026-05-20-14-30-beta"]


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
            "get_topic.get_specs_dir", lambda: str(specs)
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "--must-done and --must-undone are mutually exclusive" in err

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
            "get_topic.get_specs_dir", lambda: str(specs)
        )

        captured_kwargs = {}
        original_resolve = resolve_topic

        def mock_resolve(topic_name, specs_dir, **kwargs):
            captured_kwargs.update(kwargs)
            return original_resolve(topic_name, specs_dir, **kwargs)

        monkeypatch.setattr("get_topic.resolve_topic", mock_resolve)
        main()
        assert captured_kwargs.get("must_done") is True

    def test_must_undone_is_default(
        self, tmp_path, monkeypatch, capsys
    ):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-14-30-my-topic")

        monkeypatch.setattr(
            sys, "argv",
            ["get_topic", "2026-05-20-14-30-my-topic"],
        )
        monkeypatch.setattr(
            "get_topic.get_specs_dir", lambda: str(specs)
        )

        captured_kwargs = {}
        original_resolve = resolve_topic

        def mock_resolve(topic_name, specs_dir, **kwargs):
            captured_kwargs.update(kwargs)
            return original_resolve(topic_name, specs_dir, **kwargs)

        monkeypatch.setattr("get_topic.resolve_topic", mock_resolve)
        main()
        assert captured_kwargs.get("must_done") is False


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
