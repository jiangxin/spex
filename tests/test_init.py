import json
import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from common import (
    EXAMPLES_TEMPLATE_DIR,
    TEMPLATE_DIR,
    _sync_builtin_template,
    clear_spex_root_cache,
)
from config import ProjectContext, generate_default_toml


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_spex_root_cache()
    yield
    clear_spex_root_cache()


@pytest.fixture()
def mock_workdir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    return repo


def _make_context(
    spex_root="",
    spex_roots=None,
    spex_tomls=None,
    config=None,
    top_workdir=None,
    main_worktree=None,
):
    """Helper to build a ProjectContext for mocking."""
    return ProjectContext(
        cwd=Path.cwd(),
        top_workdir=top_workdir,
        main_worktree=main_worktree,
        remote_url="",
        branch="",
        user_name="",
        user_email="",
        spex_tomls=spex_tomls or [],
        config=config or {},
        spex_root=spex_root,
        spex_roots=spex_roots or [],
    )


class TestIsInitialized:
    def test_not_initialized_no_tomls(self, tmp_path):
        """Returns False when no .spex.toml config files are found."""
        ctx = _make_context(spex_root="", spex_roots=[], spex_tomls=[])
        with patch("init.get_project_context", return_value=ctx):
            from init import is_initialized

            assert is_initialized() is False

    def test_not_initialized_spex_root_missing(self, tmp_path):
        """Returns False when spex_root does not exist on disk."""
        spex_root = tmp_path / "spex"
        ctx = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )
        with patch("init.get_project_context", return_value=ctx):
            from init import is_initialized

            assert is_initialized() is False

    def test_initialized(self, tmp_path):
        """Returns True when spex_tomls is non-empty and spex_root exists."""
        spex_root = tmp_path / "spex"
        spex_root.mkdir()
        ctx = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )
        with patch("init.get_project_context", return_value=ctx):
            from init import is_initialized

            assert is_initialized() is True


class TestSyncTemplates:
    def test_copies_markdown_files(self, tmp_path):
        from common import _sync_all_templates

        spex_root = tmp_path / "spex"
        spex_root.mkdir()
        _sync_all_templates(spex_root)

        examples_dir = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        assert examples_dir.is_dir()
        assert (examples_dir / "spec-template.md").exists()
        assert (examples_dir / "apply-one-task.md").exists()
        assert (examples_dir / "apply-commit.md").exists()
        assert (examples_dir / "apply-review.md").exists()
        assert (examples_dir / "apply-fix.md").exists()


class TestSyncBuiltinTemplate:
    def test_copies_when_target_missing(self, tmp_path):
        """Target does not exist -> copy."""
        spex_root = tmp_path / "spex"
        spex_root.mkdir()
        _sync_builtin_template("spec-template.md", spex_root=spex_root)

        target = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR / "spec-template.md"
        assert target.exists()

    def test_skips_when_version_matches(self, tmp_path):
        """Target exists with same version -> skip (no copy)."""
        spex_root = tmp_path / "spex"
        examples_dir = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        examples_dir.mkdir(parents=True)

        # Copy the file first, then set its mtime to match source
        base = Path(__file__).resolve().parent.parent
        src = base / "skills" / "spex" / "templates" / "spec-template.md"
        target = examples_dir / "spec-template.md"
        import shutil
        shutil.copy2(src, target)

        _sync_builtin_template("spec-template.md", spex_root=spex_root)

        # Verify target was not overwritten (same stat)
        assert target.stat().st_mtime == src.stat().st_mtime

    def test_overwrites_when_version_differs(self, tmp_path):
        """Target exists with different version -> overwrite."""
        spex_root = tmp_path / "spex"
        examples_dir = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        examples_dir.mkdir(parents=True)

        target = examples_dir / "spec-template.md"
        # Write a target with a different version
        target.write_text("---\nversion: \"0.0.0\"\n---\nold content\n")

        _sync_builtin_template("spec-template.md", spex_root=spex_root)

        # Should be overwritten (version should be >= "0.0.1")
        content = target.read_text()
        assert "0.0.0" not in content

    def test_overwrites_when_mtime_differs(self, tmp_path):
        """Target exists with different mtime -> overwrite regardless of version."""
        spex_root = tmp_path / "spex"
        examples_dir = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        examples_dir.mkdir(parents=True)

        target = examples_dir / "spec-template.md"
        base = Path(__file__).resolve().parent.parent
        src = base / "skills" / "spex" / "templates" / "spec-template.md"

        # Copy with same content but different mtime
        target.write_text(src.read_text())

        _sync_builtin_template("spec-template.md", spex_root=spex_root)

        # Should be overwritten (mtime now matches source)
        assert target.stat().st_mtime == src.stat().st_mtime


class TestEnsureGitignore:
    def test_creates_root_gitignore(self, tmp_path):
        from common import _write_internal_gitignore

        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        _write_internal_gitignore(spex_root)

        gitignore = spex_root / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert "/specs/" in content
        assert "/archives/" in content
        assert "/sessions/" in content

    def test_creates_templates_gitignore(self, tmp_path):
        from common import _write_internal_gitignore

        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        _write_internal_gitignore(spex_root)

        tpl_gitignore = spex_root / "templates" / ".gitignore"
        assert tpl_gitignore.exists()
        assert "/examples/" in tpl_gitignore.read_text()

    def test_preserves_custom_content_when_sessions_present(self, tmp_path):
        from common import _write_internal_gitignore

        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        gitignore = spex_root / ".gitignore"
        gitignore.write_text("custom content\n/sessions/\n")

        _write_internal_gitignore(spex_root)

        assert gitignore.read_text() == "custom content\n/sessions/\n"

    def test_migrates_sessions_into_existing_gitignore(self, tmp_path):
        from common import _write_internal_gitignore

        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        gitignore = spex_root / ".gitignore"
        gitignore.write_text("/specs/\n/archives/\n")

        _write_internal_gitignore(spex_root)

        assert gitignore.read_text() == "/specs/\n/archives/\n/sessions/\n"


class TestEnsureInitialized:
    def test_auto_initializes_empty_dir(self, tmp_path, monkeypatch):
        from common import ensure_initialized

        spex_root = tmp_path / "spex"
        ensure_initialized(str(spex_root))

        assert (spex_root / "specs").is_dir()
        assert (spex_root / "archives").is_dir()
        assert (spex_root / ".gitignore").exists()

    def test_idempotent(self, tmp_path):
        from common import ensure_initialized

        spex_root = tmp_path / "spex"
        ensure_initialized(str(spex_root))
        ensure_initialized(str(spex_root))

        assert (spex_root / "specs").is_dir()

    def test_get_spex_root_auto_initializes(self, tmp_path, monkeypatch):
        spex_root = tmp_path / "empty_spex"
        ctx = _make_context(
            spex_root=str(spex_root), spex_roots=[str(spex_root)]
        )
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)
        clear_spex_root_cache()

        from common import get_spex_root

        result = get_spex_root()
        assert result == str(spex_root)
        assert (spex_root / "specs").is_dir()
        assert (spex_root / "archives").is_dir()


class TestSafeUpdateToml:
    def test_updates_stale_file(self, tmp_path):
        """Rewrites a toml missing new schema keys."""
        toml_file = tmp_path / ".spex.toml"
        toml_file.write_text('[spex]\nspex_root = "custom"\n')

        from config import safe_update_toml

        assert safe_update_toml(toml_file) is True

        content = toml_file.read_text()
        assert 'spex_root = "custom"' in content
        assert "# branch_management = true" in content

    def test_preserves_non_default_user_values(self, tmp_path):
        """User-set keys with non-default values stay uncommented."""
        toml_file = tmp_path / ".spex.toml"
        toml_file.write_text(
            '[spex]\nspex_root = "/my/root"\nbranch_management = false\n'
        )

        from config import safe_update_toml

        safe_update_toml(toml_file)

        content = toml_file.read_text()
        assert 'spex_root = "/my/root"' in content
        assert "branch_management = false" in content
        assert "# spex_root" not in content
        assert "# branch_management" not in content

    def test_default_matching_values_become_comments(self, tmp_path):
        """Values matching defaults are commented out on update."""
        toml_file = tmp_path / ".spex.toml"
        toml_file.write_text(
            '[spex]\nbranch_management = true\n'
        )

        from config import safe_update_toml

        safe_update_toml(toml_file)

        content = toml_file.read_text()
        assert "# branch_management = true" in content

    def test_no_write_when_up_to_date(self, tmp_path):
        """Does not touch file when content already matches schema."""
        toml_file = tmp_path / ".spex.toml"
        toml_file.write_text(generate_default_toml())
        original_mtime = toml_file.stat().st_mtime

        from config import safe_update_toml

        assert safe_update_toml(toml_file) is False
        assert toml_file.stat().st_mtime == original_mtime

    def test_preserves_unknown_keys(self, tmp_path):
        """Unknown keys (e.g. future flags) survive schema upgrade."""
        toml_file = tmp_path / ".spex.toml"
        toml_file.write_text(
            '[spex]\nspex_root = "custom"\ncustom_flag = true\n'
        )

        from config import safe_update_toml

        safe_update_toml(toml_file)
        content = toml_file.read_text()
        assert 'spex_root = "custom"' in content
        assert "custom_flag = true" in content
        assert "# branch_management = true" in content

    def test_preserves_debug_true(self, tmp_path):
        """Explicit debug = true is kept when schema includes debug."""
        toml_file = tmp_path / ".spex.toml"
        toml_file.write_text('[spex]\ndebug = true\n')

        from config import safe_update_toml

        safe_update_toml(toml_file)
        content = toml_file.read_text()
        assert "debug = true" in content
        assert "# debug = false" not in content


class TestCreateTomlConfig:
    def test_creates_home_toml_when_no_config(self, tmp_path):
        """Creates ~/.spex.toml when no config exists."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        ctx = _make_context(spex_tomls=[])
        with (
            patch("init.get_project_context", return_value=ctx),
            patch("init.Path.home", return_value=fake_home),
            patch("common.Path.home", return_value=fake_home),
            patch("init.clear_config_cache"),
        ):
            from init import _create_toml_config

            _create_toml_config()

        toml_file = fake_home / ".spex.toml"
        assert toml_file.exists()
        assert toml_file.read_text() == generate_default_toml()

    def test_upgrades_existing_home_toml_without_wipe(self, tmp_path):
        """Existing ~/.spex.toml is upgraded, not replaced with defaults."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        toml_file = fake_home / ".spex.toml"
        toml_file.write_text(
            '[spex]\nspex_root = "/keep"\ndebug = true\nextra = "x"\n'
        )

        ctx = _make_context(spex_tomls=[])
        with (
            patch("init.get_project_context", return_value=ctx),
            patch("init.Path.home", return_value=fake_home),
            patch("common.Path.home", return_value=fake_home),
            patch("init.clear_config_cache"),
        ):
            from init import _create_toml_config

            _create_toml_config()

        content = toml_file.read_text()
        assert 'spex_root = "/keep"' in content
        assert "debug = true" in content
        assert 'extra = "x"' in content
        assert "# branch_management = true" in content
        assert content != generate_default_toml()

    def test_safe_updates_all_discovered_tomls(self, tmp_path):
        """Updates every toml in spex_tomls, not just ~/.spex.toml."""
        project_toml = tmp_path / "project" / ".spex.toml"
        home_toml = tmp_path / "home" / ".spex.toml"
        project_toml.parent.mkdir()
        home_toml.parent.mkdir()
        project_toml.write_text('[spex]\nspex_root = "proj"\n')
        home_toml.write_text('[spex]\nbranch_management = true\n')

        ctx = _make_context(spex_tomls=[project_toml, home_toml])
        with (
            patch("init.get_project_context", return_value=ctx),
            patch("init.clear_config_cache"),
        ):
            from init import _create_toml_config

            _create_toml_config()

        proj_content = project_toml.read_text()
        assert 'spex_root = "proj"' in proj_content
        assert "# branch_management = true" in proj_content

        home_content = home_toml.read_text()
        assert "# branch_management = true" in home_content
        assert '# spex_root = ".spex"' in home_content

    def test_no_cache_clear_when_all_up_to_date(self, tmp_path):
        """Does not clear cache when no toml was modified."""
        toml_file = tmp_path / ".spex.toml"
        toml_file.write_text(generate_default_toml())

        ctx = _make_context(spex_tomls=[toml_file])
        with (
            patch("init.get_project_context", return_value=ctx),
            patch("init.clear_config_cache") as mock_clear,
        ):
            from init import _create_toml_config

            _create_toml_config()

        mock_clear.assert_not_called()


@pytest.mark.slow
class TestRunInit:
    def test_always_calls_create_toml_config(self, tmp_path):
        """run_init() always calls _create_toml_config."""
        spex_root = tmp_path / ".spex"
        ctx = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config") as mock_create_toml,
            patch("init.get_project_context", return_value=ctx),
            patch("init.ensure_initialized"),
        ):
            from init import run_init

            run_init(workdir=str(tmp_path))

        mock_create_toml.assert_called_once_with(
            workdir=str(tmp_path), verbose=False, dry_run=False,
        )

    def test_syncs_templates_when_already_initialized(self, tmp_path):
        """Syncs templates when spex_root and specs/ already exist."""
        spex_root = tmp_path / ".spex"
        (spex_root / "specs").mkdir(parents=True)

        ctx_with_roots = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
            config={"spex_root": ".spex"},
        )

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
            patch("init.get_project_context", return_value=ctx_with_roots),
            patch("init.ensure_initialized") as mock_ensure,
        ):
            from init import run_init

            run_init(workdir=str(tmp_path))

        mock_ensure.assert_called_once_with(
            str(spex_root), verbose=False, dry_run=False,
        )

    def test_initializes_spex_root_when_missing(self, tmp_path):
        """Calls ensure_initialized when tomls exist but spex_root/specs/ is missing."""
        spex_root = tmp_path / "custom-spex"

        ctx = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
            patch("init.get_project_context", return_value=ctx),
            patch("init.ensure_initialized") as mock_ensure,
        ):
            from init import run_init

            run_init(workdir=str(tmp_path))

        mock_ensure.assert_called_once_with(
            str(spex_root), verbose=False, dry_run=False,
        )

    def test_uses_resolved_spex_root(self, tmp_path):
        """run_init() targets ctx.spex_root, not hardcoded ~/.spex."""
        custom_root = tmp_path / "workspace" / ".my-spex"

        ctx = _make_context(
            spex_root=str(custom_root),
            spex_roots=[str(custom_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
            patch("init.get_project_context", return_value=ctx),
            patch("init.ensure_initialized") as mock_ensure,
        ):
            from init import run_init

            run_init(workdir=str(tmp_path))

        mock_ensure.assert_called_once_with(
            str(custom_root), verbose=False, dry_run=False,
        )

    def test_creates_templates(self, tmp_path, monkeypatch, mock_workdir):
        """Integration: templates are created during init."""
        from init import run_init

        (mock_workdir / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )
        clear_spex_root_cache()

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
        ):
            run_init(workdir=str(mock_workdir))

        spex_root = mock_workdir / ".spex"
        examples = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        assert examples.is_dir()
        assert (examples / "spec-template.md").exists()

    def test_idempotent(self, tmp_path, monkeypatch, mock_workdir):
        """Running init twice works without errors."""
        from init import run_init

        (mock_workdir / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )
        clear_spex_root_cache()

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
        ):
            run_init(workdir=str(mock_workdir))
            clear_spex_root_cache()
            run_init(workdir=str(mock_workdir))

        spex_root = mock_workdir / ".spex"
        examples = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        assert examples.is_dir()


    def test_normal_run_shows_status_without_verbose(self, tmp_path, caplog,
                                                         mock_workdir):
        """run_init() without -v shows status messages."""
        from init import run_init

        (mock_workdir / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\n', encoding="utf-8"
        )
        clear_spex_root_cache()

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
        ):
            # First run creates directories
            run_init(workdir=str(mock_workdir))
            clear_spex_root_cache()

            # Second run shows "Already initialized" without verbose
            run_init(workdir=str(mock_workdir))

        assert "Already initialized:" in caplog.text


class TestMainCheckFlag:
    def test_check_not_initialized(self, tmp_path):
        ctx = _make_context(spex_root="", spex_roots=[])

        with patch("init.get_project_context", return_value=ctx):
            from init import main

            with pytest.raises(SystemExit) as exc_info:
                main(argv=["--check"])
            assert exc_info.value.code == 1

    def test_check_initialized(self, tmp_path):
        spex_root = tmp_path / "spex"
        (spex_root / "specs").mkdir(parents=True)
        ctx = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )

        with patch("init.get_project_context", return_value=ctx):
            from init import main

            with pytest.raises(SystemExit) as exc_info:
                main(argv=["--check"])
            assert exc_info.value.code == 0


class TestVerboseFlag:
    def test_main_parses_verbose_short(self):
        """main() passes verbose=True when -v is given."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["-v"])
        mock_run.assert_called_once_with(
            target_dir=None, verbose=True, dry_run=False, skip_deps=False,
        )

    def test_main_parses_verbose_long(self):
        """main() passes verbose=True when --verbose is given."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["--verbose"])
        mock_run.assert_called_once_with(
            target_dir=None, verbose=True, dry_run=False, skip_deps=False,
        )

    def test_main_default_not_verbose(self):
        """main() passes verbose=False by default."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=[])
        mock_run.assert_called_once_with(
            target_dir=None, verbose=False, dry_run=False, skip_deps=False,
        )

    def test_main_parses_target_dir(self):
        """main() passes target_dir when positional arg is given."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["/some/dir"])
        mock_run.assert_called_once_with(
            target_dir="/some/dir", verbose=False, dry_run=False,
            skip_deps=False,
        )

    def test_main_parses_target_dir_with_verbose(self):
        """main() passes both target_dir and verbose."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["-v", "/some/dir"])
        mock_run.assert_called_once_with(
            target_dir="/some/dir", verbose=True, dry_run=False,
            skip_deps=False,
        )

    def test_main_parses_skip_deps(self):
        """main() passes skip_deps=True when --skip-deps is given."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["--skip-deps"])
        mock_run.assert_called_once_with(
            target_dir=None, verbose=False, dry_run=False, skip_deps=True,
        )

    def test_run_init_passes_verbose_to_ensure_initialized(self, tmp_path):
        """run_init(verbose=True) forwards verbose to ensure_initialized."""
        spex_root = tmp_path / ".spex"
        ctx = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
            patch("init.get_project_context", return_value=ctx),
            patch("init.ensure_initialized") as mock_ensure,
        ):
            from init import run_init

            run_init(workdir=str(tmp_path), verbose=True)

        mock_ensure.assert_called_once_with(
            str(spex_root), verbose=True, dry_run=False,
        )

    def test_ensure_initialized_verbose_output(self, tmp_path, caplog):
        """ensure_initialized(verbose=True) prints directory creation."""
        from common import ensure_initialized

        spex_root = tmp_path / "spex"
        ensure_initialized(str(spex_root), verbose=True)

        assert "Initializing:" in caplog.text
        assert f"Created: {spex_root}/" in caplog.text
        assert "specs/" in caplog.text
        assert "archives/" in caplog.text
        assert "hooks/" in caplog.text

    def test_ensure_initialized_verbose_already_initialized(self, tmp_path, caplog):
        """ensure_initialized(verbose=True) reports when already initialized."""
        from common import ensure_initialized

        spex_root = tmp_path / "spex"
        (spex_root / "specs").mkdir(parents=True)
        ensure_initialized(str(spex_root), verbose=True)

        assert "Already initialized:" in caplog.text

    def test_ensure_initialized_shows_created_without_verbose(self, tmp_path, caplog):
        """ensure_initialized(verbose=False) prints Created but not Initializing."""
        from common import ensure_initialized

        spex_root = tmp_path / "spex"
        ensure_initialized(str(spex_root))

        assert "Initializing:" not in caplog.text
        assert f"Created: {spex_root}/" in caplog.text
        assert "specs/" in caplog.text
        assert "archives/" in caplog.text

    def test_ensure_initialized_shows_already_without_verbose(self, tmp_path, caplog):
        """ensure_initialized(verbose=False) prints 'Already initialized'."""
        from common import ensure_initialized

        spex_root = tmp_path / "spex"
        (spex_root / "specs").mkdir(parents=True)
        ensure_initialized(str(spex_root))

        assert "Already initialized:" in caplog.text


class TestResolveTargetDir:
    def test_git_repo_returns_main_worktree(self, mock_workdir):
        from init import _resolve_target_dir

        result = _resolve_target_dir(str(mock_workdir))
        assert result == mock_workdir

    def test_non_git_dir_returns_as_is(self, tmp_path):
        target = tmp_path / "plain"
        target.mkdir()

        from init import _resolve_target_dir

        result = _resolve_target_dir(str(target))
        assert result == target

    def test_nonexistent_dir_exits(self, tmp_path):
        from init import _resolve_target_dir

        with pytest.raises(SystemExit) as exc_info:
            _resolve_target_dir(str(tmp_path / "nope"))
        assert exc_info.value.code == 1


class TestInitTargetToml:
    def test_creates_toml_with_inherited_config(self, tmp_path, caplog):
        """Creates .spex.toml inheriting user-set values from parent config."""
        target = tmp_path / "project"
        target.mkdir()
        home_toml = tmp_path / "home" / ".spex.toml"
        home_toml.parent.mkdir()
        home_toml.write_text('[spex]\nbranch_management = false\n')

        with patch("config.Path.home", return_value=home_toml.parent):
            from init import _init_target_toml

            clear_spex_root_cache()
            with caplog.at_level(logging.INFO):
                _init_target_toml(target)

        toml_path = target / ".spex.toml"
        assert toml_path.exists()
        content = toml_path.read_text()
        assert "branch_management = false" in content
        assert 'spex_root = ".spex"' in content
        assert "Created:" in caplog.text

    def test_creates_toml_with_forced_spex_root(self, tmp_path):
        """Creates .spex.toml with spex_root always explicit."""
        target = tmp_path / "project"
        target.mkdir()

        with patch("config.Path.home", return_value=tmp_path / "empty_home"):
            from init import _init_target_toml

            clear_spex_root_cache()
            _init_target_toml(target)

        content = (target / ".spex.toml").read_text()
        assert 'spex_root = ".spex"' in content
        assert "# branch_management = true" in content

    def test_skips_when_toml_exists(self, tmp_path):
        """Does not overwrite existing .spex.toml."""
        target = tmp_path / "project"
        target.mkdir()
        toml_path = target / ".spex.toml"
        toml_path.write_text('[spex]\nspex_root = "custom"\n')

        from init import _init_target_toml

        _init_target_toml(target)

        assert toml_path.read_text() == '[spex]\nspex_root = "custom"\n'


@pytest.mark.slow
class TestRunInitWithTargetDir:
    def test_creates_toml_in_target_dir(self, tmp_path, mock_workdir):
        """spex init <dir> creates .spex.toml in the target directory."""
        from init import run_init

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("config.Path.home", return_value=tmp_path / "empty_home"),
        ):
            clear_spex_root_cache()
            run_init(target_dir=str(mock_workdir))

        toml_path = mock_workdir / ".spex.toml"
        assert toml_path.exists()
        spex_root = mock_workdir / ".spex"
        assert (spex_root / "specs").is_dir()

    def test_inherits_parent_config(self, tmp_path, mock_workdir):
        """Target dir .spex.toml inherits values from ~/.spex.toml."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".spex.toml").write_text(
            '[spex]\nbranch_management = false\n'
        )

        from init import run_init

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("config.Path.home", return_value=fake_home),
        ):
            clear_spex_root_cache()
            run_init(target_dir=str(mock_workdir))

        content = (mock_workdir / ".spex.toml").read_text()
        assert "branch_management = false" in content


@pytest.mark.slow
class TestDryRun:
    def test_dry_run_does_not_create_dirs(self, tmp_path):
        """dry_run=True does not create any files or directories."""
        spex_root = tmp_path / ".spex"
        ctx = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
            patch("init.get_project_context", return_value=ctx),
        ):
            from init import run_init

            run_init(workdir=str(tmp_path), dry_run=True)

        assert not spex_root.exists()

    def test_dry_run_shows_operations(self, tmp_path, caplog):
        """dry_run=True prints 'Would' messages via logging."""
        spex_root = tmp_path / ".spex"
        ctx = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
            patch("init.get_project_context", return_value=ctx),
        ):
            from init import run_init

            run_init(workdir=str(tmp_path), dry_run=True)

        assert "Would initialize:" in caplog.text
        assert "Would create:" in caplog.text
        assert f"Would create: {spex_root}/" in caplog.text

    def test_dry_run_target_dir_shows_spex_root(self, tmp_path, caplog):
        """dry_run with target_dir resolves spex_root without .spex.toml on disk."""
        target = tmp_path / "target"
        target.mkdir()

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init.get_main_worktree", return_value=None),
        ):
            from init import run_init

            clear_spex_root_cache()
            with caplog.at_level(logging.INFO):
                run_init(target_dir=str(target), dry_run=True)

        assert "Would create:" in caplog.text
        expected_spex = str(target / ".spex")
        assert expected_spex in caplog.text

        # Verify nothing was actually created
        assert not (target / ".spex").exists()
        assert not (target / ".spex.toml").exists()

    def test_dry_run_flag_short(self):
        """Parser accepts -n and sets dry_run=True."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["-n"])
        mock_run.assert_called_once_with(
            target_dir=None, verbose=False, dry_run=True, skip_deps=False,
        )

    def test_dry_run_flag_long(self):
        """Parser accepts --dry-run and sets dry_run=True."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["--dry-run"])
        mock_run.assert_called_once_with(
            target_dir=None, verbose=False, dry_run=True, skip_deps=False,
        )


class TestDepsSatisfied:
    """Fast tests for dependency presence checks and skip paths."""

    def test_deps_satisfied_when_imports_exist(self, tmp_path, monkeypatch):
        from init import _deps_satisfied

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\ndependencies = ["jinja2"]\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "init.importlib.util.find_spec",
            lambda name: object() if name == "jinja2" else None,
        )
        assert _deps_satisfied(tmp_path) is True

    def test_deps_not_satisfied_when_missing(self, tmp_path, monkeypatch):
        from init import _deps_satisfied

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\ndependencies = ["jinja2"]\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "init.importlib.util.find_spec",
            lambda name: None,
        )
        assert _deps_satisfied(tmp_path) is False

    def test_install_deps_skips_when_satisfied(self, caplog, monkeypatch):
        monkeypatch.setattr("init._deps_satisfied", lambda skill_dir: True)
        with patch("init.subprocess.run") as mock_run:
            with caplog.at_level(logging.INFO):
                from init import _install_deps
                assert _install_deps() is True
        mock_run.assert_not_called()
        assert "already satisfied" in caplog.text

    def test_install_deps_runs_pip_when_missing(self, monkeypatch):
        monkeypatch.setattr("init._deps_satisfied", lambda skill_dir: False)
        with patch(
            "init.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as mock_run:
            from init import _install_deps
            assert _install_deps() is True
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "pip" in cmd
        from common import _get_skill_path
        assert str(_get_skill_path()) in cmd
        assert "--no-input" in cmd
        assert "--no-deps" not in cmd
        assert not any(
            isinstance(a, str) and a.startswith(("http://", "https://"))
            for a in cmd
        )

    def test_install_deps_uv_argv_local_skill_dir(self, monkeypatch):
        monkeypatch.setattr("init._deps_satisfied", lambda skill_dir: False)
        monkeypatch.setattr(
            "init.shutil.which",
            lambda name: "/usr/bin/uv" if name == "uv" else None,
        )
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if "-m" in cmd and "pip" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 1, stdout="", stderr="fail",
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("init.subprocess.run", side_effect=fake_run):
            from init import _install_deps
            assert _install_deps() is True
        uv_cmd = calls[1]
        from common import _get_skill_path
        assert str(_get_skill_path()) in uv_cmd
        assert "--no-input" in uv_cmd
        assert "--no-deps" not in uv_cmd
        assert not any(
            isinstance(a, str) and a.startswith(("http://", "https://"))
            for a in uv_cmd
        )

    def test_pyproject_pins_jinja2(self):
        pyproject = (
            Path(__file__).resolve().parent.parent
            / "skills" / "spex" / "pyproject.toml"
        )
        content = pyproject.read_text(encoding="utf-8")
        assert '"jinja2>=3.1.0"' in content

    def test_dry_run_would_skip_when_satisfied(self, caplog, monkeypatch):
        monkeypatch.setattr("init._deps_satisfied", lambda skill_dir: True)
        with caplog.at_level(logging.INFO):
            from init import _install_deps
            assert _install_deps(dry_run=True) is True
        assert "Would skip dependency installation" in caplog.text

    def test_dry_run_would_install_when_missing(self, caplog, monkeypatch):
        monkeypatch.setattr("init._deps_satisfied", lambda skill_dir: False)
        with caplog.at_level(logging.INFO):
            from init import _install_deps
            assert _install_deps(dry_run=True) is True
        assert "Would install dependencies" in caplog.text

    def test_skip_deps_bypasses_install(self, tmp_path, caplog):
        spex_root = tmp_path / ".spex"
        ctx = _make_context(
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            spex_tomls=[tmp_path / ".spex.toml"],
        )
        with (
            patch("init.get_project_context", return_value=ctx),
            patch("init.get_top_workdir", return_value=tmp_path),
            patch("init._install_deps") as mock_install,
            patch("init._create_toml_config"),
            patch("init.ensure_initialized"),
            patch("init._sync_all_templates"),
            patch("init._install_cli"),
        ):
            with caplog.at_level(logging.INFO):
                from init import run_init
                run_init(workdir=str(tmp_path), skip_deps=True)
        mock_install.assert_not_called()
        assert "--skip-deps" in caplog.text


@pytest.mark.slow
class TestInstallDeps:
    """Test _install_deps function (lines 41-61)."""

    def test_dry_run_returns_true(self, caplog, monkeypatch):
        """_install_deps(dry_run=True) returns True without installing."""
        monkeypatch.setattr("init._deps_satisfied", lambda skill_dir: False)
        with caplog.at_level(logging.INFO):
            from init import _install_deps
            assert _install_deps(dry_run=True) is True
        assert "Would install dependencies" in caplog.text

    def test_verbose_shows_message(self, caplog, monkeypatch):
        """_install_deps(verbose=True) shows installing message when needed."""
        monkeypatch.setattr("init._deps_satisfied", lambda skill_dir: False)
        with patch(
            "init.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ):
            with caplog.at_level(logging.INFO):
                from init import _install_deps
                _install_deps(verbose=True)
        assert "Installing dependencies from" in caplog.text


class TestInstallCli:
    """Test _install_cli function (lines 64-92)."""

    def test_dry_run_returns_early(self, caplog):
        """_install_cli(dry_run=True) shows 'Would install' and returns."""
        with caplog.at_level(logging.INFO):
            from init import _install_cli
            _install_cli(dry_run=True)
        assert "Would install CLI:" in caplog.text


class TestCreateTomlConfigDryRun:
    """Test _create_toml_config dry-run paths (lines 138-140, 153-155)."""

    def test_dry_run_reinitializes(self, tmp_path, caplog):
        """_create_toml_config(dry_run=True) with existing tomls shows 'Would reinitialize'."""
        toml_file = tmp_path / ".spex.toml"
        toml_file.write_text('[spex]\nspex_root = "custom"\n')
        ctx = _make_context(spex_tomls=[toml_file])
        with (
            patch("init.get_project_context", return_value=ctx),
            patch("init.clear_config_cache"),
        ):
            with caplog.at_level(logging.INFO):
                from init import _create_toml_config
                _create_toml_config(dry_run=True)
        assert "Would reinitialize:" in caplog.text

    def test_dry_run_creates_home_toml(self, tmp_path, caplog):
        """_create_toml_config(dry_run=True) with no tomls shows 'Would create'."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        ctx = _make_context(spex_tomls=[])
        with (
            patch("init.get_project_context", return_value=ctx),
            patch("init.Path.home", return_value=fake_home),
            patch("common.Path.home", return_value=fake_home),
        ):
            with caplog.at_level(logging.INFO):
                from init import _create_toml_config
                _create_toml_config(dry_run=True)
        assert "Would create:" in caplog.text
        # Verify nothing was actually created
        assert not (fake_home / ".spex.toml").exists()

    def test_dry_run_up_to_date(self, tmp_path, caplog):
        """_create_toml_config(dry_run=True) with up-to-date toml shows 'Config up-to-date'."""
        toml_file = tmp_path / ".spex.toml"
        from config import generate_default_toml
        toml_file.write_text(generate_default_toml())
        ctx = _make_context(spex_tomls=[toml_file])
        with (
            patch("init.get_project_context", return_value=ctx),
            patch("init.clear_config_cache"),
        ):
            with caplog.at_level(logging.INFO):
                from init import _create_toml_config
                _create_toml_config(dry_run=True)
        assert "Config up-to-date:" in caplog.text


@pytest.mark.slow
class TestInitModuleDirectExecution:
    """Test if __name__ == '__main__' path (lines 239-241)."""

    def test_direct_script_check_flag(self):
        """Running init.py directly with --check works."""
        result = subprocess.run(
            [sys.executable, str(
                Path(__file__).resolve().parent.parent / "skills" / "spex" / "scripts" / "init.py"
            ), "--check"],
            capture_output=True, text=True,
        )
        # Should exit 0 (initialized) or 1 (not initialized)
        assert result.returncode in (0, 1)


_GOOD_WHEEL = (
    "https://files.pythonhosted.org/packages/"
    "jinja2-3.1.0-py3-none-any.whl"
)
_PYPI_WHEEL = "https://pypi.org/packages/jinja2-3.1.0-py3-none-any.whl"


class TestWheelUrlAllowlist:
    """URL checks for the wheel-download fallback."""

    def test_allows_pythonhosted_https(self):
        from init import _is_allowed_wheel_url

        assert _is_allowed_wheel_url(_GOOD_WHEEL) is True

    def test_allows_pypi_org_https(self):
        from init import _is_allowed_wheel_url

        assert _is_allowed_wheel_url(_PYPI_WHEEL) is True

    def test_rejects_http(self):
        from init import _is_allowed_wheel_url

        assert _is_allowed_wheel_url(
            "http://files.pythonhosted.org/packages/"
            "jinja2-3.1.0-py3-none-any.whl"
        ) is False

    def test_rejects_unknown_host(self):
        from init import _is_allowed_wheel_url

        assert _is_allowed_wheel_url(
            "https://evil.example/jinja2-3.1.0-py3-none-any.whl"
        ) is False

    def test_rejects_lookalike_host(self):
        from init import _is_allowed_wheel_url

        assert _is_allowed_wheel_url(
            "https://files.pythonhosted.org.evil.example/x.whl"
        ) is False

    def test_rejects_userinfo(self):
        from init import _is_allowed_wheel_url

        assert _is_allowed_wheel_url(
            "https://user:pass@pypi.org/x.whl"
        ) is False

    def test_rejects_invalid_port(self):
        from init import _is_allowed_wheel_url

        assert _is_allowed_wheel_url("https://pypi.org:abc/x.whl") is False

    def test_pypi_json_url_exact(self):
        from init import _is_allowed_pypi_json_url

        assert _is_allowed_pypi_json_url(
            "https://pypi.org/pypi/jinja2/json", "jinja2",
        ) is True
        assert _is_allowed_pypi_json_url(
            "http://pypi.org/pypi/jinja2/json", "jinja2",
        ) is False
        assert _is_allowed_pypi_json_url(
            "https://pypi.org/pypi/jinja2/json", "evil",
        ) is False
        assert _is_allowed_pypi_json_url(
            "https://pypi.org/pypi/jinja2/../evil/json", "jinja2/../evil",
        ) is False


class TestInstallSingleWheel:
    """_install_single_wheel rejects untrusted URLs before downloading."""

    @staticmethod
    def _pypi_json(url):
        return json.dumps({
            "urls": [{
                "filename": "jinja2-3.1.0-py3-none-any.whl",
                "url": url,
            }],
        })

    def test_rejects_bad_wheel_url_without_download(self):
        from init import _install_single_wheel

        bad = "https://evil.example/jinja2-3.1.0-py3-none-any.whl"
        payload = self._pypi_json(bad)
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(
                cmd, 0, stdout=payload, stderr="",
            )

        with patch("init.subprocess.run", side_effect=fake_run):
            assert _install_single_wheel("jinja2", "/tmp/site") is False
        assert len(calls) == 1
        assert calls[0][-1] == "https://pypi.org/pypi/jinja2/json"
        assert not any(bad in part for cmd in calls for part in cmd)

    def test_rejects_http_wheel_url_without_download(self):
        from init import _install_single_wheel

        bad = (
            "http://files.pythonhosted.org/packages/"
            "jinja2-3.1.0-py3-none-any.whl"
        )
        payload = self._pypi_json(bad)
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(
                cmd, 0, stdout=payload, stderr="",
            )

        with patch("init.subprocess.run", side_effect=fake_run):
            assert _install_single_wheel("jinja2", "/tmp/site") is False
        assert len(calls) == 1
        assert not any(bad in part for cmd in calls for part in cmd)

    def test_allowed_pythonhosted_url_is_fetched(self):
        from init import _install_single_wheel

        payload = self._pypi_json(_GOOD_WHEEL)
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if any("pypi.org/pypi/" in str(a) for a in cmd):
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=payload, stderr="",
                )
            return subprocess.CompletedProcess(cmd, 1)

        with patch("init.subprocess.run", side_effect=fake_run):
            _install_single_wheel("jinja2", "/tmp/site")
        assert any(_GOOD_WHEEL in part for cmd in calls for part in cmd)

    def test_rejects_invalid_package_name(self):
        from init import _install_single_wheel

        with patch("init.subprocess.run") as mock_run:
            assert _install_single_wheel(
                "jinja2/../../evil", "/tmp/site",
            ) is False
        mock_run.assert_not_called()
