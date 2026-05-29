import json
import sys
from unittest.mock import patch

import archive_specs
import pytest
from archive_specs import (
    archive_single_topic,
    find_completed_topics,
    has_active_branch,
    move_topic,
)
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
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
        ):
            archive_specs.main([])
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
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
        ):
            archive_specs.main([])
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
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
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
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
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
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
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
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
        ):
            with pytest.raises(SystemExit) as exc_info:
                archive_specs.main()
            assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "--topic" in err


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
        assert "no topic matching" in err

    def test_archive_single_topic_conflict(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        _write_todo(specs / "my-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        (archives / "my-topic").mkdir(parents=True)

        dest = archive_single_topic("my-topic", specs, archives)

        assert dest == archives / "my-topic-2"
        assert dest.is_dir()
        assert not (specs / "my-topic").exists()


class TestHasActiveBranch:
    """Tests for has_active_branch."""

    def test_returns_true_when_branch_exists(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir()
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/some-branch"}), encoding="utf-8"
        )
        with patch("archive_specs.branch_exists", return_value=True):
            assert has_active_branch(topic) is True

    def test_returns_false_when_branch_missing(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir()
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/gone-branch"}), encoding="utf-8"
        )
        with patch("archive_specs.branch_exists", return_value=False):
            assert has_active_branch(topic) is False

    def test_returns_false_when_no_spex_branch(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir()
        (topic / "meta.json").write_text(
            json.dumps({"workdir": "/repo"}), encoding="utf-8"
        )
        assert has_active_branch(topic) is False

    def test_returns_false_when_no_meta_json(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir()
        assert has_active_branch(topic) is False


class TestFindCompletedTopicsWithBranchGuard:
    """Tests for find_completed_topics with force parameter."""

    def test_excludes_active_branch_when_force_false(self, tmp_path):
        specs = tmp_path / "specs"
        # Topic with active branch
        topic_a = specs / "active-topic"
        _write_todo(topic_a, [_make_task("1")])
        (topic_a / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}), encoding="utf-8"
        )
        # Topic without spex_branch
        topic_b = specs / "no-branch-topic"
        _write_todo(topic_b, [_make_task("1")])

        with patch("archive_specs.branch_exists", return_value=True):
            result = find_completed_topics(specs, force=False)

        names = [d.name for d in result]
        assert "no-branch-topic" in names
        assert "active-topic" not in names

    def test_includes_active_branch_when_force_true(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "active-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}), encoding="utf-8"
        )

        with patch("archive_specs.branch_exists", return_value=True):
            result = find_completed_topics(specs, force=True)

        assert len(result) == 1
        assert result[0].name == "active-topic"

    def test_includes_when_spex_branch_missing_from_git(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "merged-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/merged"}), encoding="utf-8"
        )

        with patch("archive_specs.branch_exists", return_value=False):
            result = find_completed_topics(specs, force=False)

        assert len(result) == 1
        assert result[0].name == "merged-topic"


class TestArchiveSingleWithBranchGuard:
    """Tests for archive_single_topic with force parameter."""

    def test_skips_when_branch_exists_no_force(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        topic = specs / "active-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        archives = tmp_path / "archives"

        with patch("archive_specs.branch_exists", return_value=True):
            result = archive_single_topic("active-topic", specs, archives)

        assert result is None
        assert not (archives / "active-topic").exists()
        output = capsys.readouterr().out
        assert "spex/active" in output
        assert "Skipping" in output

    def test_archives_when_branch_missing_no_force(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        _write_todo(specs / "merged-topic", [_make_task("1")])
        archives = tmp_path / "archives"

        with patch("archive_specs.branch_exists", return_value=False):
            result = archive_single_topic("merged-topic", specs, archives)

        assert result == archives / "merged-topic"
        assert (archives / "merged-topic").is_dir()

    def test_archives_with_force_despite_branch(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        topic = specs / "active-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        archives = tmp_path / "archives"

        with patch("archive_specs.branch_exists", return_value=True):
            result = archive_single_topic(
                "active-topic", specs, archives, force=True
            )

        assert result == archives / "active-topic"
        assert (archives / "active-topic").is_dir()
        assert not (specs / "active-topic").exists()

    def test_partial_match_archives_topic(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        topic = specs / "2026-05-27-14-11-archive-branch-guard"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"

        with patch("archive_specs.branch_exists", return_value=False):
            result = archive_single_topic("branch-guard", specs, archives)

        assert result == archives / "2026-05-27-14-11-archive-branch-guard"
        assert (archives / "2026-05-27-14-11-archive-branch-guard").is_dir()
        assert not (specs / "2026-05-27-14-11-archive-branch-guard").exists()

    def test_partial_match_multiple_error(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        (specs / "2026-05-27-14-11-topic-a").mkdir(parents=True)
        (specs / "2026-05-27-14-22-topic-b").mkdir(parents=True)
        archives = tmp_path / "archives"

        with pytest.raises(SystemExit) as exc_info:
            archive_single_topic("topic", specs, archives)
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "multiple topics match" in err
        assert "topic-a" in err
        assert "topic-b" in err


class TestMainWithBranchGuard:
    """Integration tests for main() with branch guard."""

    def test_force_flag_archives_active_branch(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        topic = specs / "active-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys, "argv", ["archive_specs.py", "--force"]
        )
        with patch.object(
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
        ), patch(
            "archive_specs.branch_exists", return_value=True
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "active-topic" in output
        assert (archives / "active-topic").is_dir()

    def test_short_f_flag_works(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        topic = specs / "active-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys, "argv", ["archive_specs.py", "-f"]
        )
        with patch.object(
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
        ), patch(
            "archive_specs.branch_exists", return_value=True
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "active-topic" in output

    def test_dry_run_shows_skipped(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        # Topic with active branch
        topic_active = specs / "active-topic"
        _write_todo(topic_active, [_make_task("1")])
        (topic_active / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        # Topic without branch
        topic_merged = specs / "merged-topic"
        _write_todo(topic_merged, [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys, "argv", ["archive_specs.py", "--dry-run"]
        )
        with patch.object(
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
        ), patch(
            "archive_specs.branch_exists",
            side_effect=lambda name: name == "spex/active",
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "Would archive 1 topic(s)" in output
        assert "merged-topic" in output
        assert "Would skip 1 topic(s)" in output
        assert "active-topic" in output
        assert "spex/active" in output
        # Nothing actually moved
        assert not archives.exists()

    def test_bulk_excludes_active_branch(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        topic_active = specs / "active-topic"
        _write_todo(topic_active, [_make_task("1")])
        (topic_active / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        topic_merged = specs / "merged-topic"
        _write_todo(topic_merged, [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(sys, "argv", ["archive_specs.py"])
        with patch.object(
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
        ), patch(
            "archive_specs.branch_exists",
            side_effect=lambda name: name == "spex/active",
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "merged-topic" in output
        assert "active-topic" not in output
        assert (archives / "merged-topic").is_dir()
        assert (specs / "active-topic").is_dir()

    def test_topic_flag_partial_match(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        topic = specs / "2026-05-27-14-11-archive-branch-guard"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys,
            "argv",
            ["archive_specs.py", "--topic", "branch-guard"],
        )
        with patch.object(
            archive_specs, "get_specs_dir", return_value=specs
        ), patch.object(
            archive_specs, "get_archives_dir", return_value=archives
        ), patch(
            "archive_specs.branch_exists", return_value=False
        ):
            archive_specs.main()
        output = capsys.readouterr().out
        assert "2026-05-27-14-11-archive-branch-guard" in output
        assert (archives / "2026-05-27-14-11-archive-branch-guard").is_dir()
