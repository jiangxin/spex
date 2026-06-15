import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import archive as spex_archive
import pytest
from archive import (
    archive_single_spec,
    find_completed_specs,
    has_active_branch,
    move_spec,
    move_spec_with_conflict,
    restore_single_spec,
)
from common import is_spec_completed
from config import ProjectContext


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


def _write_todo(spec_dir, tasks):
    """Write a todo.json file into spec_dir."""
    spec_dir.mkdir(parents=True, exist_ok=True)
    todo_path = spec_dir / "todo.json"
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


class TestIsSpecCompleted:
    """Tests for is_spec_completed."""

    def test_all_completed_returns_true(self, tmp_path):
        topic = tmp_path / "my-topic"
        _write_todo(topic, [_make_task("1"), _make_task("2")])

        assert is_spec_completed(topic) is True

    def test_partial_completed_returns_false(self, tmp_path):
        topic = tmp_path / "my-topic"
        _write_todo(topic, [_make_task("1"), _make_task("2", completed=False)])

        assert is_spec_completed(topic) is False

    def test_missing_todo_returns_false(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir()

        assert is_spec_completed(topic) is False

    def test_empty_list_returns_false(self, tmp_path):
        topic = tmp_path / "my-topic"
        _write_todo(topic, [])

        assert is_spec_completed(topic) is False

    def test_invalid_json_returns_false(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir(parents=True, exist_ok=True)
        (topic / "todo.json").write_text("not json", encoding="utf-8")

        assert is_spec_completed(topic) is False


class TestFindCompletedSpecs:
    """Tests for find_completed_specs."""

    def test_returns_only_completed(self, tmp_path):
        specs = tmp_path / "specs"
        # Completed spec
        _write_todo(specs / "done-topic", [_make_task("1")])
        # Incomplete spec
        _write_todo(
            specs / "wip-topic",
            [_make_task("1"), _make_task("2", completed=False)],
        )
        # No todo.json
        (specs / "empty-topic").mkdir(parents=True)

        ctx = _mock_project_context()
        result = find_completed_specs(specs, ctx)

        assert len(result) == 1
        assert result[0].name == "done-topic"

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        ctx = _mock_project_context()
        result = find_completed_specs(tmp_path / "nonexistent", ctx)

        assert result == []

    def test_multiple_completed_sorted(self, tmp_path):
        specs = tmp_path / "specs"
        _write_todo(specs / "beta-topic", [_make_task("1")])
        _write_todo(specs / "alpha-topic", [_make_task("1")])

        ctx = _mock_project_context()
        result = find_completed_specs(specs, ctx)

        assert [d.name for d in result] == ["alpha-topic", "beta-topic"]

    def test_filters_by_current_workdir(self, tmp_path):
        specs = tmp_path / "specs"
        # Spec matching current workdir
        topic_a = specs / "topic-a"
        _write_todo(topic_a, [_make_task("1")])
        (topic_a / "meta.json").write_text(
            json.dumps({"workdir": "/repo/a"}), encoding="utf-8"
        )
        # Spec for a different workdir
        topic_b = specs / "topic-b"
        _write_todo(topic_b, [_make_task("1")])
        (topic_b / "meta.json").write_text(
            json.dumps({"workdir": "/repo/b"}), encoding="utf-8"
        )
        # Spec without workdir (should be included)
        topic_c = specs / "topic-c"
        _write_todo(topic_c, [_make_task("1")])

        ctx = _mock_project_context(top_workdir="/repo/a")
        result = find_completed_specs(specs, ctx)

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

        ctx = _mock_project_context()
        result = find_completed_specs(specs, ctx)

        assert len(result) == 2


class TestMoveTopic:
    """Tests for move_spec."""

    def test_normal_move(self, tmp_path):
        topic = tmp_path / "specs" / "my-topic"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"
        archives.mkdir()

        dest = move_spec(topic, archives)

        assert dest == archives / "my-topic"
        assert dest.is_dir()
        assert not topic.exists()

    def test_conflict_appends_suffix(self, tmp_path):
        topic = tmp_path / "specs" / "my-topic"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"
        # Pre-existing conflict
        (archives / "my-topic").mkdir(parents=True)

        dest = move_spec(topic, archives)

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

        dest = move_spec(topic, archives)

        assert dest == archives / "my-topic-3"
        assert dest.is_dir()
        assert not topic.exists()


class TestMoveTopicWithConflict:
    """Tests for move_spec_with_conflict (bidirectional)."""

    def test_specs_to_archives(self, tmp_path):
        """Move from specs to archives direction."""
        topic = tmp_path / "specs" / "my-topic"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"
        archives.mkdir()

        dest = move_spec_with_conflict(topic, archives)

        assert dest == archives / "my-topic"
        assert dest.is_dir()
        assert not topic.exists()

    def test_archives_to_specs(self, tmp_path):
        """Move from archives to specs direction."""
        archives = tmp_path / "archives" / "my-topic"
        _write_todo(archives, [_make_task("1")])
        specs = tmp_path / "specs"
        specs.mkdir()

        dest = move_spec_with_conflict(archives, specs)

        assert dest == specs / "my-topic"
        assert dest.is_dir()
        assert not archives.exists()

    def test_conflict_appends_suffix(self, tmp_path):
        """Conflict in dest_dir appends -2 suffix."""
        src = tmp_path / "src" / "my-topic"
        _write_todo(src, [_make_task("1")])
        dest_dir = tmp_path / "dest"
        (dest_dir / "my-topic").mkdir(parents=True)

        dest = move_spec_with_conflict(src, dest_dir)

        assert dest == dest_dir / "my-topic-2"
        assert dest.is_dir()
        assert not src.exists()

    def test_multiple_conflicts_increment(self, tmp_path):
        """Multiple conflicts increment suffix to -3."""
        src = tmp_path / "src" / "my-topic"
        _write_todo(src, [_make_task("1")])
        dest_dir = tmp_path / "dest"
        (dest_dir / "my-topic").mkdir(parents=True)
        (dest_dir / "my-topic-2").mkdir(parents=True)

        dest = move_spec_with_conflict(src, dest_dir)

        assert dest == dest_dir / "my-topic-3"
        assert dest.is_dir()
        assert not src.exists()


class TestMain:
    """Tests for the main() CLI entry point."""

    def test_no_completed_specs(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main([])
        assert "No completed specs" in caplog.text

    def test_archives_completed_specs(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        _write_todo(specs / "done-topic", [_make_task("1")])
        _write_todo(
            specs / "wip-topic",
            [_make_task("1", completed=False)],
        )
        archives = tmp_path / "archives"
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main([])
        assert "done-topic" in caplog.text
        assert "wip-topic" not in caplog.text
        assert (archives / "done-topic").is_dir()
        assert (specs / "wip-topic").is_dir()

    def test_dry_run_does_not_move(self, tmp_path, caplog, monkeypatch):
        specs = tmp_path / "specs"
        _write_todo(specs / "done-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(sys, "argv", ["archive.py", "--dry-run"])
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "Would archive 1 spec(s)" in caplog.text
        assert "done-topic" in caplog.text
        assert (specs / "done-topic").is_dir()
        assert not archives.exists()

    def test_dry_run_short_flag(self, tmp_path, caplog, monkeypatch):
        specs = tmp_path / "specs"
        _write_todo(specs / "done-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(sys, "argv", ["archive.py", "-n"])
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "Would archive" in caplog.text
        assert (specs / "done-topic").is_dir()

    def test_topic_flag_archives_single(self, tmp_path, caplog, monkeypatch):
        specs = tmp_path / "specs"
        _write_todo(specs / "target-topic", [_make_task("1")])
        _write_todo(specs / "other-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys, "argv", ["archive.py", "--topic", "target-topic"]
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "target-topic" in caplog.text
        assert (archives / "target-topic").is_dir()
        assert not (specs / "target-topic").exists()
        # other-spec should remain untouched
        assert (specs / "other-topic").is_dir()

    def test_topic_flag_dry_run_does_not_move(self, tmp_path, caplog, monkeypatch):
        specs = tmp_path / "specs"
        _write_todo(specs / "done-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys, "argv", ["archive.py", "--topic", "done-topic", "-n"]
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "Would archive" in caplog.text
        assert "done-topic" in caplog.text
        assert (specs / "done-topic").is_dir()  # not moved
        assert not archives.exists()  # archives dir not even created

    def test_topic_flag_missing_value(self, tmp_path, capsys, monkeypatch):
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"
        monkeypatch.setattr(sys, "argv", ["archive.py", "--topic"])
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ):
            with pytest.raises(SystemExit) as exc_info:
                spex_archive.main()
            assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "--topic" in err


class TestArchiveSingleTopic:
    """Tests for archive_single_spec."""

    def test_archive_single_existing_spec(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        _write_todo(specs / "my-topic", [_make_task("1")])
        archives = tmp_path / "archives"

        with caplog.at_level(logging.INFO):
            dest = archive_single_spec("my-topic", specs, archives)

        assert dest == archives / "my-topic"
        assert dest.is_dir()
        assert not (specs / "my-topic").exists()
        assert "my-topic" in caplog.text

    def test_archive_single_nonexistent_spec(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"

        with pytest.raises(SystemExit) as exc_info:
            archive_single_spec("no-such-topic", specs, archives)
        assert exc_info.value.code == 1
        assert "no-such-topic" in caplog.text
        assert "no spec matching" in caplog.text

    def test_archive_single_spec_conflict(self, tmp_path):
        specs = tmp_path / "specs"
        _write_todo(specs / "my-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        (archives / "my-topic").mkdir(parents=True)

        dest = archive_single_spec("my-topic", specs, archives)

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
        with patch("branch.branch_exists", return_value=True):
            assert has_active_branch(topic) is True

    def test_returns_false_when_branch_missing(self, tmp_path):
        topic = tmp_path / "my-topic"
        topic.mkdir()
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/gone-branch"}), encoding="utf-8"
        )
        with patch("branch.branch_exists", return_value=False):
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


class TestFindCompletedSpecsWithBranchGuard:
    """Tests for find_completed_specs with force parameter."""

    def test_excludes_active_branch_when_force_false(self, tmp_path):
        specs = tmp_path / "specs"
        # Spec with active branch
        topic_a = specs / "active-topic"
        _write_todo(topic_a, [_make_task("1")])
        (topic_a / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}), encoding="utf-8"
        )
        # Spec without spex_branch
        topic_b = specs / "no-branch-topic"
        _write_todo(topic_b, [_make_task("1")])

        ctx = _mock_project_context()
        with patch("branch.branch_exists", return_value=True):
            result = find_completed_specs(specs, ctx, force=False)

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

        ctx = _mock_project_context()
        with patch("branch.branch_exists", return_value=True):
            result = find_completed_specs(specs, ctx, force=True)

        assert len(result) == 1
        assert result[0].name == "active-topic"

    def test_includes_when_spex_branch_missing_from_git(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "merged-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/merged"}), encoding="utf-8"
        )

        ctx = _mock_project_context()
        with patch("branch.branch_exists", return_value=False):
            result = find_completed_specs(specs, ctx, force=False)

        assert len(result) == 1
        assert result[0].name == "merged-topic"


class TestArchiveSingleWithBranchGuard:
    """Tests for archive_single_spec with force parameter."""

    def test_skips_when_branch_exists_no_force(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        topic = specs / "active-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        archives = tmp_path / "archives"

        with patch("branch.branch_exists", return_value=True), \
             caplog.at_level(logging.INFO):
            result = archive_single_spec("active-topic", specs, archives)

        assert result is None
        assert not (archives / "active-topic").exists()
        assert "spex/active" in caplog.text
        assert "Skipping" in caplog.text

    def test_archives_when_branch_missing_no_force(self, tmp_path):
        specs = tmp_path / "specs"
        _write_todo(specs / "merged-topic", [_make_task("1")])
        archives = tmp_path / "archives"

        with patch("branch.branch_exists", return_value=False):
            result = archive_single_spec("merged-topic", specs, archives)

        assert result == archives / "merged-topic"
        assert (archives / "merged-topic").is_dir()

    def test_archives_with_force_despite_branch(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "active-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        archives = tmp_path / "archives"

        with patch("branch.branch_exists", return_value=True):
            result = archive_single_spec(
                "active-topic", specs, archives, force=True
            )

        assert result == archives / "active-topic"
        assert (archives / "active-topic").is_dir()
        assert not (specs / "active-topic").exists()

    def test_partial_match_archives_spec(self, tmp_path):
        specs = tmp_path / "specs"
        topic = specs / "2026-05-27-14-11-archive-branch-guard"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"

        with patch("branch.branch_exists", return_value=False):
            result = archive_single_spec("branch-guard", specs, archives)

        assert result == archives / "2026-05-27-14-11-archive-branch-guard"
        assert (archives / "2026-05-27-14-11-archive-branch-guard").is_dir()
        assert not (specs / "2026-05-27-14-11-archive-branch-guard").exists()

    def test_partial_match_multiple_error(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        (specs / "2026-05-27-14-11-topic-a").mkdir(parents=True)
        (specs / "2026-05-27-14-22-topic-b").mkdir(parents=True)
        archives = tmp_path / "archives"

        with pytest.raises(SystemExit) as exc_info:
            archive_single_spec("topic", specs, archives)
        assert exc_info.value.code == 1
        assert "multiple specs match" in caplog.text
        assert "topic-a" in caplog.text
        assert "topic-b" in caplog.text


class TestMainWithBranchGuard:
    """Integration tests for main() with branch guard."""

    def test_force_flag_archives_active_branch(self, tmp_path, caplog, monkeypatch):
        specs = tmp_path / "specs"
        topic = specs / "active-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys, "argv", ["archive.py", "--force"]
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), patch(
            "branch.branch_exists", return_value=True
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "active-topic" in caplog.text
        assert (archives / "active-topic").is_dir()

    def test_short_f_flag_works(self, tmp_path, caplog, monkeypatch):
        specs = tmp_path / "specs"
        topic = specs / "active-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys, "argv", ["archive.py", "-f"]
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), patch(
            "branch.branch_exists", return_value=True
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "active-topic" in caplog.text

    def test_dry_run_shows_skipped(self, tmp_path, caplog, monkeypatch):
        specs = tmp_path / "specs"
        # Spec with active branch
        topic_active = specs / "active-topic"
        _write_todo(topic_active, [_make_task("1")])
        (topic_active / "meta.json").write_text(
            json.dumps({"spex_branch": "spex/active"}),
            encoding="utf-8",
        )
        # Spec without branch
        topic_merged = specs / "merged-topic"
        _write_todo(topic_merged, [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys, "argv", ["archive.py", "--dry-run"]
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), patch(
            "branch.branch_exists",
            side_effect=lambda name: name == "spex/active",
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "Would archive 1 spec(s)" in caplog.text
        assert "merged-topic" in caplog.text
        assert "Would skip 1 spec(s)" in caplog.text
        assert "active-topic" in caplog.text
        assert "spex/active" in caplog.text
        # Nothing actually moved
        assert not archives.exists()

    def test_bulk_excludes_active_branch(self, tmp_path, caplog, monkeypatch):
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
        monkeypatch.setattr(sys, "argv", ["archive.py"])
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), patch(
            "branch.branch_exists",
            side_effect=lambda name: name == "spex/active",
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "merged-topic" in caplog.text
        assert "active-topic" not in caplog.text
        assert (archives / "merged-topic").is_dir()
        assert (specs / "active-topic").is_dir()

    def test_topic_flag_partial_match(self, tmp_path, caplog, monkeypatch):
        specs = tmp_path / "specs"
        topic = specs / "2026-05-27-14-11-archive-branch-guard"
        _write_todo(topic, [_make_task("1")])
        archives = tmp_path / "archives"
        monkeypatch.setattr(
            sys,
            "argv",
            ["archive.py", "--topic", "branch-guard"],
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), patch(
            "branch.branch_exists", return_value=False
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "2026-05-27-14-11-archive-branch-guard" in caplog.text
        assert (archives / "2026-05-27-14-11-archive-branch-guard").is_dir()


class TestRestoreSingleTopic:
    """Tests for restore_single_spec."""

    def test_restore_single_match(self, tmp_path, caplog):
        """Single match in archives → moved to specs."""
        archives = tmp_path / "archives"
        _write_todo(archives / "my-topic", [_make_task("1")])
        specs = tmp_path / "specs"
        specs.mkdir()

        with caplog.at_level(logging.INFO):
            dest = restore_single_spec("my-topic", specs, archives)

        assert dest == specs / "my-topic"
        assert dest.is_dir()
        assert not (archives / "my-topic").exists()
        assert "Restored:" in caplog.text
        assert "my-topic" in caplog.text

    def test_restore_no_match(self, tmp_path, caplog):
        """No match → exit 1 with error."""
        archives = tmp_path / "archives"
        archives.mkdir()
        specs = tmp_path / "specs"
        specs.mkdir()

        with caplog.at_level(logging.ERROR), \
             pytest.raises(SystemExit) as exc_info:
            restore_single_spec("nonexistent", specs, archives)
        assert exc_info.value.code == 1
        assert "no spec matching" in caplog.text

    def test_restore_multiple_matches(self, tmp_path, caplog):
        """Multiple matches → exit 1 listing candidates."""
        archives = tmp_path / "archives"
        (archives / "2026-01-01-topic-a").mkdir(parents=True)
        (archives / "2026-01-02-topic-b").mkdir(parents=True)
        specs = tmp_path / "specs"
        specs.mkdir()

        with caplog.at_level(logging.ERROR), \
             pytest.raises(SystemExit) as exc_info:
            restore_single_spec("topic", specs, archives)
        assert exc_info.value.code == 1
        assert "multiple specs match" in caplog.text
        assert "topic-a" in caplog.text
        assert "topic-b" in caplog.text

    def test_restore_name_conflict(self, tmp_path):
        """Conflict in specs → spec moved as <name>-2."""
        archives = tmp_path / "archives"
        _write_todo(archives / "my-topic", [_make_task("1")])
        specs = tmp_path / "specs"
        (specs / "my-topic").mkdir(parents=True)

        dest = restore_single_spec("my-topic", specs, archives)

        assert dest == specs / "my-topic-2"
        assert dest.is_dir()
        assert not (archives / "my-topic").exists()

    def test_restore_partial_match(self, tmp_path):
        """Partial match finds unique spec."""
        archives = tmp_path / "archives"
        _write_todo(
            archives / "2026-05-27-14-11-archive-branch-guard",
            [_make_task("1")],
        )
        specs = tmp_path / "specs"
        specs.mkdir()

        dest = restore_single_spec("branch-guard", specs, archives)

        expected = specs / "2026-05-27-14-11-archive-branch-guard"
        assert dest == expected
        assert dest.is_dir()
        assert not (
            archives / "2026-05-27-14-11-archive-branch-guard"
        ).exists()


class TestRestoreFlagCLI:
    """Integration tests for --restore flag in main()."""

    def test_restore_without_topic_errors(self, tmp_path, caplog, monkeypatch):
        """--restore without --topic → error."""
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"
        archives.mkdir()
        monkeypatch.setattr(sys, "argv", ["archive.py", "--restore"])
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                spex_archive.main()
            assert exc_info.value.code == 1
        assert "--restore" in caplog.text
        assert "--topic" in caplog.text

    def test_restore_restores_from_archives(self, tmp_path, caplog, monkeypatch):
        """--restore --topic restores spec from archives to specs."""
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"
        _write_todo(archives / "my-topic", [_make_task("1")])
        monkeypatch.setattr(
            sys, "argv", ["archive.py", "--restore", "--topic", "my-topic"]
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "Restored:" in caplog.text
        assert "my-topic" in caplog.text
        assert (specs / "my-topic").is_dir()
        assert not (archives / "my-topic").exists()

    def test_restore_dry_run_does_not_move(self, tmp_path, caplog, monkeypatch):
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"
        _write_todo(archives / "my-topic", [_make_task("1")])
        monkeypatch.setattr(
            sys, "argv", ["archive.py", "--restore", "--topic", "my-topic", "-n"]
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "Would restore" in caplog.text
        assert "my-topic" in caplog.text
        assert (archives / "my-topic").is_dir()  # not moved
        assert not (specs / "my-topic").exists()  # not restored

    def test_restore_partial_match_restores(self, tmp_path, caplog, monkeypatch):
        """--restore with partial spec name restores unique match."""
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"
        _write_todo(
            archives / "2026-05-27-14-11-archive-branch-guard",
            [_make_task("1")],
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["archive.py", "--restore", "--topic", "branch-guard"],
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "Restored:" in caplog.text
        assert (specs / "2026-05-27-14-11-archive-branch-guard").is_dir()
        assert not (
            archives / "2026-05-27-14-11-archive-branch-guard"
        ).exists()

    def test_not_flag_backward_compat(self, tmp_path, caplog, monkeypatch):
        """--not still works as a hidden alias for --restore."""
        specs = tmp_path / "specs"
        specs.mkdir()
        archives = tmp_path / "archives"
        _write_todo(archives / "my-topic", [_make_task("1")])
        monkeypatch.setattr(
            sys, "argv", ["archive.py", "--not", "--topic", "my-topic"]
        )
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "Restored:" in caplog.text
        assert (specs / "my-topic").is_dir()


class TestAllProjectsFlag:
    """Tests for --all-projects flag."""

    def test_all_projects_includes_cross_project(self, tmp_path, caplog, monkeypatch):
        """With --all-projects, specs from other projects are archived."""
        specs = tmp_path / "specs"
        # Spec from a different project
        topic = specs / "other-topic"
        _write_todo(topic, [_make_task("1")])
        (topic / "meta.json").write_text(
            json.dumps({"workdir": "/other/repo"}), encoding="utf-8"
        )
        archives = tmp_path / "archives"
        ctx = _mock_project_context(top_workdir="/my/repo")
        monkeypatch.setattr(sys, "argv", ["archive.py", "--all-projects"])
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), patch.object(
            spex_archive, "get_project_context", return_value=ctx
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "other-topic" in caplog.text
        assert (archives / "other-topic").is_dir()

    def test_without_all_projects_filters_by_project(self, tmp_path, caplog, monkeypatch):
        """Without --all-projects, only current project specs are archived."""
        specs = tmp_path / "specs"
        # Spec from current project
        topic_mine = specs / "my-topic"
        _write_todo(topic_mine, [_make_task("1")])
        (topic_mine / "meta.json").write_text(
            json.dumps({"workdir": "/my/repo"}), encoding="utf-8"
        )
        # Spec from another project
        topic_other = specs / "other-topic"
        _write_todo(topic_other, [_make_task("1")])
        (topic_other / "meta.json").write_text(
            json.dumps({"workdir": "/other/repo"}), encoding="utf-8"
        )
        archives = tmp_path / "archives"
        ctx = _mock_project_context(top_workdir="/my/repo")
        monkeypatch.setattr(sys, "argv", ["archive.py"])
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), patch.object(
            spex_archive, "get_project_context", return_value=ctx
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "my-topic" in caplog.text
        assert "other-topic" not in caplog.text
        assert (archives / "my-topic").is_dir()
        assert (specs / "other-topic").is_dir()

    def test_non_git_workdir_requires_all_projects(self, tmp_path, caplog, monkeypatch):
        """Outside git workdir without --all-projects, prints message and exits."""
        specs = tmp_path / "specs"
        _write_todo(specs / "done-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        ctx = _mock_project_context()  # top_workdir=None
        monkeypatch.setattr(sys, "argv", ["archive.py"])
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), patch.object(
            spex_archive, "get_project_context", return_value=ctx
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "--all-projects" in caplog.text
        assert (specs / "done-topic").is_dir()  # not moved
        assert not archives.exists()

    def test_non_git_workdir_with_all_projects_works(self, tmp_path, caplog, monkeypatch):
        """Outside git workdir with --all-projects, archives normally."""
        specs = tmp_path / "specs"
        _write_todo(specs / "done-topic", [_make_task("1")])
        archives = tmp_path / "archives"
        ctx = _mock_project_context()  # top_workdir=None
        monkeypatch.setattr(sys, "argv", ["archive.py", "--all-projects"])
        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives
        ), patch.object(
            spex_archive, "get_project_context", return_value=ctx
        ), caplog.at_level(logging.INFO):
            spex_archive.main()
        assert "done-topic" in caplog.text
        assert (archives / "done-topic").is_dir()
