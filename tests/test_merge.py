import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import merge as spex_merge
import pytest
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
        config={"submit_method": "merge"},
    )


def _setup_topic(tmp_path, topic_name="my-topic", spex_branch="spex/test",
                 branch="main", completed=True):
    """Create a topic directory with meta.json and todo.json."""
    specs = tmp_path / "specs"
    topic_dir = specs / topic_name
    topic_dir.mkdir(parents=True, exist_ok=True)

    meta = {"spex_branch": spex_branch, "branch": branch}
    (topic_dir / "meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )

    tasks = [
        {
            "id": "1",
            "name": "Task 1",
            "details": "Some details",
            "completed_at": "2026-01-01T00:00:00Z" if completed else "",
            "commit_title": "feat: task 1" if completed else "",
        }
    ]
    (topic_dir / "todo.json").write_text(
        json.dumps(tasks), encoding="utf-8"
    )

    return specs, topic_dir


class TestDryRun:
    """Tests for --dry-run flag in cli_submit."""

    def test_dry_run_does_not_merge(self, tmp_path, capsys):
        specs, topic_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.merge_branch", mock_merge):
            spex_merge.cli_submit(["my-topic", "--dry-run"])

        mock_merge.assert_not_called()
        output = capsys.readouterr().out
        assert "Would merge" in output

    def test_dry_run_json_output(self, tmp_path, capsys):
        specs, topic_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.merge_branch", mock_merge):
            spex_merge.cli_submit(["my-topic", "--dry-run"])

        output = capsys.readouterr().out
        lines = output.strip().split("\n")
        # Last line should be JSON
        data = json.loads(lines[-1])
        assert data["dry_run"] is True
        assert data["source"] == "spex/test"
        assert data["target"] == "main"
        assert data["archived"] is True
        assert data["errors"] == []

    def test_dry_run_no_archive(self, tmp_path, capsys):
        specs, topic_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.merge_branch", mock_merge):
            spex_merge.cli_submit(["my-topic", "--dry-run", "--no-archive"])

        mock_merge.assert_not_called()
        output = capsys.readouterr().out
        assert "Would merge" in output
        assert "Would archive" not in output
        lines = output.strip().split("\n")
        data = json.loads(lines[-1])
        assert data["archived"] is False

    def test_dry_run_short_flag(self, tmp_path, capsys):
        specs, topic_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.merge_branch", mock_merge):
            spex_merge.cli_submit(["my-topic", "-n"])

        mock_merge.assert_not_called()
        output = capsys.readouterr().out
        assert "Would merge" in output


class TestAutoSelect:
    """Tests for auto-topic selection when no topic is provided."""

    def test_auto_select_single_topic(self, tmp_path, capsys):
        specs, topic_dir = _setup_topic(
            tmp_path, topic_name="auto-topic",
            spex_branch="spex/auto", completed=True,
        )
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.merge_branch", mock_merge), \
             patch("hooks.run_post_action"), \
             patch("archive.archive_single_topic", return_value=None):
            spex_merge.cli_submit([])

        mock_merge.assert_called_once()
        call_args = mock_merge.call_args
        assert call_args[0][1] == "spex/auto"
        err = capsys.readouterr().err
        assert "Auto-selected: auto-topic" in err

    def test_auto_select_no_topics(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        specs.mkdir(parents=True)
        ctx = _mock_project_context(top_workdir=str(tmp_path))

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             pytest.raises(SystemExit) as exc_info:
            spex_merge.cli_submit([])

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "No submittable topics found" in err

    def test_auto_select_multiple_topics_non_interactive(
        self, tmp_path, caplog,
    ):
        specs = tmp_path / "specs"
        _setup_topic(tmp_path, topic_name="topic-a",
                     spex_branch="spex/a", completed=True)
        _setup_topic(tmp_path, topic_name="topic-b",
                     spex_branch="spex/b", completed=True)
        ctx = _mock_project_context(top_workdir=str(tmp_path))

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("sys.stdin") as mock_stdin, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.readline.return_value = ""
            spex_merge.cli_submit([])

        assert exc_info.value.code == 1
        assert "[1]" in caplog.text
        assert "[2]" in caplog.text
        assert "topic-a" in caplog.text
        assert "topic-b" in caplog.text
