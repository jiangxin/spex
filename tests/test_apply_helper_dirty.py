"""Unit tests for apply_helper dirty detection (Phase 4 algorithm)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import apply_helper
import pytest
from apply_helper import (
    compute_dirty_from_porcelain,
    is_under_spex_root,
    parse_porcelain_paths,
    resolve_repo_path,
    strip_porcelain_quotes,
)
from config import ProjectContext, clear_config_cache

TOPLEVEL = "/repo"


def _ctx(**overrides):
    defaults = {
        "cwd": Path(TOPLEVEL),
        "top_workdir": Path(TOPLEVEL),
        "main_worktree": Path(TOPLEVEL),
        "remote_url": "",
        "branch": "main",
        "user_name": "",
        "user_email": "",
        "spex_tomls": [],
        "config": {},
        "spex_root": f"{TOPLEVEL}/.spex",
        "spex_roots": [f"{TOPLEVEL}/.spex"],
    }
    defaults.update(overrides)
    return ProjectContext(**defaults)


class TestStripPorcelainQuotes:
    def test_quoted(self):
        assert strip_porcelain_quotes('"space name.txt"') == "space name.txt"

    def test_unquoted(self):
        assert strip_porcelain_quotes("README.md") == "README.md"


class TestParsePorcelainPaths:
    def test_modified(self):
        assert parse_porcelain_paths(" M README.md") == ["README.md"]

    def test_untracked_quoted(self):
        assert parse_porcelain_paths('?? "space name.txt"') == ["space name.txt"]

    def test_rename_both_sides(self):
        assert parse_porcelain_paths("R  old.txt -> new.txt") == [
            "old.txt",
            "new.txt",
        ]

    def test_rename_quoted(self):
        assert parse_porcelain_paths('R  "old a" -> "new b"') == [
            "old a",
            "new b",
        ]


class TestIsUnderSpexRoot:
    def test_equal(self):
        assert is_under_spex_root("/repo/.spex", "/repo/.spex")

    def test_child(self):
        assert is_under_spex_root(
            "/repo/.spex/specs/x", "/repo/.spex",
        )

    def test_toml_boundary_not_under(self):
        """`.spex.toml` must not match bare prefix of `.spex`."""
        assert not is_under_spex_root(
            "/repo/.spex.toml", "/repo/.spex",
        )

    def test_sibling_not_under(self):
        assert not is_under_spex_root("/repo/README.md", "/repo/.spex")


class TestResolveRepoPath:
    def test_relative(self):
        assert resolve_repo_path("a/b", "/repo") == "/repo/a/b"

    def test_absolute(self):
        assert resolve_repo_path("/abs/x", "/repo") == "/abs/x"


class TestComputeDirtyFromPorcelain:
    """Encode apply.md Phase 4 six-step algorithm."""

    spex_root = f"{TOPLEVEL}/.spex"

    def test_clean_tree(self):
        dirty, paths = compute_dirty_from_porcelain(
            "", self.spex_root, TOPLEVEL,
        )
        assert dirty is False
        assert paths == []

    def test_spex_root_only_not_dirty(self):
        porcelain = (
            " M .spex/specs/foo/todo.json\n"
            "?? .spex/specs/foo/debug.log\n"
        )
        dirty, paths = compute_dirty_from_porcelain(
            porcelain, self.spex_root, TOPLEVEL,
        )
        assert dirty is False
        assert paths == []

    def test_dirty_outside(self):
        porcelain = " M README.md\n M .spex/specs/x/meta.json\n"
        dirty, paths = compute_dirty_from_porcelain(
            porcelain, self.spex_root, TOPLEVEL,
        )
        assert dirty is True
        assert paths == [f"{TOPLEVEL}/README.md"]

    def test_spex_toml_boundary(self):
        porcelain = " M .spex.toml\n"
        dirty, paths = compute_dirty_from_porcelain(
            porcelain, self.spex_root, TOPLEVEL,
        )
        assert dirty is True
        assert paths == [f"{TOPLEVEL}/.spex.toml"]

    def test_rename_both_under_spex_root(self):
        porcelain = "R  .spex/a.txt -> .spex/b.txt\n"
        dirty, paths = compute_dirty_from_porcelain(
            porcelain, self.spex_root, TOPLEVEL,
        )
        assert dirty is False
        assert paths == []

    def test_rename_one_side_outside(self):
        porcelain = "R  .spex/a.txt -> src/a.txt\n"
        dirty, paths = compute_dirty_from_porcelain(
            porcelain, self.spex_root, TOPLEVEL,
        )
        assert dirty is True
        assert paths == [f"{TOPLEVEL}/src/a.txt"]

    def test_rename_both_outside(self):
        porcelain = "R  old.txt -> new.txt\n"
        dirty, paths = compute_dirty_from_porcelain(
            porcelain, self.spex_root, TOPLEVEL,
        )
        assert dirty is True
        assert paths == [
            f"{TOPLEVEL}/old.txt",
            f"{TOPLEVEL}/new.txt",
        ]


class TestDirtyCli:
    def setup_method(self):
        clear_config_cache()

    def teardown_method(self):
        clear_config_cache()

    def test_json_output(self, capsys, tmp_path):
        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        ctx = _ctx(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
        )

        def fake_check_output(cmd, **kwargs):
            if cmd[:2] == ["git", "rev-parse"]:
                return f"{tmp_path}\n"
            if cmd[:2] == ["git", "status"]:
                return " M README.md\n"
            raise AssertionError(cmd)

        with patch("config.get_project_context", return_value=ctx):
            with patch(
                "apply_helper.subprocess.check_output",
                side_effect=fake_check_output,
            ):
                apply_helper.main(["dirty", "--json"])

        out = json.loads(capsys.readouterr().out)
        assert out["dirty"] is True
        assert out["paths"] == [str(tmp_path / "README.md")]
        assert out["spex_root"] == str(spex_root.resolve())

    def test_spex_root_override(self, capsys, tmp_path):
        override = tmp_path / "custom-spex"
        override.mkdir()
        ctx = _ctx(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            spex_root=str(tmp_path / ".spex"),
        )

        def fake_check_output(cmd, **kwargs):
            if cmd[:2] == ["git", "rev-parse"]:
                return f"{tmp_path}\n"
            if cmd[:2] == ["git", "status"]:
                return " M custom-spex/x\n M other.txt\n"
            raise AssertionError(cmd)

        with patch("config.get_project_context", return_value=ctx):
            with patch(
                "apply_helper.subprocess.check_output",
                side_effect=fake_check_output,
            ):
                apply_helper.main([
                    "dirty", "--json",
                    "--spex-root", str(override),
                ])

        out = json.loads(capsys.readouterr().out)
        assert out["dirty"] is True
        assert out["paths"] == [str(tmp_path / "other.txt")]
        assert out["spex_root"] == str(override.resolve())

    def test_git_failure_nonzero(self, tmp_path):
        ctx = _ctx(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            spex_root=str(tmp_path / ".spex"),
        )
        err = subprocess.CalledProcessError(
            128, ["git", "status"], stderr="not a git repository",
        )
        with patch("config.get_project_context", return_value=ctx):
            with patch(
                "apply_helper.subprocess.check_output",
                side_effect=err,
            ):
                with pytest.raises(SystemExit) as exc:
                    apply_helper.main(["dirty", "--json"])
        assert exc.value.code == 128
