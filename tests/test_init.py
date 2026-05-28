import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import (
    EXAMPLES_TEMPLATE_DIR,
    TEMPLATE_DIR,
    _sync_builtin_template,
    clear_spex_root_cache,
)
from config import SpexContext


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
    worktree_root=None,
):
    """Helper to build a SpexContext for mocking."""
    return SpexContext(
        spex_tomls=spex_tomls or [],
        config=config or {},
        spex_root=spex_root,
        spex_roots=spex_roots or [],
        worktree_root=worktree_root,
    )


class TestIsInitialized:
    def test_not_initialized_no_roots(self, tmp_path):
        """Returns False when no spex_roots are resolved."""
        ctx = _make_context(spex_root="", spex_roots=[])
        with patch("init.get_context", return_value=ctx):
            from init import is_initialized

            assert is_initialized() is False

    def test_not_initialized_no_specs_dir(self, tmp_path):
        """Returns False when spex_root exists but specs/ is missing."""
        spex_root = tmp_path / "spex"
        spex_root.mkdir()
        ctx = _make_context(
            spex_root=str(spex_root), spex_roots=[str(spex_root)]
        )
        with patch("init.get_context", return_value=ctx):
            from init import is_initialized

            assert is_initialized() is False

    def test_initialized(self, tmp_path):
        """Returns True when spex_roots is non-empty and specs/ exists."""
        spex_root = tmp_path / "spex"
        (spex_root / "specs").mkdir(parents=True)
        ctx = _make_context(
            spex_root=str(spex_root), spex_roots=[str(spex_root)]
        )
        with patch("init.get_context", return_value=ctx):
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
        assert (spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR).is_dir()
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
        monkeypatch.setattr("common.get_context", lambda w=None: ctx)
        clear_spex_root_cache()

        from common import get_spex_root

        result = get_spex_root()
        assert result == str(spex_root)
        assert (spex_root / "specs").is_dir()
        assert (spex_root / "archives").is_dir()


class TestCreateTomlConfig:
    def test_creates_home_toml_when_no_config(self, tmp_path):
        """Creates ~/.spex.toml when no config exists."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        ctx = _make_context(spex_tomls=[])
        with (
            patch("init.get_context", return_value=ctx),
            patch("init.Path.home", return_value=fake_home),
            patch("init.clear_config_cache"),
        ):
            from init import _create_toml_config

            _create_toml_config()

        toml_file = fake_home / ".spex.toml"
        assert toml_file.exists()
        assert toml_file.read_text() == '# spex_root = ".spex"\n'

    def test_preserves_existing_config(self, tmp_path):
        """Does not overwrite when config already exists."""
        existing_toml = tmp_path / ".spex.toml"
        existing_toml.write_text('spex_root = "custom"\n')

        ctx = _make_context(spex_tomls=[existing_toml])
        with patch("init.get_context", return_value=ctx):
            from init import _create_toml_config

            _create_toml_config()

        # File should be unchanged
        assert existing_toml.read_text() == 'spex_root = "custom"\n'


class TestRunInit:
    def test_creates_spex_dir_when_no_roots(self, tmp_path):
        """Creates ~/.spex/ when no roots exist."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        # First call (from _create_toml_config): no tomls
        ctx_no_roots = _make_context(
            spex_root="",
            spex_roots=[],
            spex_tomls=[],
            config={"spex_root": ".spex"},
        )

        with (
            patch("init._install_deps"),
            patch("init._install_cli"),
            patch("init._create_toml_config"),
            patch("init.clear_config_cache"),
            patch("init.get_context", return_value=ctx_no_roots),
            patch("init.Path.home", return_value=fake_home),
            patch("init.ensure_initialized") as mock_ensure,
        ):
            from init import run_init

            run_init(workdir=str(tmp_path))

        mock_ensure.assert_called_once_with(str(fake_home / ".spex"))

    def test_uses_existing_root(self, tmp_path):
        """Uses existing spex_root when roots are already resolved."""
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
            patch("init.clear_config_cache"),
            patch("init.get_context", return_value=ctx_with_roots),
            patch("init.ensure_initialized") as mock_ensure,
        ):
            from init import run_init

            run_init(workdir=str(tmp_path))

        mock_ensure.assert_called_once_with(str(spex_root))

    def test_creates_templates(self, tmp_path, monkeypatch, mock_workdir):
        """Integration: templates are created during init."""
        from init import run_init

        (mock_workdir / ".spex.toml").write_text(
            'spex_root = ".spex"\n', encoding="utf-8"
        )
        clear_spex_root_cache()

        with patch("init._install_deps"), patch("init._install_cli"):
            run_init(workdir=str(mock_workdir))

        spex_root = mock_workdir / ".spex"
        examples = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        assert examples.is_dir()
        assert (examples / "spec-template.md").exists()

    def test_idempotent(self, tmp_path, monkeypatch, mock_workdir):
        """Running init twice works without errors."""
        from init import run_init

        (mock_workdir / ".spex.toml").write_text(
            'spex_root = ".spex"\n', encoding="utf-8"
        )
        clear_spex_root_cache()

        with patch("init._install_deps"), patch("init._install_cli"):
            run_init(workdir=str(mock_workdir))
            clear_spex_root_cache()
            run_init(workdir=str(mock_workdir))

        spex_root = mock_workdir / ".spex"
        examples = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        assert examples.is_dir()


class TestMainCheckFlag:
    def test_check_not_initialized(self, tmp_path, monkeypatch):
        ctx = _make_context(spex_root="", spex_roots=[])
        monkeypatch.setattr(sys, "argv", ["spex", "init", "--check"])

        with patch("init.get_context", return_value=ctx):
            from init import main

            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_check_initialized(self, tmp_path, monkeypatch):
        spex_root = tmp_path / "spex"
        (spex_root / "specs").mkdir(parents=True)
        ctx = _make_context(
            spex_root=str(spex_root), spex_roots=[str(spex_root)]
        )
        monkeypatch.setattr(sys, "argv", ["spex", "init", "--check"])

        with patch("init.get_context", return_value=ctx):
            from init import main

            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
