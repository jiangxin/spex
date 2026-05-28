"""Tests for config.py: hierarchical TOML discovery, merging, and caching."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from config import (
    _deep_merge,
    _find_spex_tomls,
    _get_worktree_root,
    _load_toml_config,
    _merge_configs,
    clear_config_cache,
    load_config,
)


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    monkeypatch.delenv("SPEX_ROOT", raising=False)
    clear_config_cache()
    yield
    clear_config_cache()


# ===================== _load_toml_config =====================


class TestLoadTomlConfig:
    def test_valid_toml(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text('spex_root = "/my/spex"\n', encoding="utf-8")

        result = _load_toml_config(p)

        assert result == {"spex_root": "/my/spex"}

    def test_invalid_toml(self, tmp_path):
        p = tmp_path / "bad.toml"
        p.write_text("this is not [valid\n", encoding="utf-8")

        assert _load_toml_config(p) is None

    def test_nonexistent_file(self, tmp_path):
        p = tmp_path / "nope.toml"

        assert _load_toml_config(p) is None

    def test_empty_toml(self, tmp_path):
        p = tmp_path / "empty.toml"
        p.write_text("", encoding="utf-8")

        result = _load_toml_config(p)
        assert result == {}


# ===================== _deep_merge =====================


class TestDeepMerge:
    def test_override_takes_precedence(self):
        base = {"spex_root": "/base", "other": 1}
        override = {"spex_root": "/override"}

        result = _deep_merge(base, override)

        assert result["spex_root"] == "/override"
        assert result["other"] == 1

    def test_nested_merge(self):
        base = {"nested": {"a": 1, "b": 2}}
        override = {"nested": {"b": 99, "c": 3}}

        result = _deep_merge(base, override)

        assert result["nested"] == {"a": 1, "b": 99, "c": 3}

    def test_empty_override_no_change(self):
        base = {"spex_root": "/base", "x": 1}
        result = _deep_merge(base, {})
        assert result == base


# ===================== _find_spex_tomls =====================


class TestFindSpexTomls:
    def test_single_file_at_worktree_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        (tmp_path / ".spex.toml").write_text('spex_root = ".spex"\n', encoding="utf-8")

        result = _find_spex_tomls(tmp_path)

        assert len(result) == 1
        assert result[0] == tmp_path / ".spex.toml"

    def test_hierarchy_worktree_and_parent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        # Parent has .spex.toml
        (tmp_path / ".spex.toml").write_text(
            'submit_method = "pr"\n', encoding="utf-8"
        )
        # Worktree root (child) also has .spex.toml
        child = tmp_path / "projects" / "myrepo"
        child.mkdir(parents=True)
        (child / ".spex.toml").write_text('spex_root = ".spex"\n', encoding="utf-8")

        result = _find_spex_tomls(child)

        # Highest priority first: child, then parent
        assert len(result) == 2
        assert result[0] == child / ".spex.toml"
        assert result[1] == tmp_path / ".spex.toml"

    def test_home_fallback(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("config.Path.home", lambda: home)
        (home / ".spex.toml").write_text(
            'create_branch = true\n', encoding="utf-8"
        )
        # worktree_root is somewhere else with no .spex.toml
        worktree = tmp_path / "repo"
        worktree.mkdir()

        result = _find_spex_tomls(worktree)

        assert len(result) == 1
        assert result[0] == home / ".spex.toml"

    def test_no_files_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        worktree = tmp_path / "empty_repo"
        worktree.mkdir()

        result = _find_spex_tomls(worktree)

        assert result == []

    def test_home_not_duplicated_when_in_walk(self, tmp_path, monkeypatch):
        """If ~/.spex.toml is found during upward walk, don't append again."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("config.Path.home", lambda: home)
        (home / ".spex.toml").write_text('x = 1\n', encoding="utf-8")
        # worktree_root is under home, so walk passes through home
        worktree = home / "projects" / "repo"
        worktree.mkdir(parents=True)

        result = _find_spex_tomls(worktree)

        # Should only appear once
        resolved_paths = [p.resolve() for p in result]
        assert resolved_paths.count((home / ".spex.toml").resolve()) == 1

    def test_none_worktree_root_walks_from_workdir(self, tmp_path, monkeypatch):
        """When worktree_root is None, walk upward from workdir."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("config.Path.home", lambda: home)
        # Place .spex.toml in a parent of workdir
        parent = tmp_path / "projects"
        parent.mkdir()
        (parent / ".spex.toml").write_text('x = 1\n', encoding="utf-8")
        workdir = parent / "myapp"
        workdir.mkdir()

        result = _find_spex_tomls(None, workdir)

        assert any(p.resolve() == (parent / ".spex.toml").resolve() for p in result)

    def test_none_worktree_root_falls_back_to_cwd(self, tmp_path, monkeypatch):
        """When worktree_root and workdir are both None, walk from cwd."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("config.Path.home", lambda: home)
        (home / ".spex.toml").write_text('x = 1\n', encoding="utf-8")
        monkeypatch.chdir(home)

        result = _find_spex_tomls(None)

        assert len(result) == 1
        assert result[0].resolve() == (home / ".spex.toml").resolve()


# ===================== _merge_configs =====================


class TestMergeConfigs:
    def test_higher_priority_overrides(self, tmp_path):
        low = tmp_path / "low.toml"
        high = tmp_path / "high.toml"
        low.write_text('spex_root = "/low"\nextra = true\n', encoding="utf-8")
        high.write_text('spex_root = "/high"\n', encoding="utf-8")

        # highest priority first in list
        result = _merge_configs([high, low])

        assert result["spex_root"] == "/high"
        assert result["extra"] is True

    def test_empty_list(self):
        result = _merge_configs([])
        assert result == {}


# ===================== load_config =====================


class TestLoadConfig:
    def test_env_var_overrides_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_worktree_root", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/from/file"\n', encoding="utf-8"
        )
        monkeypatch.setenv("SPEX_ROOT", "/from/env")

        result = load_config()

        assert result["spex_root"] == "/from/env"

    def test_caching(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_worktree_root", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/original"\n', encoding="utf-8"
        )

        first = load_config()
        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/changed"\n', encoding="utf-8"
        )
        second = load_config()

        assert first["spex_root"] == "/original"
        assert second["spex_root"] == "/original"  # cached

    def test_cache_clear_then_reload(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_worktree_root", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/v1"\n', encoding="utf-8"
        )

        first = load_config()
        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/v2"\n', encoding="utf-8"
        )
        clear_config_cache()
        second = load_config()

        assert first["spex_root"] == "/v1"
        assert second["spex_root"] == "/v2"


# ===================== Worktree root caching =====================


class TestWorktreeRootCaching:
    def test_second_call_uses_cache(self, monkeypatch):
        call_count = {"n": 0}
        original_run = __import__("subprocess").run

        def mock_run(cmd, **kwargs):
            if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
                call_count["n"] += 1
            return original_run(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", mock_run)

        _get_worktree_root()
        _get_worktree_root()

        assert call_count["n"] == 1


# ===================== Branch config keys =====================


class TestBranchConfig:
    def test_load_branch_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr("config._get_worktree_root", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            'create_branch = true\nmain_branch_name = "main"\nsubmit_method = "pr"\n',
            encoding="utf-8",
        )

        result = load_config()

        assert result["create_branch"] is True
        assert result["main_branch_name"] == "main"
        assert result["submit_method"] == "pr"

    def test_default_branch_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr("config._get_worktree_root", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            'spex_root = ".spex"\n', encoding="utf-8"
        )

        result = load_config()

        assert result["create_branch"] is False
        assert result["main_branch_name"] == ""
        assert result["submit_method"] == "merge"
