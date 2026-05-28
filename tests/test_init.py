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


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_spex_root_cache()
    yield


@pytest.fixture()
def mock_workdir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    return repo


class TestIsInitialized:
    def _mock_context(self, monkeypatch, spex_root_path):
        from config import SpexContext
        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(spex_root_path),
            spex_roots=[str(spex_root_path)],
            worktree_root=None,
        )
        monkeypatch.setattr("common.get_context", lambda w=None: ctx)
        clear_spex_root_cache()

    def test_not_initialized(self, tmp_path, monkeypatch):
        self._mock_context(monkeypatch, tmp_path / "spex")
        from init import is_initialized

        assert is_initialized() is False

    def test_initialized(self, tmp_path, monkeypatch):
        spex_root = tmp_path / "spex"
        (spex_root / "specs").mkdir(parents=True)
        (spex_root / "archives").mkdir(parents=True)
        (spex_root / "hooks").mkdir(parents=True)
        (spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR).mkdir(parents=True)
        self._mock_context(monkeypatch, spex_root)
        from init import is_initialized

        assert is_initialized() is True

    def test_missing_specs_dir(self, tmp_path, monkeypatch):
        spex_root = tmp_path / "spex"
        (spex_root / "archives").mkdir(parents=True)
        (spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR).mkdir(parents=True)
        self._mock_context(monkeypatch, spex_root)
        from init import is_initialized

        assert is_initialized() is False


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
        """Target does not exist → copy."""
        spex_root = tmp_path / "spex"
        spex_root.mkdir()
        _sync_builtin_template("spec-template.md", spex_root=spex_root)

        target = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR / "spec-template.md"
        assert target.exists()

    def test_skips_when_version_matches(self, tmp_path):
        """Target exists with same version → skip (no copy)."""
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
        """Target exists with different version → overwrite."""
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
        """Target exists with different mtime → overwrite regardless of version."""
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
        from config import SpexContext

        spex_root = tmp_path / "empty_spex"
        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
            worktree_root=None,
        )
        monkeypatch.setattr("common.get_context", lambda w=None: ctx)
        clear_spex_root_cache()

        from common import get_spex_root

        result = get_spex_root()
        assert result == str(spex_root)
        assert (spex_root / "specs").is_dir()
        assert (spex_root / "archives").is_dir()


class TestRunInit:
    def test_creates_templates(self, tmp_path, monkeypatch, mock_workdir):
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
        from init import run_init

        (mock_workdir / ".spex.toml").write_text(
            'spex_root = ".spex"\n', encoding="utf-8"
        )
        clear_spex_root_cache()

        with patch("init._install_deps"), patch("init._install_cli"):
            run_init(workdir=str(mock_workdir))
            run_init(workdir=str(mock_workdir))

        spex_root = mock_workdir / ".spex"
        examples = spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR
        assert examples.is_dir()


class TestMainCheckFlag:
    def _mock_context(self, monkeypatch, spex_root_path):
        from config import SpexContext
        ctx = SpexContext(
            spex_tomls=[],
            config={},
            spex_root=str(spex_root_path),
            spex_roots=[str(spex_root_path)],
            worktree_root=None,
        )
        monkeypatch.setattr("common.get_context", lambda w=None: ctx)
        clear_spex_root_cache()

    def test_check_not_initialized(self, tmp_path, monkeypatch):
        self._mock_context(monkeypatch, tmp_path / "missing")
        monkeypatch.setattr(sys, "argv", ["spex", "init", "--check"])

        from init import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_check_initialized(self, tmp_path, monkeypatch):
        spex_root = tmp_path / "spex"
        (spex_root / "specs").mkdir(parents=True)
        (spex_root / "archives").mkdir(parents=True)
        (spex_root / "hooks").mkdir(parents=True)
        (spex_root / TEMPLATE_DIR / EXAMPLES_TEMPLATE_DIR).mkdir(parents=True)
        self._mock_context(monkeypatch, spex_root)
        monkeypatch.setattr(sys, "argv", ["spex", "init", "--check"])

        from init import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
