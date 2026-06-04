import logging
import subprocess
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
        src = Path(__file__).resolve().parent.parent / "templates" / "spec-template.md"
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
        src = Path(__file__).resolve().parent.parent / "templates" / "spec-template.md"

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

    def test_creates_templates_gitignore(self, tmp_path):
        from common import _write_internal_gitignore

        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        _write_internal_gitignore(spex_root)

        tpl_gitignore = spex_root / "templates" / ".gitignore"
        assert tpl_gitignore.exists()
        assert "/examples/" in tpl_gitignore.read_text()

    def test_skips_when_already_exists(self, tmp_path):
        from common import _write_internal_gitignore

        spex_root = tmp_path / ".spex"
        spex_root.mkdir()
        gitignore = spex_root / ".gitignore"
        gitignore.write_text("custom content\n")

        _write_internal_gitignore(spex_root)

        assert gitignore.read_text() == "custom content\n"


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
            target_dir=None, verbose=True, dry_run=False,
        )

    def test_main_parses_verbose_long(self):
        """main() passes verbose=True when --verbose is given."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["--verbose"])
        mock_run.assert_called_once_with(
            target_dir=None, verbose=True, dry_run=False,
        )

    def test_main_default_not_verbose(self):
        """main() passes verbose=False by default."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=[])
        mock_run.assert_called_once_with(
            target_dir=None, verbose=False, dry_run=False,
        )

    def test_main_parses_target_dir(self):
        """main() passes target_dir when positional arg is given."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["/some/dir"])
        mock_run.assert_called_once_with(
            target_dir="/some/dir", verbose=False, dry_run=False,
        )

    def test_main_parses_target_dir_with_verbose(self):
        """main() passes both target_dir and verbose."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["-v", "/some/dir"])
        mock_run.assert_called_once_with(
            target_dir="/some/dir", verbose=True, dry_run=False,
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
            target_dir=None, verbose=False, dry_run=True,
        )

    def test_dry_run_flag_long(self):
        """Parser accepts --dry-run and sets dry_run=True."""
        with patch("init.run_init") as mock_run:
            from init import main

            main(argv=["--dry-run"])
        mock_run.assert_called_once_with(
            target_dir=None, verbose=False, dry_run=True,
        )
