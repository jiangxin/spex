"""Test version consistency between pyproject.toml and SKILL.md."""

import version


class TestVersionConsistency:
    def test_pyproject_version_readable(self):
        ver = version.get_pyproject_version()
        assert ver is not None
        assert ver != ""

    def test_skill_version_readable(self):
        ver = version.get_skill_version()
        assert ver is not None
        assert ver != ""

    def test_versions_match(self):
        assert version.get_pyproject_version() == version.get_skill_version()
