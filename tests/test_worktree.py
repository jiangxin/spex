"""Unit tests for worktree.py helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from branch import get_current_branch, merge_branch
from worktree import (
    add_worktree,
    checkout_commit,
    find_worktree_for_branch,
    is_registered_worktree,
    remove_worktree,
    resolve_spex_worktree_path,
    worktree_root,
)


def _git_init_with_commit(repo: Path) -> None:
    """Initialize a git repo with one commit on main."""
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, check=True, capture_output=True,
    )
    (repo / "README").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, check=True, capture_output=True,
    )


class TestPathHelpers:
    def test_worktree_root_uses_singular_worktree(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        root = worktree_root()
        assert root == tmp_path / ".spex" / "worktree"
        assert root.name == "worktree"
        assert "worktrees" not in str(root)

    def test_resolve_spex_worktree_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        main = tmp_path / "repos" / "my-project"
        main.mkdir(parents=True)
        path = resolve_spex_worktree_path(main, "2026-09-10-19-36-topic")
        assert path == (
            tmp_path / ".spex" / "worktree" / "my-project"
            / "2026-09-10-19-36-topic"
        )


class TestMergeBranchSkipSwitch:
    @patch("branch.subprocess.run")
    def test_skips_switch_when_already_on_target(self, mock_run):
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="main\n", stderr="",
            ),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            ),
        ]
        merge_branch("main", "spex/feature")
        assert mock_run.call_count == 2
        first = mock_run.call_args_list[0][0][0]
        assert first[:3] == ["git", "symbolic-ref", "--short"]
        second = mock_run.call_args_list[1][0][0]
        assert second[0:1] == ["git"]
        assert "merge" in second
        assert "switch" not in second

    @patch("branch.subprocess.run")
    def test_switches_when_not_on_target(self, mock_run):
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="feature\n", stderr="",
            ),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            ),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            ),
        ]
        merge_branch("main", "spex/feature")
        assert mock_run.call_count == 3
        switch_cmd = mock_run.call_args_list[1][0][0]
        assert switch_cmd == ["git", "switch", "main"]


@pytest.mark.slow
class TestWorktreeGitOps:
    def test_add_remove_find_checkout(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)

        wt_path = resolve_spex_worktree_path(main, "spec-a")
        add_worktree(wt_path, "spex/feat", cwd=main)

        assert wt_path.is_dir()
        assert is_registered_worktree(wt_path, cwd=main)
        assert find_worktree_for_branch("spex/feat", cwd=main) == wt_path
        assert find_worktree_for_branch("main", cwd=main) == main.resolve()
        assert get_current_branch(wt_path) == "spex/feat"

        # Second worktree for an existing branch should fail if same branch;
        # instead create another branch from existing.
        wt_b = resolve_spex_worktree_path(main, "spec-b")
        add_worktree(wt_b, "spex/other", base="main", cwd=main)
        assert find_worktree_for_branch("spex/other", cwd=main) == wt_b

        tip = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=main, capture_output=True, text=True, check=True,
        ).stdout.strip()
        checkout_commit(wt_b, tip)
        head_state = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=wt_b, capture_output=True, text=True,
        )
        assert head_state.returncode != 0  # detached

        remove_worktree(wt_path, cwd=main)
        assert not is_registered_worktree(wt_path, cwd=main)
        assert find_worktree_for_branch("spex/feat", cwd=main) is None

        # No-op when already gone
        remove_worktree(wt_path, cwd=main)

        remove_worktree(wt_b, force=True, cwd=main)
        assert not is_registered_worktree(wt_b, cwd=main)

    def test_add_existing_branch(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        subprocess.run(
            ["git", "branch", "spex/ready"],
            cwd=main, check=True, capture_output=True,
        )

        wt_path = resolve_spex_worktree_path(main, "ready-spec")
        add_worktree(wt_path, "spex/ready", cwd=main)
        assert get_current_branch(wt_path) == "spex/ready"
        assert is_registered_worktree(wt_path, cwd=main)
        remove_worktree(wt_path, cwd=main)

    def test_merge_without_switch_in_target_worktree(
        self, tmp_path, monkeypatch,
    ):
        """Merge into main while feature is locked in another worktree."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)

        wt_path = resolve_spex_worktree_path(main, "feat-spec")
        add_worktree(wt_path, "spex/feat", cwd=main)
        (wt_path / "feature.txt").write_text("feat\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "feature.txt"],
            cwd=wt_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feature"],
            cwd=wt_path, check=True, capture_output=True,
        )

        # Must succeed without switching main away (feature holds spex/feat)
        merge_branch("main", "spex/feat", cwd=main)
        assert get_current_branch(main) == "main"
        assert (main / "feature.txt").is_file()

        remove_worktree(wt_path, force=True, cwd=main)
