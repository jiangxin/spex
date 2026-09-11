"""Integration tests: merge on target worktree; archive removes worktree."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from archive import archive_single_spec
from branch import get_current_branch
from common import SpecMeta, clear_spex_root_cache, load_meta
from config import ProjectContext, clear_config_cache
from merge import cli_submit
from worktree import (
    add_worktree,
    is_registered_worktree,
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


def _write_completed_spec(
    spec_dir: Path,
    *,
    main: Path,
    spex_branch: str,
    spex_worktree: str = "",
    branch: str = "main",
) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    meta = SpecMeta(
        name=spec_dir.name,
        workdir=str(main),
        main_worktree=str(main),
        branch=branch,
        spex_branch=spex_branch,
        use_git_worktree=bool(spex_worktree),
        spex_worktree=spex_worktree,
    )
    (spec_dir / "meta.json").write_text(
        json.dumps(meta.to_dict()), encoding="utf-8",
    )
    (spec_dir / "todo.json").write_text(
        json.dumps([{
            "id": "1",
            "name": "done",
            "details": "",
            "completed_at": "2026-01-01T00:00:00Z",
            "commit_title": "feat: done",
        }]),
        encoding="utf-8",
    )


@pytest.mark.slow
class TestMergeOnTargetWorktree:
    def test_merge_succeeds_while_feature_locked_in_worktree(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Feature branch locked in spex worktree; merge on main succeeds."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spex_root = tmp_path / "spex"
        specs = spex_root / "specs"
        archives = spex_root / "archives"
        (main / ".spex.toml").write_text(
            f'[spex]\nspex_root = "{spex_root}"\n',
            encoding="utf-8",
        )

        spec_name = "2026-09-10-19-36-feat"
        wt_path = resolve_spex_worktree_path(main, spec_name)
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

        spec_dir = specs / spec_name
        _write_completed_spec(
            spec_dir,
            main=main,
            spex_branch="spex/feat",
            spex_worktree=str(wt_path),
            branch=main_branch,
        )

        clear_config_cache()
        clear_spex_root_cache()
        monkeypatch.chdir(main)

        ctx = ProjectContext(
            cwd=main,
            top_workdir=main,
            main_worktree=main,
            remote_url="",
            branch=main_branch,
            user_name="Test",
            user_email="test@example.com",
            config={"submit_method": "merge"},
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("common.get_archives_dir", return_value=archives), \
             patch("hooks.run_pre_action"), \
             patch("hooks.run_post_action"):
            cli_submit([spec_name, "--no-archive"])

        out = json.loads(capsys.readouterr().out)
        assert out["errors"] == []
        assert out["source"] == "spex/feat"
        assert out["target"] == main_branch
        assert get_current_branch(main) == main_branch
        assert (main / "feature.txt").is_file()
        # Feature worktree still holds the branch (archive skipped).
        assert is_registered_worktree(wt_path, cwd=main)
        assert get_current_branch(wt_path) == "spex/feat"

    def test_legacy_submit_when_target_not_checked_out(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Legacy in-place apply: main is on spex/*; submit still merges."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        # Legacy apply: switch main worktree onto the feature branch
        # (no linked spex worktree). Target trunk is then not checked out
        # anywhere until merge falls back to main_worktree and switches.
        subprocess.run(
            ["git", "switch", "-c", "spex/feat"],
            cwd=main, check=True, capture_output=True,
        )
        (main / "feature.txt").write_text("feat\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "feature.txt"],
            cwd=main, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feature"],
            cwd=main, check=True, capture_output=True,
        )

        spex_root = tmp_path / "spex"
        specs = spex_root / "specs"
        archives = spex_root / "archives"
        (main / ".spex.toml").write_text(
            f'[spex]\nspex_root = "{spex_root}"\n',
            encoding="utf-8",
        )

        spec_name = "legacy-feat"
        _write_completed_spec(
            specs / spec_name,
            main=main,
            spex_branch="spex/feat",
            spex_worktree="",
            branch=main_branch,
        )

        clear_config_cache()
        clear_spex_root_cache()
        monkeypatch.chdir(main)

        ctx = ProjectContext(
            cwd=main,
            top_workdir=main,
            main_worktree=main,
            remote_url="",
            branch="spex/feat",
            user_name="Test",
            user_email="test@example.com",
            config={"submit_method": "merge"},
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("common.get_archives_dir", return_value=archives), \
             patch("hooks.run_pre_action"), \
             patch("hooks.run_post_action"):
            cli_submit([spec_name, "--no-archive"])

        out = json.loads(capsys.readouterr().out)
        assert out["errors"] == []
        assert out["source"] == "spex/feat"
        assert out["target"] == main_branch
        assert get_current_branch(main) == main_branch
        assert (main / "feature.txt").is_file()


@pytest.mark.slow
class TestMergeDryRunWorktree:
    def test_dry_run_exposes_worktree_ops(
        self, tmp_path, monkeypatch, capsys, caplog,
    ):
        """Worktree mode: dry-run JSON/logs show merge cwd + remove plan."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spex_root = tmp_path / "spex"
        specs = spex_root / "specs"
        archives = spex_root / "archives"
        (main / ".spex.toml").write_text(
            f'[spex]\nspex_root = "{spex_root}"\n',
            encoding="utf-8",
        )

        spec_name = "2026-09-10-19-36-dry-run-wt"
        wt_path = resolve_spex_worktree_path(main, spec_name)
        add_worktree(wt_path, "spex/dry-run-feat", cwd=main)
        (wt_path / "feature.txt").write_text("feat\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "feature.txt"],
            cwd=wt_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feature"],
            cwd=wt_path, check=True, capture_output=True,
        )
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=main, check=True, capture_output=True, text=True,
        ).stdout.strip()

        _write_completed_spec(
            specs / spec_name,
            main=main,
            spex_branch="spex/dry-run-feat",
            spex_worktree=str(wt_path),
            branch=main_branch,
        )

        clear_config_cache()
        clear_spex_root_cache()
        monkeypatch.chdir(main)

        ctx = ProjectContext(
            cwd=main,
            top_workdir=main,
            main_worktree=main,
            remote_url="",
            branch=main_branch,
            user_name="Test",
            user_email="test@example.com",
            config={"submit_method": "merge"},
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("common.get_archives_dir", return_value=archives), \
             patch("hooks.run_pre_action"), \
             patch("hooks.run_post_action"), \
             caplog.at_level(logging.INFO):
            cli_submit([spec_name, "--dry-run"])

        out = json.loads(capsys.readouterr().out)
        assert out["dry_run"] is True
        assert out["errors"] == []
        assert out["source"] == "spex/dry-run-feat"
        assert out["target"] == main_branch
        assert out["archived"] is True
        assert Path(out["merge_cwd"]).resolve() == main.resolve()
        assert out["spex_worktree"] == str(wt_path)
        assert out["would_remove_worktree"] is True
        assert out["merge_cwd_head"] == main_branch
        assert out["would_switch"] is False
        assert out["target_checked_out"] is True
        assert "Would merge in worktree" in caplog.text
        assert "Would git merge" in caplog.text
        assert "Would switch to" not in caplog.text
        assert "Feature worktree" in caplog.text
        assert "Would remove worktree" in caplog.text

        # Repo unchanged: no merge, worktree still registered, HEAD same.
        head_after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=main, check=True, capture_output=True, text=True,
        ).stdout.strip()
        assert head_after == head_before
        assert get_current_branch(main) == main_branch
        assert not (main / "feature.txt").exists()
        assert is_registered_worktree(wt_path, cwd=main)
        assert (specs / spec_name).is_dir()

    def test_dry_run_legacy_no_spex_worktree(
        self, tmp_path, monkeypatch, capsys, caplog,
    ):
        """Legacy: merge_cwd is main worktree; would_remove_worktree=false."""
        main = tmp_path / "repo"
        _git_init_with_commit(main)
        main_branch = get_current_branch(main)

        spex_root = tmp_path / "spex"
        specs = spex_root / "specs"
        (main / ".spex.toml").write_text(
            f'[spex]\nspex_root = "{spex_root}"\n',
            encoding="utf-8",
        )

        # Feature commit on a branch that is not checked out elsewhere.
        subprocess.run(
            ["git", "branch", "spex/legacy-dry"],
            cwd=main, check=True, capture_output=True,
        )

        spec_name = "legacy-dry-run"
        _write_completed_spec(
            specs / spec_name,
            main=main,
            spex_branch="spex/legacy-dry",
            spex_worktree="",
            branch=main_branch,
        )

        clear_config_cache()
        clear_spex_root_cache()
        monkeypatch.chdir(main)

        ctx = ProjectContext(
            cwd=main,
            top_workdir=main,
            main_worktree=main,
            remote_url="",
            branch=main_branch,
            user_name="Test",
            user_email="test@example.com",
            config={"submit_method": "merge"},
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
        )

        with patch("config.get_project_context", return_value=ctx), \
             patch("common.get_specs_dir", return_value=specs), \
             patch("hooks.run_pre_action"), \
             patch("hooks.run_post_action"), \
             caplog.at_level(logging.INFO):
            cli_submit([spec_name, "--dry-run"])

        out = json.loads(capsys.readouterr().out)
        assert out["dry_run"] is True
        assert out["errors"] == []
        assert Path(out["merge_cwd"]).resolve() == main.resolve()
        assert out["spex_worktree"] == ""
        assert out["would_remove_worktree"] is False
        assert out["archived"] is True
        assert out["would_switch"] is False
        assert out["target_checked_out"] is True
        assert out["merge_cwd_head"] == main_branch
        assert "Would merge in worktree" in caplog.text
        assert "Would git merge" in caplog.text
        assert "Feature worktree" not in caplog.text
        assert "Would remove worktree" not in caplog.text
        assert get_current_branch(main) == main_branch


@pytest.mark.slow
class TestArchiveDryRunWorktree:
    def test_archive_dry_run_shows_worktree_remove_cmd(
        self, tmp_path, monkeypatch, capsys, caplog,
    ):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)

        spex_root = tmp_path / "spex"
        specs = spex_root / "specs"
        archives = spex_root / "archives"
        archives.mkdir(parents=True)

        spec_name = "2026-09-10-19-36-archive-dry"
        wt_path = resolve_spex_worktree_path(main, spec_name)
        add_worktree(wt_path, "spex/archive-dry", cwd=main)

        spec_dir = specs / spec_name
        _write_completed_spec(
            spec_dir,
            main=main,
            spex_branch="spex/archive-dry",
            spex_worktree=str(wt_path),
        )

        import archive as spex_archive

        with patch.object(
            spex_archive, "get_specs_dir", return_value=specs,
        ), patch.object(
            spex_archive, "get_archives_dir", return_value=archives,
        ), caplog.at_level(logging.INFO):
            spex_archive.main([
                "--json", "--name", spec_name, "-n", "-f",
            ])

        data = json.loads(capsys.readouterr().out)
        assert data["dry_run"] is True
        item = data["results"][0]
        assert item["action"] == "would_archive"
        assert item["would_remove_worktree"] is True
        assert item["spex_worktree"] == str(wt_path)
        assert item["worktree_remove_cwd"] == str(main)
        assert item["worktree_remove_cmd"] == (
            f"git worktree remove --force {wt_path}"
        )
        assert "Would run: git worktree remove --force" in caplog.text
        assert f"(cwd: {main})" in caplog.text
        # Dry-run must not remove the worktree.
        assert is_registered_worktree(wt_path, cwd=main)
        assert (specs / spec_name).is_dir()


@pytest.mark.slow
class TestArchiveRemovesWorktree:
    def test_archive_deletes_worktree(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)

        spex_root = tmp_path / "spex"
        specs = spex_root / "specs"
        archives = spex_root / "archives"
        archives.mkdir(parents=True)

        spec_name = "2026-09-10-19-36-archive-wt"
        wt_path = resolve_spex_worktree_path(main, spec_name)
        add_worktree(wt_path, "spex/archive-feat", cwd=main)
        assert is_registered_worktree(wt_path, cwd=main)

        spec_dir = specs / spec_name
        _write_completed_spec(
            spec_dir,
            main=main,
            spex_branch="spex/archive-feat",
            spex_worktree=str(wt_path),
        )

        # Branch still exists — use force like submit's auto-archive.
        dest = archive_single_spec(
            spec_name, specs, archives, force=True,
        )
        assert dest is not None
        assert dest.is_dir()
        assert not spec_dir.exists()
        assert not is_registered_worktree(wt_path, cwd=main)
        assert not wt_path.exists()
        # Branch itself is intentionally kept (archive does not delete it).
        assert subprocess.run(
            ["git", "rev-parse", "--verify", "refs/heads/spex/archive-feat"],
            cwd=main, capture_output=True,
        ).returncode == 0

    def test_archive_deletes_worktree_without_force(
        self, tmp_path, monkeypatch,
    ):
        """After clearing active-branch skip, force=False still removes wt."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        main = tmp_path / "repo"
        _git_init_with_commit(main)

        spex_root = tmp_path / "spex"
        specs = spex_root / "specs"
        archives = spex_root / "archives"
        archives.mkdir(parents=True)

        spec_name = "2026-09-10-19-36-archive-noforce"
        wt_path = resolve_spex_worktree_path(main, spec_name)
        add_worktree(wt_path, "spex/archive-noforce", cwd=main)
        assert is_registered_worktree(wt_path, cwd=main)

        spec_dir = specs / spec_name
        _write_completed_spec(
            spec_dir,
            main=main,
            spex_branch="spex/archive-noforce",
            spex_worktree=str(wt_path),
        )

        # Rename the branch so has_active_branch no longer blocks archive.
        subprocess.run(
            ["git", "branch", "-m", "spex/archive-noforce",
             "spex/archive-noforce-old"],
            cwd=main, check=True, capture_output=True,
        )

        dest = archive_single_spec(
            spec_name, specs, archives, force=False,
        )
        assert dest is not None
        assert dest.is_dir()
        assert not spec_dir.exists()
        assert not is_registered_worktree(wt_path, cwd=main)
        assert not wt_path.exists()

    def test_archive_without_spex_worktree_unchanged(
        self, tmp_path, monkeypatch,
    ):
        main = tmp_path / "repo"
        _git_init_with_commit(main)
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        archives.mkdir()

        spec_dir = specs / "plain-spec"
        _write_completed_spec(
            spec_dir,
            main=main,
            spex_branch="spex/plain",
            spex_worktree="",
        )
        # Create the branch so has_active_branch would skip without force.
        subprocess.run(
            ["git", "branch", "spex/plain"],
            cwd=main, check=True, capture_output=True,
        )

        dest = archive_single_spec(
            "plain-spec", specs, archives, force=True,
        )
        assert dest is not None
        assert dest.is_dir()
        meta = load_meta(dest)
        assert meta is not None
        assert meta.spex_worktree == ""
