"""Tests for config.py: hierarchical TOML discovery, merging, and caching."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from config import (
    ProjectContext,
    _deep_merge,
    _find_spex_tomls,
    _get_main_worktree,
    _get_top_workdir,
    _load_toml_config,
    _merge_configs,
    _resolve_spex_roots,
    clear_config_cache,
    generate_default_toml,
    generate_updated_toml,
    get_effective_user_config,
    get_project_context,
    load_config,
    resolve_spex_root_and_roots,
    set_spex_config_file,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_config_cache()
    yield
    clear_config_cache()


# ===================== _load_toml_config =====================


class TestLoadTomlConfig:
    def test_valid_toml(self, tmp_path):
        p = tmp_path / "sample.toml"
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
        (tmp_path / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

        result = _find_spex_tomls(tmp_path)

        assert len(result) == 1
        assert result[0] == tmp_path / ".spex.toml"

    def test_hierarchy_worktree_and_parent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        # Parent has .spex.toml
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nsubmit_method = "pr"\n', encoding="utf-8"
        )
        # Worktree root (child) also has .spex.toml
        child = tmp_path / "projects" / "myrepo"
        child.mkdir(parents=True)
        (child / ".spex.toml").write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

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
            '[spex]\nbranch_management = true\n', encoding="utf-8"
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
        low.write_text('[spex]\nspex_root = "/low"\nextra = true\n', encoding="utf-8")
        high.write_text('[spex]\nspex_root = "/high"\n', encoding="utf-8")

        # highest priority first in list
        result = _merge_configs([high, low])

        assert result["spex_root"] == "/high"
        assert result["extra"] is True

    def test_empty_list(self):
        result = _merge_configs([])
        assert result == {}


# ===================== load_config =====================


class TestLoadConfig:
    def test_caching(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_main_worktree", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = "/original"\n', encoding="utf-8"
        )

        first = load_config()
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = "/changed"\n', encoding="utf-8"
        )
        second = load_config()

        assert first["spex_root"] == "/original"
        assert second["spex_root"] == "/original"  # cached

    def test_cache_clear_then_reload(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path)
        monkeypatch.setattr("config._get_main_worktree", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = "/v1"\n', encoding="utf-8"
        )

        first = load_config()
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = "/v2"\n', encoding="utf-8"
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

        _get_top_workdir()
        _get_top_workdir()

        assert call_count["n"] == 1


# ===================== Branch config keys =====================


class TestBranchConfig:
    def test_load_branch_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr("config._get_main_worktree", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nbranch_management = true\nmain_branch_name = "main"\nsubmit_method = "pr"\n',
            encoding="utf-8",
        )

        result = load_config()

        assert result["branch_management"] is True
        assert result["main_branch_name"] == "main"
        assert result["submit_method"] == "pr"

    def test_default_branch_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr("config._get_main_worktree", lambda w=None: tmp_path)
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )

        result = load_config()

        assert result["branch_management"] is True
        assert result["main_branch_name"] == ""
        assert result["submit_method"] == "merge"


# ===================== _resolve_spex_roots =====================


class TestResolveSpexRoots:
    def test_same_level_added_unconditionally(self, tmp_path, monkeypatch):
        """Directory with .spex.toml setting spex_root is added even without dir."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        toml = worktree / ".spex.toml"
        toml.write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")
        # .spex/ does NOT exist

        result = _resolve_spex_roots([toml], worktree)

        assert result[0] == str((worktree / ".spex").resolve())

    def test_non_same_level_requires_existence(self, tmp_path, monkeypatch):
        """Child governed by parent's .spex.toml — only added if dir exists."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        parent = tmp_path / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        toml = parent / ".spex.toml"
        toml.write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")
        # child/.spex does NOT exist, parent/.spex exists
        (parent / ".spex").mkdir()

        result = _resolve_spex_roots([toml], child)

        # child/.spex missing (not same-level) → skipped
        # parent/.spex exists AND is same-level → first
        assert result[0] == str((parent / ".spex").resolve())

    def test_per_level_different_spex_root(self, tmp_path, monkeypatch):
        """Different .spex.toml files set different spex_root values."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        grandparent = tmp_path / "gp"
        parent = grandparent / "parent"
        child = parent / "child"
        child.mkdir(parents=True)

        # Parent sets .spex, grandparent sets .specs
        parent_toml = parent / ".spex.toml"
        parent_toml.write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")
        gp_toml = grandparent / ".spex.toml"
        gp_toml.write_text('[spex]\nspex_root = ".specs"\n', encoding="utf-8")

        # child/.spex exists (governed by parent's config)
        (child / ".spex").mkdir()
        # grandparent/.specs added unconditionally (same-level)

        result = _resolve_spex_roots([parent_toml, gp_toml], child)

        assert result[0] == str((child / ".spex").resolve())
        assert result[1] == str((parent / ".spex").resolve())
        assert result[2] == str((grandparent / ".specs").resolve())

    def test_toml_without_spex_root_is_transparent(self, tmp_path, monkeypatch):
        """A .spex.toml without spex_root key doesn't affect resolution."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        parent = tmp_path / "parent"
        child = parent / "child"
        child.mkdir(parents=True)

        # Child has .spex.toml but without spex_root
        child_toml = child / ".spex.toml"
        child_toml.write_text('[spex]\nbranch_management = true\n', encoding="utf-8")
        # Parent has .spex.toml with spex_root
        parent_toml = parent / ".spex.toml"
        parent_toml.write_text('[spex]\nspex_root = ".my-spex"\n', encoding="utf-8")

        # child/.my-spex exists (governed by parent's config, since child's toml is transparent)
        (child / ".my-spex").mkdir()

        result = _resolve_spex_roots([child_toml, parent_toml], child)

        assert result[0] == str((child / ".my-spex").resolve())
        assert result[1] == str((parent / ".my-spex").resolve())

    def test_absolute_path_in_toml(self, tmp_path, monkeypatch):
        """Absolute spex_root is added unconditionally at same level."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        abs_path = tmp_path / "absolute-spex"
        toml = worktree / ".spex.toml"
        toml.write_text(f'[spex]\nspex_root = "{abs_path}"\n', encoding="utf-8")

        result = _resolve_spex_roots([toml], worktree)

        assert result[0] == str(abs_path.resolve())
        home_default = str((tmp_path / "fakehome" / ".spex").resolve())
        assert home_default in result

    def test_tilde_path_in_toml(self, monkeypatch, tmp_path):
        """~/path is expanded and treated as absolute."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr("config.Path.home", lambda: home)
        worktree = tmp_path / "repo"
        worktree.mkdir()
        toml = worktree / ".spex.toml"
        toml.write_text('[spex]\nspex_root = "~/my-specs"\n', encoding="utf-8")

        result = _resolve_spex_roots([toml], worktree)

        assert result[0] == str(home / "my-specs")
        home_default = str((home / ".spex").resolve())
        assert home_default in result

    def test_no_tomls_uses_default(self, tmp_path, monkeypatch):
        """No .spex.toml anywhere — default .spex, only if dir exists."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        worktree = tmp_path / "repo"
        worktree.mkdir()
        (worktree / ".spex").mkdir()

        result = _resolve_spex_roots([], worktree)

        assert result[0] == str((worktree / ".spex").resolve())
        home_default = str((tmp_path / "fakehome" / ".spex").resolve())
        assert home_default in result

    def test_no_tomls_no_dirs_has_home_default(self, tmp_path, monkeypatch):
        """No .spex.toml, no .spex/ dirs — only home default in result."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        worktree = tmp_path / "repo"
        worktree.mkdir()

        result = _resolve_spex_roots([], worktree)

        home_default = str((tmp_path / "fakehome" / ".spex").resolve())
        assert result == [home_default]

    def test_none_worktree_walks_from_workdir(self, tmp_path, monkeypatch):
        """When worktree_root is None, walk from workdir."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        parent = tmp_path / "projects"
        parent.mkdir()
        (parent / ".spex").mkdir()
        toml = parent / ".spex.toml"
        toml.write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")
        workdir = parent / "myapp"
        workdir.mkdir()

        result = _resolve_spex_roots([toml], None, workdir)

        assert result[0] == str((parent / ".spex").resolve())

    def test_home_fallback_off_path(self, tmp_path, monkeypatch):
        """Home .spex.toml used when home is not on the upward path."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("config.Path.home", lambda: home)
        home_toml = home / ".spex.toml"
        home_toml.write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")

        # worktree is NOT under home
        worktree = tmp_path / "other" / "repo"
        worktree.mkdir(parents=True)

        result = _resolve_spex_roots([home_toml], worktree)

        # Home toml is off-path, added unconditionally
        assert result == [str((home / ".spex").resolve())]


# ===================== resolve_spex_root_and_roots =====================


class TestResolveSpexRootAndRoots:
    def test_basic(self, tmp_path, monkeypatch):
        """With .spex/ and .spex.toml, returns correct tuple."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr(
            "config._get_main_worktree", lambda w=None: tmp_path
        )
        (tmp_path / ".spex").mkdir()
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )

        primary, roots = resolve_spex_root_and_roots()

        expected = str((tmp_path / ".spex").resolve())
        home_default = str((tmp_path / "fakehome" / ".spex").resolve())
        assert primary == expected
        assert roots[0] == expected
        assert home_default in roots

    def test_same_level_no_dir(self, tmp_path, monkeypatch):
        """Same-level rule: primary returned even if dir doesn't exist."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr(
            "config._get_main_worktree", lambda w=None: tmp_path
        )
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = ".my-spex"\n', encoding="utf-8"
        )

        primary, roots = resolve_spex_root_and_roots()

        expected = str((tmp_path / ".my-spex").resolve())
        home_default = str((tmp_path / "fakehome" / ".spex").resolve())
        assert primary == expected
        assert roots[0] == expected
        assert home_default in roots

    def test_home_default_always_in_roots(self, tmp_path, monkeypatch):
        """~/.<default> is always in roots even without any .spex.toml."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr(
            "config._get_main_worktree", lambda w=None: tmp_path
        )

        primary, roots = resolve_spex_root_and_roots()

        home_default = str((tmp_path / "fakehome" / ".spex").resolve())
        assert primary == home_default
        assert roots == [home_default]

    def test_home_default_not_duplicated(self, tmp_path, monkeypatch):
        """If ~/.spex already in roots, it's not added again."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("config.Path.home", lambda: home)
        monkeypatch.setattr(
            "config._get_main_worktree", lambda w=None: home
        )
        (home / ".spex").mkdir()
        (home / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )

        primary, roots = resolve_spex_root_and_roots()

        home_spex = str((home / ".spex").resolve())
        assert primary == home_spex
        assert roots.count(home_spex) == 1


# ===================== SPEX_CONFIG_FILE override =====================


class TestSpexConfigFileOverride:
    def test_env_var_overrides_discovery(self, tmp_path, monkeypatch):
        """SPEX_CONFIG_FILE env var bypasses normal .spex.toml discovery."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        # Normal .spex.toml that should be ignored
        worktree = tmp_path / "repo"
        worktree.mkdir()
        (worktree / ".spex.toml").write_text(
            '[spex]\nspex_root = "/ignored"\n', encoding="utf-8"
        )
        # Explicit config file
        custom = tmp_path / "custom.toml"
        custom.write_text('[spex]\nspex_root = "/custom"\n', encoding="utf-8")
        monkeypatch.setenv("SPEX_CONFIG_FILE", str(custom))

        result = _find_spex_tomls(worktree)

        assert result == [custom.resolve()]

    def test_cli_override_takes_priority_over_env(self, tmp_path, monkeypatch):
        """set_spex_config_file (CLI) takes priority over SPEX_CONFIG_FILE env."""
        cli_file = tmp_path / "cli.toml"
        cli_file.write_text('[spex]\nspex_root = "/from-cli"\n', encoding="utf-8")
        env_file = tmp_path / "env.toml"
        env_file.write_text('[spex]\nspex_root = "/from-env"\n', encoding="utf-8")

        monkeypatch.setenv("SPEX_CONFIG_FILE", str(env_file))
        set_spex_config_file(str(cli_file))

        result = _find_spex_tomls(None)

        assert result == [cli_file.resolve()]

    def test_nonexistent_file_raises(self, tmp_path, monkeypatch):
        """Pointing at a missing file raises FileNotFoundError."""
        missing = tmp_path / "does-not-exist.toml"
        monkeypatch.setenv("SPEX_CONFIG_FILE", str(missing))

        with pytest.raises(FileNotFoundError, match="does not exist"):
            _find_spex_tomls(None)

    def test_nonexistent_cli_override_raises(self, tmp_path):
        """CLI override pointing at a missing file raises FileNotFoundError."""
        missing = tmp_path / "missing.toml"
        set_spex_config_file(str(missing))

        with pytest.raises(FileNotFoundError, match="does not exist"):
            _find_spex_tomls(None)

    def test_spex_root_from_config_file(self, tmp_path, monkeypatch):
        """Config file overrides spex_root in get_project_context."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr(
            "config._get_top_workdir", lambda w=None: tmp_path
        )
        monkeypatch.setattr(
            "config._get_main_worktree", lambda w=None: tmp_path
        )
        # Normal .spex.toml in worktree (should be ignored)
        (tmp_path / ".spex.toml").write_text(
            '[spex]\nspex_root = "/normal"\n', encoding="utf-8"
        )
        # Custom config file with different spex_root
        custom = tmp_path / "override.toml"
        custom.write_text('[spex]\nspex_root = "/custom-root"\n', encoding="utf-8")
        set_spex_config_file(str(custom))

        ctx = get_project_context(str(tmp_path))

        assert ctx.spex_root == "/custom-root"
        assert ctx.spex_tomls == [custom.resolve()]

    def test_clear_cache_resets_override(self, tmp_path):
        """clear_config_cache resets the CLI override."""
        config_file = tmp_path / "test.toml"
        config_file.write_text('[spex]\nspex_root = "/x"\n', encoding="utf-8")
        set_spex_config_file(str(config_file))

        clear_config_cache()

        # After clearing, should fall back to normal discovery (no override)
        # Without any .spex.toml in tree, returns empty
        import config

        monkeypatch_home = tmp_path / "fakehome"
        original_home = config.Path.home
        config.Path.home = lambda: monkeypatch_home
        try:
            result = _find_spex_tomls(tmp_path)
            assert result == []
        finally:
            config.Path.home = original_home


# ===================== _get_main_worktree =====================


@pytest.mark.slow
class TestGetMainWorktree:
    """Tests for _get_main_worktree with real git repos."""

    def test_normal_repo(self, tmp_path):
        """Normal repo (.git is a directory) returns top_workdir."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init", str(repo)], capture_output=True, check=True
        )
        clear_config_cache()

        result = _get_main_worktree(str(repo))

        assert result == repo.resolve()

    def test_not_in_git_repo(self, tmp_path):
        """Returns None when not inside a git repo."""
        clear_config_cache()

        result = _get_main_worktree(str(tmp_path))

        assert result is None

    def test_linked_worktree(self, tmp_path):
        """Linked worktree (.git is a file) resolves to main worktree."""
        main = tmp_path / "main"
        main.mkdir()
        subprocess.run(
            ["git", "init", str(main)], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", str(main), "commit",
             "--allow-empty", "-m", "init"],
            capture_output=True, check=True,
        )
        linked = tmp_path / "linked"
        subprocess.run(
            ["git", "-C", str(main), "worktree", "add",
             str(linked), "-b", "feature"],
            capture_output=True, check=True,
        )
        clear_config_cache()

        result = _get_main_worktree(str(linked))

        assert result == main.resolve()

    def test_submodule(self, tmp_path):
        """Submodule (.git is a file) resolves to parent project main worktree."""
        parent = tmp_path / "parent"
        parent.mkdir()
        subprocess.run(
            ["git", "init", str(parent)], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", str(parent), "commit",
             "--allow-empty", "-m", "init"],
            capture_output=True, check=True,
        )

        child_origin = tmp_path / "child_origin"
        child_origin.mkdir()
        subprocess.run(
            ["git", "init", str(child_origin)],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(child_origin), "commit",
             "--allow-empty", "-m", "init"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(parent),
             "-c", "protocol.file.allow=always",
             "submodule", "add", str(child_origin), "child"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(parent), "commit", "-m", "add submodule"],
            capture_output=True, check=True,
        )

        sub_workdir = parent / "child"
        clear_config_cache()

        result = _get_main_worktree(str(sub_workdir))

        assert result == parent.resolve()

    def test_caching(self, tmp_path):
        """Second call returns cached result without running git again."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init", str(repo)], capture_output=True, check=True
        )
        clear_config_cache()

        first = _get_main_worktree(str(repo))
        second = _get_main_worktree(str(repo))

        assert first == second
        assert first == repo.resolve()


# ===================== generate_default_toml =====================


class TestGenerateDefaultToml:
    def test_header_is_first_line(self):
        result = generate_default_toml()
        first_line = result.splitlines()[0]
        assert first_line == "[spex]"

    def test_all_default_keys_present(self):
        result = generate_default_toml()
        for key in ("spex_root", "branch_management", "main_branch_name", "submit_method"):
            assert f"# {key} = " in result

    def test_boolean_formatting(self):
        result = generate_default_toml()
        assert "# branch_management = true" in result
        assert "True" not in result

    def test_string_formatting(self):
        result = generate_default_toml()
        assert '# spex_root = ".spex"' in result
        assert '# main_branch_name = ""' in result
        assert '# submit_method = "merge"' in result

    def test_comments_present(self):
        result = generate_default_toml()
        assert "# Root directory for spec storage" in result
        assert "# Create and manage branches for specs" in result

    def test_blank_line_separators(self):
        lines = generate_default_toml().splitlines()
        assert lines[0] == "[spex]"
        assert lines[1] == "# Root directory for spec storage"
        assert lines[2] == '# spex_root = ".spex"'
        assert lines[3] == ""
        assert lines[4] == "# Create and manage branches for specs"


# ===================== generate_updated_toml =====================


class TestGenerateUpdatedToml:
    def test_empty_config_equals_default(self):
        assert generate_updated_toml({}) == generate_default_toml()

    def test_user_key_uncommented(self):
        result = generate_updated_toml({"spex_root": "custom"})
        assert 'spex_root = "custom"' in result
        assert '# spex_root = ' not in result

    def test_other_keys_stay_commented(self):
        result = generate_updated_toml({"spex_root": "custom"})
        assert "# branch_management = true" in result
        assert '# submit_method = "merge"' in result

    def test_boolean_user_value_different_from_default(self):
        result = generate_updated_toml({"branch_management": False})
        assert "branch_management = false" in result
        assert "# branch_management" not in result

    def test_value_matching_default_is_commented(self):
        result = generate_updated_toml({"branch_management": True})
        assert "# branch_management = true" in result

        result = generate_updated_toml({"spex_root": ".spex"})
        assert '# spex_root = ".spex"' in result

    def test_unknown_key_ignored(self):
        result = generate_updated_toml({"unknown_key": "val"})
        assert "unknown_key" not in result
        assert result == generate_default_toml()

    def test_all_keys_set_non_default(self):
        cfg = {
            "spex_root": "/my/root",
            "branch_management": False,
            "main_branch_name": "develop",
            "submit_method": "pr",
        }
        result = generate_updated_toml(cfg)
        assert 'spex_root = "/my/root"' in result
        assert "branch_management = false" in result
        assert 'main_branch_name = "develop"' in result
        assert 'submit_method = "pr"' in result

    def test_comments_always_present(self):
        result = generate_updated_toml({"spex_root": "x"})
        assert "# Root directory for spec storage" in result
        assert "# Create and manage branches for specs" in result


# ===================== get_effective_user_config =====================


class TestGetEffectiveUserConfig:
    def test_returns_user_set_values(self, tmp_path):
        """Returns only explicitly set values, not defaults."""
        toml_file = tmp_path / ".spex.toml"
        toml_file.write_text('[spex]\nbranch_management = true\n')

        with patch("config.Path.home", return_value=tmp_path / "no_home"):
            clear_config_cache()
            result = get_effective_user_config(str(tmp_path))

        assert result == {"branch_management": True}

    def test_returns_empty_when_no_tomls(self, tmp_path):
        """Returns empty dict when no config files exist."""
        target = tmp_path / "empty"
        target.mkdir()

        with patch("config.Path.home", return_value=tmp_path / "no_home"):
            clear_config_cache()
            result = get_effective_user_config(str(target))

        assert result == {}

    def test_merges_multiple_tomls(self, tmp_path):
        """Merges values from project and home-level tomls."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".spex.toml").write_text('[spex]\nspex_root = "proj"\n')
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".spex.toml").write_text(
            '[spex]\nbranch_management = true\n'
        )

        with patch("config.Path.home", return_value=fake_home):
            clear_config_cache()
            result = get_effective_user_config(str(project))

        assert result["spex_root"] == "proj"
        assert result["branch_management"] is True


# ===================== ProjectContext =====================


class TestProjectContext:
    def test_default_field_values(self):
        """Fields with factory defaults are initialized correctly."""
        ctx = ProjectContext(
            cwd=Path("/tmp"),
            top_workdir=None,
            main_worktree=None,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
        )
        assert ctx.spex_tomls == []
        assert ctx.config == {}
        assert ctx.spex_root == ""
        assert ctx.spex_roots == []

    def test_all_fields_accessible(self):
        """All fields are stored and accessible as attributes."""
        cwd = Path("/work")
        top = Path("/work")
        ctx = ProjectContext(
            cwd=cwd,
            top_workdir=top,
            main_worktree=top,
            remote_url="https://github.com/test/repo.git",
            branch="main",
            user_name="Test User",
            user_email="test@example.com",
            spex_tomls=[Path("/work/.spex.toml")],
            config={"spex_root": ".spex"},
            spex_root="/work/.spex",
            spex_roots=["/work/.spex"],
        )
        assert ctx.cwd == cwd
        assert ctx.top_workdir == top
        assert ctx.main_worktree == top
        assert ctx.remote_url == "https://github.com/test/repo.git"
        assert ctx.branch == "main"
        assert ctx.user_name == "Test User"
        assert ctx.user_email == "test@example.com"
        assert len(ctx.spex_tomls) == 1
        assert ctx.config["spex_root"] == ".spex"
        assert ctx.spex_root == "/work/.spex"
        assert ctx.spex_roots == ["/work/.spex"]


# ===================== in_git_workdir =====================


class TestInGitWorkDir:
    def test_returns_true_when_top_workdir_is_path(self):
        ctx = ProjectContext(
            cwd=Path("/work"),
            top_workdir=Path("/work"),
            main_worktree=None,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
        )
        assert ctx.in_git_workdir() is True

    def test_returns_false_when_top_workdir_is_none(self):
        ctx = ProjectContext(
            cwd=Path("/tmp"),
            top_workdir=None,
            main_worktree=None,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
        )
        assert ctx.in_git_workdir() is False


# ===================== get_project_context =====================


class TestGetProjectContext:
    @pytest.mark.slow
    def test_git_repo_populates_all_fields(self, tmp_path):
        """In a git repo, all fields are populated from git metadata."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init", str(repo)], capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test User"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin",
             "https://github.com/test/repo.git"],
            capture_output=True, check=True,
        )

        ctx = get_project_context(str(repo))

        assert ctx.cwd == repo.resolve()
        assert ctx.top_workdir == repo.resolve()
        assert ctx.main_worktree == repo.resolve()
        assert ctx.remote_url == "https://github.com/test/repo.git"
        assert ctx.branch in ("main", "master")
        assert ctx.user_name == "Test User"
        assert ctx.user_email == "test@example.com"

    @pytest.mark.slow
    def test_non_git_repo_returns_none_and_empty(self, tmp_path, monkeypatch):
        """Outside a git repo, top_workdir is None and string fields are empty."""
        no_git = tmp_path / "not-a-repo"
        no_git.mkdir()
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")

        ctx = get_project_context(str(no_git))

        assert ctx.cwd == no_git.resolve()
        assert ctx.top_workdir is None
        assert ctx.main_worktree is None
        assert ctx.remote_url == ""
        assert ctx.branch == ""
        # user_name/user_email may be non-empty from global git config

    def test_caching_returns_same_object(self, tmp_path, monkeypatch):
        """Two calls with same workdir return the identical cached object."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr("config._get_top_workdir", lambda w=None: None)
        monkeypatch.setattr("config._get_main_worktree", lambda w=None: None)

        first = get_project_context(str(tmp_path))
        second = get_project_context(str(tmp_path))

        assert first is second

    def test_cache_cleared_by_clear_config_cache(self, tmp_path, monkeypatch):
        """clear_config_cache() invalidates the project context cache."""
        monkeypatch.setattr("config.Path.home", lambda: tmp_path / "fakehome")
        monkeypatch.setattr("config._get_top_workdir", lambda w=None: None)
        monkeypatch.setattr("config._get_main_worktree", lambda w=None: None)

        first = get_project_context(str(tmp_path))
        clear_config_cache()
        second = get_project_context(str(tmp_path))

        assert first is not second


# ===================== is_related_to =====================


class TestIsRelatedTo:
    """Tests for ProjectContext.is_related_to() method."""

    def _make_ctx(self, top_workdir=None, main_worktree=None):
        return ProjectContext(
            cwd=Path("/tmp"),
            top_workdir=top_workdir,
            main_worktree=main_worktree,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
        )

    def test_top_workdir_matches(self, tmp_path):
        """top_workdir matches spec's workdir -> True."""
        ctx = self._make_ctx(top_workdir=tmp_path, main_worktree=tmp_path)
        topic_dict = {"workdir": str(tmp_path), "main_worktree": ""}
        assert ctx.is_related_to(topic_dict) is True

    def test_main_worktree_matches(self, tmp_path):
        """main_worktree matches spec's main_worktree -> True."""
        other = tmp_path / "other"
        other.mkdir()
        ctx = self._make_ctx(top_workdir=other, main_worktree=tmp_path)
        topic_dict = {"workdir": "/nonexistent/path", "main_worktree": str(tmp_path)}
        assert ctx.is_related_to(topic_dict) is True

    def test_neither_matches(self, tmp_path):
        """Neither top_workdir nor main_worktree matches -> False."""
        ctx = self._make_ctx(
            top_workdir=tmp_path / "a", main_worktree=tmp_path / "b"
        )
        topic_dict = {
            "workdir": str(tmp_path / "x"),
            "main_worktree": str(tmp_path / "y"),
        }
        assert ctx.is_related_to(topic_dict) is False

    def test_not_in_git_repo(self):
        """Both top_workdir and main_worktree are None -> True."""
        ctx = self._make_ctx(top_workdir=None, main_worktree=None)
        topic_dict = {"workdir": "/some/path", "main_worktree": "/other"}
        assert ctx.is_related_to(topic_dict) is True

    def test_topic_workdir_empty(self, tmp_path):
        """Spec's workdir is empty string -> True."""
        ctx = self._make_ctx(top_workdir=tmp_path, main_worktree=tmp_path)
        topic_dict = {"workdir": "", "main_worktree": ""}
        assert ctx.is_related_to(topic_dict) is True

    def test_accepts_dict(self, tmp_path):
        """Accepts a dict (like load_meta().to_dict() result)."""
        ctx = self._make_ctx(top_workdir=tmp_path, main_worktree=tmp_path)
        topic_dict = {"workdir": str(tmp_path), "main_worktree": str(tmp_path)}
        assert ctx.is_related_to(topic_dict) is True

    def test_accepts_object_with_attributes(self, tmp_path):
        """Accepts object with .workdir/.main_worktree attributes."""
        ctx = self._make_ctx(top_workdir=tmp_path, main_worktree=tmp_path)

        class FakeMeta:
            workdir = str(tmp_path)
            main_worktree = str(tmp_path)

        assert ctx.is_related_to(FakeMeta()) is True

    def test_accepts_topic_with_meta_attribute(self, tmp_path):
        """Accepts Spec-like object with .meta attribute."""
        ctx = self._make_ctx(top_workdir=tmp_path, main_worktree=tmp_path)

        class FakeMeta:
            workdir = str(tmp_path)
            main_worktree = str(tmp_path)

        class FakeSpec:
            meta = FakeMeta()

        assert ctx.is_related_to(FakeSpec()) is True

    def test_accepts_path(self, tmp_path):
        """Accepts Path as parameter (reads meta.json from directory)."""
        import json

        ctx = self._make_ctx(top_workdir=tmp_path, main_worktree=tmp_path)
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()
        meta = {"workdir": str(tmp_path), "main_worktree": str(tmp_path)}
        (spec_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        assert ctx.is_related_to(spec_dir) is True

    def test_path_with_no_meta_json(self, tmp_path):
        """Path with no meta.json returns True (no filtering possible)."""
        ctx = self._make_ctx(top_workdir=tmp_path, main_worktree=tmp_path)
        spec_dir = tmp_path / "empty-topic"
        spec_dir.mkdir()

        assert ctx.is_related_to(spec_dir) is True

