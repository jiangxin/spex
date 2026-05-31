import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from apply_helper import (
    cli_post_action,
    cli_precheck,
    validate_apply_branch,
)
from branch import (
    branch_exists,
    cli_submit,
    get_current_branch,
    merge_branch,
)
from common import strip_date_prefix
from config import SpexContext


def _fake_context(**overrides):
    """Build a SpexContext with sensible defaults, overriding as needed."""
    defaults = {
        "spex_tomls": [],
        "config": {},
        "spex_root": "",
        "spex_roots": [],
        "top_workdir": None,
        "main_worktree": None,
    }
    defaults.update(overrides)
    return SpexContext(**defaults)


class TestStripDatePrefix:
    def test_removes_datetime_prefix(self):
        result = strip_date_prefix("2026-05-26-21-28-add-branch-management")
        assert result == "add-branch-management"

    def test_no_prefix_unchanged(self):
        assert strip_date_prefix("add-login-api") == "add-login-api"

    def test_minimal_suffix(self):
        assert strip_date_prefix("2026-01-01-00-00-x") == "x"


class TestGetCurrentBranch:
    @patch("branch.subprocess.run")
    def test_returns_branch_name(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="main\n", stderr=""
        )
        assert get_current_branch() == "main"
        mock_run.assert_called_once_with(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=None,
        )


class TestBranchExists:
    @patch("branch.subprocess.run")
    def test_branch_exists(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        assert branch_exists("spex/add-feature") is True

    @patch("branch.subprocess.run")
    def test_branch_not_exists(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="fatal: not a valid ref"
        )
        assert branch_exists("spex/nonexistent") is False


class TestMergeBranch:
    @patch("branch.subprocess.run")
    def test_merge_calls_switch_and_merge(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        merge_branch("main", "spex/feature")
        assert mock_run.call_count == 2
        mock_run.assert_any_call(
            ["git", "switch", "main"],
            capture_output=True, text=True, check=True, cwd=None,
        )
        mock_run.assert_any_call(
                ["git", "-c", "merge.branchdesc=true", "-c", "merge.log=true",
                 "merge", "spex/feature", "--no-ff", "--no-edit"],
            capture_output=True, text=True, check=True, cwd=None,
        )

    @patch("branch.subprocess.run")
    def test_merge_raises_on_conflict(self, mock_run):
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="",
                                       stderr=""),
            subprocess.CalledProcessError(1, "git merge",
                                          stderr="CONFLICT"),
        ]
        try:
            merge_branch("main", "spex/feature")
            assert False, "Should have raised"
        except subprocess.CalledProcessError:
            pass


class TestValidateApplyBranch:
    def test_disabled_returns_immediately(self, tmp_path):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps({}), encoding="utf-8")
        # Should return without error when branch_management is False
        validate_apply_branch({"branch_management": False}, tmp_path)

    @patch("common.is_topic_completed", return_value=True)
    def test_completed_topic_exits(self, _mock, tmp_path, capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps({}), encoding="utf-8")
        try:
            validate_apply_branch({"branch_management": True}, tmp_path)
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1

    @patch("branch.get_current_branch", return_value="spex/feat")
    @patch("branch.branch_exists", return_value=True)
    def test_spex_branch_matches_current_noop(self, _exists, _curr, tmp_path):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/feat"}), encoding="utf-8"
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        # Should not call switch_branch since current already matches

    @patch("branch.switch_branch")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=True)
    @patch("common.is_topic_completed", return_value=False)
    def test_spex_branch_switches(self, _completed, _exists, _curr, mock_switch, tmp_path):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/feat"}), encoding="utf-8"
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        mock_switch.assert_called_once_with("spex/feat", None)

    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("common.is_topic_completed", return_value=False)
    def test_spex_branch_missing_exits(self, _completed, _exists, _curr, tmp_path):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/missing"}), encoding="utf-8"
        )
        try:
            validate_apply_branch({"branch_management": True}, tmp_path)
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1

    @patch("branch.switch_branch")
    @patch("branch.set_branch_description")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("branch.create_branch")
    @patch("common.is_topic_completed", return_value=False)
    def test_creates_branch_with_short_name(
        self, _completed, mock_create, _exists, _curr, _desc, mock_switch,
        tmp_path,
    ):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"topic": "2026-05-27-10-00-add-feature"}),
            encoding="utf-8",
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        mock_create.assert_called_once_with("spex/add-feature", None)
        mock_switch.assert_called_once_with("spex/add-feature", None)

    @patch("branch.switch_branch")
    @patch("branch.set_branch_description")
    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("branch.create_branch", side_effect=[
        subprocess.CalledProcessError(1, "git"),
        None,
    ])
    @patch("common.is_topic_completed", return_value=False)
    def test_fallback_to_long_name(
        self, _completed, mock_create, _exists, _curr, _desc, mock_switch,
        tmp_path,
    ):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"topic": "2026-05-27-10-00-add-feature"}),
            encoding="utf-8",
        )
        validate_apply_branch({"branch_management": True}, tmp_path)
        # First call with short name fails, second with long name succeeds
        assert mock_create.call_count == 2
        mock_create.assert_any_call("spex/add-feature", None)
        mock_create.assert_any_call("spex/2026-05-27-10-00-add-feature", None)
        mock_switch.assert_called_once_with(
            "spex/2026-05-27-10-00-add-feature", None
        )

    @patch("branch.get_current_branch", return_value="main")
    @patch("branch.branch_exists", return_value=False)
    @patch("branch.create_branch", side_effect=subprocess.CalledProcessError(1, "git"))
    @patch("common.is_topic_completed", return_value=False)
    def test_both_candidates_fail_exits(
        self, _completed, _create, _exists, _curr, tmp_path,
    ):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"topic": "add-feature"}), encoding="utf-8"
        )
        try:
            validate_apply_branch({"branch_management": True}, tmp_path)
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1


class TestCliPrecheck:
    @patch("common.resolve_topic_dir")
    @patch("config.get_context", return_value=_fake_context(
        config={"branch_management": False}))
    def test_disabled_no_output(self, _ctx, mock_resolve, tmp_path,
                                capsys):
        mock_resolve.return_value = tmp_path
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps({}), encoding="utf-8")
        cli_precheck(["--topic", "test-topic"])
        out = capsys.readouterr().out
        assert out == ""


class TestCliPostAction:
    @patch("common.resolve_topic_dir")
    def test_outputs_text_with_branch(self, mock_resolve, tmp_path, capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/my-feat"}), encoding="utf-8"
        )
        mock_resolve.return_value = tmp_path
        cli_post_action(["--topic", "my-feat"])
        out = capsys.readouterr().out
        assert "spex/my-feat" in out
        assert "Development completed" in out
        assert "main" in out

    @patch("common.resolve_topic_dir")
    @patch("common.load_meta", return_value={})
    def test_no_branch_no_output(self, _meta, _resolve, capsys,
                                 tmp_path):
        _resolve.return_value = tmp_path
        cli_post_action(["--topic", "no-branch"])
        out = capsys.readouterr().out
        assert out == ""


class TestCliSubmit:
    @patch("branch.merge_branch")
    @patch("config.get_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.resolve_topic_dir")
    def test_merge_success(self, mock_resolve, _ctx, mock_merge, tmp_path,
                           capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/done", "branch": "main"}),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        cli_submit(["--topic", "done-topic"])
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "merge"
        assert out["source"] == "spex/done"
        assert out["target"] == "main"
        assert out["errors"] == []
        mock_merge.assert_called_once_with("main", "spex/done", cwd=None)

    @patch("branch.merge_branch",
           side_effect=subprocess.CalledProcessError(1, "git", stderr="CONFLICT"))
    @patch("config.get_context", return_value=_fake_context(
        config={"submit_method": "merge"}))
    @patch("common.resolve_topic_dir")
    def test_merge_failure_exits_nonzero(self, mock_resolve, _ctx, _merge,
                                         tmp_path, capsys):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps({"spex_branch": "spex/conflict", "branch": "main"}),
            encoding="utf-8",
        )
        mock_resolve.return_value = tmp_path
        try:
            cli_submit(["--topic", "conflict"])
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "Merge failed" in out["errors"][0]


class TestCliRouting:
    """Test that the spex CLI routes to branch handlers."""

    SPEX_SCRIPT = str(
        Path(__file__).resolve().parent.parent / "scripts" / "spex"
    )

    def _run_spex(self, *args):
        return subprocess.run(
            [sys.executable, self.SPEX_SCRIPT, *args],
            capture_output=True,
            text=True,
        )

    def test_create_helper_no_flag_exits(self):
        result = self._run_spex("create-helper")
        assert result.returncode in (1, 2)
        assert "Usage:" in result.stderr

    def test_apply_helper_no_flag_exits(self):
        result = self._run_spex("apply-helper")
        assert result.returncode in (1, 2)
        assert "Usage:" in result.stderr

    def test_submit_no_topic_exits(self):
        result = self._run_spex("submit")
        assert result.returncode in (1, 2)
        assert "--topic" in result.stderr
