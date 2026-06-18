"""Tests for version.py: version bump, check, and parsing logic."""

import subprocess
import sys
from pathlib import Path

import pytest
import version

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "version.py")


class TestGetPyprojectVersion:
    """Test get_pyproject_version function."""

    def test_reads_version_from_existing_file(self):
        """Normal pyproject.toml with version = "x.y.z"."""
        ver = version.get_pyproject_version()
        assert ver is not None
        assert ver == version.get_skill_version()

    def test_missing_file_returns_none(self, monkeypatch, tmp_path):
        """pyproject.toml doesn't exist -> returns None."""
        fake = tmp_path / "pyproject.toml"
        monkeypatch.setattr(version, "_PYPROJECT", fake)
        assert version.get_pyproject_version() is None

    def test_no_version_line_returns_none(self, monkeypatch, tmp_path):
        """pyproject.toml exists but has no version line."""
        p = tmp_path / "pyproject.toml"
        p.write_text('[project]\nname = "test"\n', encoding="utf-8")
        monkeypatch.setattr(version, "_PYPROJECT", p)
        assert version.get_pyproject_version() is None


class TestGetSkillVersion:
    """Test get_skill_version function."""

    def test_reads_version_from_existing_file(self):
        """Normal SKILL.md with version in front-matter."""
        ver = version.get_skill_version()
        assert ver is not None

    def test_missing_file_returns_none(self, monkeypatch, tmp_path):
        """SKILL.md doesn't exist -> returns None."""
        fake = tmp_path / "SKILL.md"
        monkeypatch.setattr(version, "_SKILL_MD", fake)
        assert version.get_skill_version() is None

    def test_no_version_line_returns_none(self, monkeypatch, tmp_path):
        """SKILL.md exists but has no version line."""
        p = tmp_path / "SKILL.md"
        p.write_text("# No version here\n", encoding="utf-8")
        monkeypatch.setattr(version, "_SKILL_MD", p)
        assert version.get_skill_version() is None

    def test_quoted_version_stripped(self, monkeypatch, tmp_path):
        """version: "1.2.3" -> strips quotes."""
        p = tmp_path / "SKILL.md"
        p.write_text('---\nversion: "1.2.3-beta"\n---\n', encoding="utf-8")
        monkeypatch.setattr(version, "_SKILL_MD", p)
        ver = version.get_skill_version()
        assert ver == "1.2.3-beta"

    def test_single_quoted_version_stripped(self, monkeypatch, tmp_path):
        """version: '1.2.3' -> strips single quotes."""
        p = tmp_path / "SKILL.md"
        p.write_text("---\nversion: '0.1.0'\n---\n", encoding="utf-8")
        monkeypatch.setattr(version, "_SKILL_MD", p)
        ver = version.get_skill_version()
        assert ver == "0.1.0"


class TestCheckVersions:
    """Test check_versions function."""

    def test_matching_versions_return_true(self):
        """Both files have the same version."""
        assert version.check_versions() is True

    def test_mismatch_returns_false(self, monkeypatch, tmp_path):
        """Different versions in pyproject.toml and SKILL.md -> False."""
        pp = tmp_path / "pyproject.toml"
        pp.write_text('version = "1.0.0"\n', encoding="utf-8")
        sk = tmp_path / "SKILL.md"
        sk.write_text("version: 2.0.0\n", encoding="utf-8")
        monkeypatch.setattr(version, "_PYPROJECT", pp)
        monkeypatch.setattr(version, "_SKILL_MD", sk)
        assert version.check_versions() is False

    def test_missing_pyproject_returns_false(self, monkeypatch, tmp_path):
        """Missing pyproject.toml -> returns False."""
        fake = tmp_path / "pyproject.toml"
        sk = tmp_path / "SKILL.md"
        sk.write_text("version: 1.0.0\n", encoding="utf-8")
        monkeypatch.setattr(version, "_PYPROJECT", fake)
        monkeypatch.setattr(version, "_SKILL_MD", sk)
        assert version.check_versions() is False

    def test_missing_skill_md_returns_false(self, monkeypatch, tmp_path):
        """Missing SKILL.md -> returns False."""
        pp = tmp_path / "pyproject.toml"
        pp.write_text('version = "1.0.0"\n', encoding="utf-8")
        fake = tmp_path / "SKILL.md"
        monkeypatch.setattr(version, "_PYPROJECT", pp)
        monkeypatch.setattr(version, "_SKILL_MD", fake)
        assert version.check_versions() is False


class TestBumpVersion:
    """Test bump_version function."""

    def test_bump_both_files(self, monkeypatch, tmp_path, capsys):
        """Valid semver updates both files."""
        pp = tmp_path / "pyproject.toml"
        pp.write_text('version = "0.1.0"\n', encoding="utf-8")
        sk = tmp_path / "SKILL.md"
        sk.write_text("---\nversion: 0.1.0\n---\n", encoding="utf-8")
        monkeypatch.setattr(version, "_PYPROJECT", pp)
        monkeypatch.setattr(version, "_SKILL_MD", sk)

        result = version.bump_version("0.2.0")

        assert result is True
        assert pp.read_text(encoding="utf-8") == 'version = "0.2.0"\n'
        sk_content = sk.read_text(encoding="utf-8")
        assert "version: 0.2.0" in sk_content
        assert capsys.readouterr().out.strip() == "0.2.0"

    def test_invalid_semver_returns_false(self, monkeypatch, tmp_path):
        """Non-semver format -> returns False."""
        result = version.bump_version("not-a-version")
        assert result is False

    def test_missing_version_in_pyproject(self, monkeypatch, tmp_path):
        """pyproject.toml without version line -> returns False."""
        pp = tmp_path / "pyproject.toml"
        pp.write_text('name = "test"\n', encoding="utf-8")
        sk = tmp_path / "SKILL.md"
        sk.write_text("version: 1.0.0\n", encoding="utf-8")
        monkeypatch.setattr(version, "_PYPROJECT", pp)
        monkeypatch.setattr(version, "_SKILL_MD", sk)

        result = version.bump_version("2.0.0")
        assert result is False

    def test_missing_version_in_skill_md(self, monkeypatch, tmp_path):
        """SKILL.md without version line -> returns False."""
        pp = tmp_path / "pyproject.toml"
        pp.write_text('version = "1.0.0"\n', encoding="utf-8")
        sk = tmp_path / "SKILL.md"
        sk.write_text("# No version\n", encoding="utf-8")
        monkeypatch.setattr(version, "_PYPROJECT", pp)
        monkeypatch.setattr(version, "_SKILL_MD", sk)

        result = version.bump_version("2.0.0")
        assert result is False

    def test_bump_preserves_surrounding_content(self, monkeypatch, tmp_path):
        """Bump doesn't touch other lines in either file."""
        pp = tmp_path / "pyproject.toml"
        pp.write_text(
            '[project]\nname = "spex"\nversion = "0.1.0"\ndescription = "test"\n',
            encoding="utf-8",
        )
        sk = tmp_path / "SKILL.md"
        sk.write_text(
            "---\nversion: 0.1.0\ntitle: Spex\n---\n\n# Content\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(version, "_PYPROJECT", pp)
        monkeypatch.setattr(version, "_SKILL_MD", sk)

        version.bump_version("1.0.0")

        pp_content = pp.read_text(encoding="utf-8")
        assert 'name = "spex"' in pp_content
        assert 'description = "test"' in pp_content
        sk_content = sk.read_text(encoding="utf-8")
        assert "title: Spex" in sk_content
        assert "# Content" in sk_content

    def test_bump_with_prerelease(self, monkeypatch, tmp_path):
        """Bump with prerelease tag like 1.0.0-alpha."""
        pp = tmp_path / "pyproject.toml"
        pp.write_text('version = "0.1.0"\n', encoding="utf-8")
        sk = tmp_path / "SKILL.md"
        sk.write_text("version: 0.1.0\n", encoding="utf-8")
        monkeypatch.setattr(version, "_PYPROJECT", pp)
        monkeypatch.setattr(version, "_SKILL_MD", sk)

        result = version.bump_version("1.0.0-alpha")
        assert result is True
        assert 'version = "1.0.0-alpha"' in pp.read_text(encoding="utf-8")
        assert "version: 1.0.0-alpha" in sk.read_text(encoding="utf-8")


class TestMainCli:
    """Test main() CLI routing."""

    def test_default_mode_prints_version(self, monkeypatch, capsys):
        """main() with no flags prints version."""
        monkeypatch.setattr(version, "get_pyproject_version", lambda: "1.2.3")
        version.main([])
        assert capsys.readouterr().out.strip() == "1.2.3"

    def test_default_mode_missing_version_exits(
        self, monkeypatch, caplog, tmp_path,
    ):
        """main() with no version exits 1."""
        monkeypatch.setattr(version, "get_pyproject_version", lambda: None)
        with caplog.at_level(0):
            with pytest.raises(SystemExit) as exc_info:
                version.main([])
        assert exc_info.value.code == 1

    def test_check_mode_passes(self, monkeypatch, caplog):
        """main() --check with matching versions exits 0."""
        monkeypatch.setattr(version, "check_versions", lambda: True)
        monkeypatch.setattr(version, "get_pyproject_version", lambda: "1.0.0")
        version.main(["--check"])

    def test_check_mode_fails(self, monkeypatch, caplog):
        """main() --check with mismatched versions exits 1."""
        monkeypatch.setattr(version, "check_versions", lambda: False)
        with caplog.at_level(0):
            with pytest.raises(SystemExit) as exc_info:
                version.main(["--check"])
        assert exc_info.value.code == 1

    def test_bump_mode_valid(self, monkeypatch, capsys, tmp_path):
        """main() --bump with valid semver updates files."""
        pp = tmp_path / "pyproject.toml"
        pp.write_text('version = "0.1.0"\n', encoding="utf-8")
        sk = tmp_path / "SKILL.md"
        sk.write_text("version: 0.1.0\n", encoding="utf-8")
        monkeypatch.setattr(version, "_PYPROJECT", pp)
        monkeypatch.setattr(version, "_SKILL_MD", sk)

        version.main(["--bump", "0.2.0"])

        out = capsys.readouterr().out
        assert out.strip() == "0.2.0"

    def test_bump_mode_invalid(self, monkeypatch, caplog):
        """main() --bump with invalid semver exits 1."""
        with caplog.at_level(0):
            with pytest.raises(SystemExit) as exc_info:
                version.main(["--bump", "bad-version"])
        assert exc_info.value.code == 1


class TestScriptDirect:
    """Test if __name__ == '__main__' path."""

    def test_direct_script_no_args(self):
        """Running version.py directly prints version."""
        result = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        import re
        assert re.match(r"\d+\.\d+\.\d+", result.stdout.strip())

    def test_direct_script_check(self):
        """Running version.py --check succeeds."""
        result = subprocess.run(
            [sys.executable, SCRIPT, "--check"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
