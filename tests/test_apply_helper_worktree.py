"""Tests for apply_helper worktree mode (meta.use_git_worktree)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from apply_helper import (
    resolve_apply_git_cwd,
    validate_apply_branch,
)
from branch import get_current_branch
from common import SpecMeta, load_meta
from worktree import (
    is_registered_worktree,
    remove_worktree,
    resolve_spex_worktree_path,
)


def _git_init_with_commit(repo: Path, branch: str = "main") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", branch],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, check=True, capture_output=True,
    )
    (repo / "README").write_text("hello\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README"], cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, check=True, capture_output=True,
    )


def _write_spec(
    spec_dir: Path,
    *,
    use_git_worktree: bool,
    main_worktree: Path,
    name: str | None = None,
    branch: str = "main",
    spex_branch: str = "",
) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name or spec_dir.name,
        "main_worktree": str(main_worktree),
        "branch": branch,
        "use_git_worktree": use_git_worktree,
    }
    if spex_branch:
        meta["spex_branch"] = spex_branch
    (spec_dir / "meta.json").write_text(
        json.dumps(meta), encoding="utf-8",
    )
    (spec_dir / "todo.json").write_text(
        json.dumps([{"id": "t1", "name": "work"}]),
        encoding="utf-8",
    )


class TestResolveApplyGitCwd:
    def test_prefers_spex_worktree(self):
        meta = SpecMeta(spex_worktree="/wt/path")
        assert resolve_apply_git_cwd(meta, "/fallback") == "/wt/path"

    def test_falls_back_when_empty(self):
        meta = SpecMeta(spex_worktree="")
        assert resolve_apply_git_cwd(meta, "/fallback") == "/fallback"

    def test_none_meta(self):
        assert resolve_apply_git_cwd(None, "/fallback") == "/fallback"


@pytest.mark.slow
class TestValidateApplyWorktree:
    def test_meta_true_creates_worktree_and_records_path(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "2026-09-10-19-36-topic"
        spec_dir = tmp_path / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=True,
            main_worktree=main,
            branch=main_branch,
        )

        validate_apply_branch(
            {"branch_management": True},
            spec_dir,
            cwd=main,
        )

        meta = load_meta(spec_dir)
        assert meta is not None
        assert meta.use_git_worktree is True
        assert meta.spex_branch.startswith("spex/")
        assert meta.spex_worktree
        expected = resolve_spex_worktree_path(main, spec_name)
        assert Path(meta.spex_worktree).resolve() == expected.resolve()
        assert is_registered_worktree(meta.spex_worktree, cwd=main)
        assert get_current_branch(meta.spex_worktree) == meta.spex_branch
        # Main worktree must stay on the base branch (no in-place switch).
        assert get_current_branch(main) == main_branch

        remove_worktree(meta.spex_worktree, force=True, cwd=main)

    def test_meta_false_does_not_create_or_record_worktree(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "2026-09-10-19-36-inplace"
        spec_dir = tmp_path / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=False,
            main_worktree=main,
            branch=main_branch,
        )

        validate_apply_branch(
            {"branch_management": True},
            spec_dir,
            cwd=main,
        )

        meta = load_meta(spec_dir)
        assert meta is not None
        assert meta.use_git_worktree is False
        assert meta.spex_branch.startswith("spex/")
        assert meta.spex_worktree == ""
        expected = resolve_spex_worktree_path(main, spec_name)
        assert not expected.exists()
        assert get_current_branch(main) == meta.spex_branch

    def test_meta_true_reuses_existing_worktree(
        self, tmp_path, monkeypatch,
    ):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "reuse-spec"
        spec_dir = tmp_path / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=True,
            main_worktree=main,
            branch=main_branch,
        )

        validate_apply_branch(
            {"branch_management": True}, spec_dir, cwd=main,
        )
        meta1 = load_meta(spec_dir)
        assert meta1 is not None
        path1 = meta1.spex_worktree
        branch1 = meta1.spex_branch

        validate_apply_branch(
            {"branch_management": True}, spec_dir, cwd=main,
        )
        meta2 = load_meta(spec_dir)
        assert meta2 is not None
        assert meta2.spex_worktree == path1
        assert meta2.spex_branch == branch1
        assert is_registered_worktree(path1, cwd=main)

        remove_worktree(path1, force=True, cwd=main)

    def test_old_meta_missing_use_git_worktree_is_inplace(
        self, tmp_path, monkeypatch,
    ):
        """Absent use_git_worktree key → False → no spex_worktree."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "legacy-spec"
        spec_dir = tmp_path / "specs" / spec_name
        spec_dir.mkdir(parents=True)
        (spec_dir / "meta.json").write_text(
            json.dumps({
                "name": spec_name,
                "main_worktree": str(main),
                "branch": main_branch,
            }),
            encoding="utf-8",
        )
        (spec_dir / "todo.json").write_text(
            json.dumps([{"id": "t1", "name": "work"}]),
            encoding="utf-8",
        )

        validate_apply_branch(
            {"branch_management": True}, spec_dir, cwd=main,
        )
        meta = load_meta(spec_dir)
        assert meta is not None
        assert meta.use_git_worktree is False
        assert meta.spex_worktree == ""
        assert not resolve_spex_worktree_path(main, spec_name).exists()


@pytest.mark.slow
class TestPrecheckWorktreeOutput:
    def test_precheck_prints_coding_path(self, tmp_path, monkeypatch, capsys):
        from apply_helper import cli_precheck
        from config import ProjectContext

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "precheck-wt"
        spec_dir = tmp_path / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=True,
            main_worktree=main,
            branch=main_branch,
        )

        ctx = ProjectContext(
            cwd=main,
            top_workdir=main,
            main_worktree=main,
            remote_url="",
            branch=main_branch,
            user_name="",
            user_email="",
            spex_tomls=[],
            config={"branch_management": True},
            spex_root=str(tmp_path / ".spex"),
            spex_roots=[str(tmp_path / ".spex")],
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.resolve_spec_dir", return_value=spec_dir), \
             patch("hooks.run_pre_action"):
            cli_precheck(["--name", spec_name])

        out = capsys.readouterr().out.strip()
        payload = json.loads(out)
        meta = load_meta(spec_dir)
        assert meta is not None
        assert payload["spex_worktree"] == meta.spex_worktree
        assert payload["coding_path"] == meta.spex_worktree
        assert payload["spex_branch"] == meta.spex_branch

        remove_worktree(meta.spex_worktree, force=True, cwd=main)


@pytest.mark.slow
class TestDirtyNameWorktreeCwd:
    def test_dirty_name_reports_worktree_dirtiness(
        self, tmp_path, monkeypatch, capsys,
    ):
        """dirty --name must use meta.spex_worktree as git cwd."""
        from apply_helper import cli_dirty
        from config import ProjectContext

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spec_name = "dirty-wt-spec"
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / spec_name
        _write_spec(
            spec_dir,
            use_git_worktree=True,
            main_worktree=main,
            branch=main_branch,
        )

        validate_apply_branch(
            {"branch_management": True},
            spec_dir,
            cwd=main,
        )
        meta = load_meta(spec_dir)
        assert meta is not None
        assert meta.spex_worktree

        # Dirty the worktree only; leave main clean.
        dirty_file = Path(meta.spex_worktree) / "wt-dirty.txt"
        dirty_file.write_text("dirty\n", encoding="utf-8")

        ctx = ProjectContext(
            cwd=main,
            top_workdir=main,
            main_worktree=main,
            remote_url="",
            branch=main_branch,
            user_name="",
            user_email="",
            spex_tomls=[],
            config={"branch_management": True},
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.resolve_spec_dir", return_value=spec_dir):
            cli_dirty(["--name", spec_name, "--json"])

        out = json.loads(capsys.readouterr().out.strip())
        assert out["dirty"] is True
        wt_resolved = str(Path(meta.spex_worktree).resolve())
        assert all(
            str(Path(p).resolve()).startswith(wt_resolved)
            for p in out["paths"]
        ), out["paths"]

        # Main worktree must still be clean.
        main_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=main,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert main_status.strip() == ""

        remove_worktree(meta.spex_worktree, force=True, cwd=main)
