import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import common as spex_common
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


def _setup_topic(tmp_path, spec_name="my-topic", spex_branch="spex/test",
                 branch="main", completed=True):
    """Create a spec directory with meta.json and todo.json."""
    specs = tmp_path / "specs"
    spec_dir = specs / spec_name
    spec_dir.mkdir(parents=True, exist_ok=True)

    meta = {"spex_branch": spex_branch, "branch": branch}
    (spec_dir / "meta.json").write_text(
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
    (spec_dir / "todo.json").write_text(
        json.dumps(tasks), encoding="utf-8"
    )

    return specs, spec_dir


@pytest.mark.slow
class TestDryRun:
    """Tests for --dry-run flag in cli_submit."""

    def test_dry_run_does_not_merge(self, tmp_path, caplog):
        specs, spec_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.merge_branch", mock_merge), \
             caplog.at_level(logging.INFO):
            spex_merge.cli_submit(["my-topic", "--dry-run"])

        mock_merge.assert_not_called()
        assert "Would merge" in caplog.text

    def test_dry_run_json_output(self, tmp_path, capsys):
        specs, spec_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.merge_branch", mock_merge):
            spex_merge.cli_submit(["my-topic", "--dry-run"])

        output = capsys.readouterr().out
        # Only JSON remains on stdout (info messages go to logging)
        data = json.loads(output.strip())
        assert data["dry_run"] is True
        assert data["source"] == "spex/test"
        assert data["target"] == "main"
        assert data["archived"] is True
        assert data["errors"] == []

    def test_dry_run_no_archive(self, tmp_path, capsys, caplog):
        specs, spec_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.merge_branch", mock_merge), \
             caplog.at_level(logging.INFO):
            spex_merge.cli_submit(["my-topic", "--dry-run", "--no-archive"])

        mock_merge.assert_not_called()
        assert "Would merge" in caplog.text
        assert "Would archive" not in caplog.text
        output = capsys.readouterr().out
        data = json.loads(output.strip())
        assert data["archived"] is False

    def test_dry_run_short_flag(self, tmp_path, caplog):
        specs, spec_dir = _setup_topic(tmp_path)
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.merge_branch", mock_merge), \
             caplog.at_level(logging.INFO):
            spex_merge.cli_submit(["my-topic", "-n"])

        mock_merge.assert_not_called()
        assert "Would merge" in caplog.text


@pytest.mark.slow
class TestAutoSelect:
    """Tests for auto-selection when no spec name is provided."""

    def test_auto_select_single_topic(self, tmp_path, caplog):
        specs, spec_dir = _setup_topic(
            tmp_path, spec_name="auto-topic",
            spex_branch="spex/auto", completed=True,
        )
        ctx = _mock_project_context(top_workdir=str(tmp_path))
        mock_merge = MagicMock()

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("branch.branch_exists", return_value=True), \
             patch("branch.merge_branch", mock_merge), \
             patch("hooks.run_post_action"), \
             patch("archive.archive_single_spec", return_value=None), \
             caplog.at_level(logging.ERROR):
            spex_merge.cli_submit([])

        mock_merge.assert_called_once()
        call_args = mock_merge.call_args
        assert call_args[0][1] == "spex/auto"
        assert "Auto-selected: auto-topic" in caplog.text

    def test_auto_select_no_topics(self, tmp_path, caplog):
        specs = tmp_path / "specs"
        specs.mkdir(parents=True)
        ctx = _mock_project_context(top_workdir=str(tmp_path))

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             caplog.at_level(logging.ERROR), \
             pytest.raises(SystemExit) as exc_info:
            spex_merge.cli_submit([])

        assert exc_info.value.code == 1
        assert "No submittable specs found" in caplog.text

    def test_auto_select_multiple_topics_non_interactive(
        self, tmp_path, caplog,
    ):
        specs = tmp_path / "specs"
        _setup_topic(tmp_path, spec_name="topic-a",
                     spex_branch="spex/a", completed=True)
        _setup_topic(tmp_path, spec_name="topic-b",
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


@pytest.mark.slow
class TestNoSpexBranch:
    """Test no spex_branch error path (lines 105-108)."""

    def test_no_spex_branch_exits_with_json(self, monkeypatch, caplog,
                                            capsys, tmp_path):
        """cli_submit exits 1 with JSON error when spec has no spex_branch."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
        (repo / ".spex.toml").write_text(
            f'[spex]\nspex_root = "{tmp_path}/spex"\n', encoding="utf-8"
        )
        specs = tmp_path / "spex" / "specs" / "no-branch-spec"
        specs.mkdir(parents=True)
        (specs / "meta.json").write_text(
            json.dumps({
                "name": "no-branch-spec",
                "workdir": str(repo),
                "branch": "main",
            }),
            encoding="utf-8",
        )
        monkeypatch.chdir(repo)
        spex_common.clear_spex_root_cache()

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                spex_merge.cli_submit(["no-branch-spec"])

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "No spex_branch" in data["errors"][0]


@pytest.mark.slow
class TestNonMergeSubmitMethod:
    """Test non-merge submit method error (lines 145-148)."""

    def test_submit_method_not_implemented(self, monkeypatch, caplog,
                                           capsys, tmp_path):
        """cli_submit exits 1 when submit_method is not 'merge'."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
        (repo / ".spex.toml").write_text(
            f'[spex]\nspex_root = "{tmp_path}/spex"\nsubmit_method = "pr"\n',
            encoding="utf-8",
        )
        specs = tmp_path / "spex" / "specs" / "pr-spec"
        specs.mkdir(parents=True)
        (specs / "meta.json").write_text(
            json.dumps({
                "name": "pr-spec",
                "workdir": str(repo),
                "branch": "main",
                "spex_branch": "spex/pr-spec",
            }),
            encoding="utf-8",
        )
        monkeypatch.chdir(repo)
        spex_common.clear_spex_root_cache()

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                spex_merge.cli_submit(["pr-spec"])

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "not implemented" in data["errors"][0]
