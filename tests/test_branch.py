import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from branch import branch_exists, get_current_branch, strip_date_prefix


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
