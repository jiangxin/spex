"""Tests for config.py: TOML loading, merging, and caching."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from config import (
    _deep_merge,
    _find_spex_toml,
    _load_toml_config,
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

    def test_base_extra_key_preserved(self):
        base = {"spex_root": "/base", "extra": True}
        override = {"spex_root": "/new"}

        result = _deep_merge(base, override)

        assert result["extra"] is True

    def test_override_extra_key_preserved(self):
        base = {"spex_root": "/base"}
        override = {"new_key": "value"}

        result = _deep_merge(base, override)

        assert result["new_key"] == "value"

    def test_empty_override_no_change(self):
        base = {"spex_root": "/base", "x": 1}
        result = _deep_merge(base, {})
        assert result == base

    def test_nested_merge(self):
        base = {"nested": {"a": 1, "b": 2}}
        override = {"nested": {"b": 99, "c": 3}}

        result = _deep_merge(base, override)

        assert result["nested"]["a"] == 1
        assert result["nested"]["b"] == 99
        assert result["nested"]["c"] == 3


# ===================== _find_spex_toml =====================


class TestFindSpexToml:
    def test_no_configs_empty(self, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: Path("/nonexistent"))
        result = _find_spex_toml(None)
        assert result == {}

    def test_home_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/home/spex"\n', encoding="utf-8"
        )

        result = _find_spex_toml(None)
        assert result["spex_root"] == "/home/spex"

    def test_repo_overrides_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/home/spex"\n', encoding="utf-8"
        )
        (repo / ".spex.toml").write_text(
            'spex_root = "/repo/spex"\n', encoding="utf-8"
        )

        result = _find_spex_toml(repo)
        assert result["spex_root"] == "/repo/spex"

    def test_xdg_overrides_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        xdg = tmp_path / ".config" / "spex"
        xdg.mkdir(parents=True)

        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/home/spex"\n', encoding="utf-8"
        )
        (xdg / "config.toml").write_text(
            'spex_root = "/xdg/spex"\n', encoding="utf-8"
        )

        result = _find_spex_toml(None)
        assert result["spex_root"] == "/xdg/spex"

    def test_repo_overrides_xdg_overrides_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()
        xdg = tmp_path / ".config" / "spex"
        xdg.mkdir(parents=True)

        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/home"\n', encoding="utf-8"
        )
        (xdg / "config.toml").write_text(
            'spex_root = "/xdg"\n', encoding="utf-8"
        )
        (repo / ".spex.toml").write_text(
            'spex_root = "/repo"\n', encoding="utf-8"
        )

        result = _find_spex_toml(repo)
        assert result["spex_root"] == "/repo"

    def test_repo_key_preserves_home_extra(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        repo = tmp_path / "repo"
        repo.mkdir()

        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/home"\nextra = true\n', encoding="utf-8"
        )
        (repo / ".spex.toml").write_text(
            'spex_root = "/repo"\n', encoding="utf-8"
        )

        result = _find_spex_toml(repo)
        assert result["extra"] is True


# ===================== load_config =====================


class TestLoadConfig:
    def test_env_var_overrides_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_repo_root", lambda w=None: None)
        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/from/file"\n', encoding="utf-8"
        )
        monkeypatch.setenv("SPEX_ROOT", "/from/env")

        result = load_config()

        assert result["spex_root"] == "/from/env"

    def test_caching(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_repo_root", lambda w=None: None)
        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/original"\n', encoding="utf-8"
        )

        first = load_config()
        # Change file after first load
        (tmp_path / ".spex.toml").write_text(
            'spex_root = "/changed"\n', encoding="utf-8"
        )
        second = load_config()

        assert first["spex_root"] == "/original"
        assert second["spex_root"] == "/original"  # cached

    def test_cache_clear_then_reload(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_repo_root", lambda w=None: None)
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


# ===================== Branch config keys =====================


class TestBranchConfig:
    def test_load_branch_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_repo_root", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            'create_branch = true\nmain_branch_name = "main"\nsubmit_method = "pr"\n',
            encoding="utf-8",
        )

        result = load_config()

        assert result["create_branch"] is True
        assert result["main_branch_name"] == "main"
        assert result["submit_method"] == "pr"

    def test_default_branch_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_repo_root", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            'spex_root = ".spex"\n', encoding="utf-8"
        )

        result = load_config()

        assert "create_branch" not in result
        assert "main_branch_name" not in result
        assert "submit_method" not in result
