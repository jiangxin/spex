import sys
from pathlib import Path
from unittest.mock import patch

import open_topic
import pytest
from open_topic import find_topic, main, open_directory


def _make_dir(base, name):
    """Create a subdirectory and return its path."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestFindTopic:
    """Tests for find_topic."""

    def test_exact_match_in_specs(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_dir(specs, "2026-05-20-14-30-my-topic")

        result = find_topic("2026-05-20-14-30-my-topic", specs, archives)

        assert len(result) == 1
        assert result[0][1] == "specs"
        assert Path(result[0][0]).name == "2026-05-20-14-30-my-topic"

    def test_exact_match_in_archives(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_dir(archives, "2026-05-20-14-30-archived")

        result = find_topic("2026-05-20-14-30-archived", specs, archives)

        assert len(result) == 1
        assert result[0][1] == "archives"

    def test_exact_match_in_both(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_dir(specs, "shared-name")
        _make_dir(archives, "shared-name")

        result = find_topic("shared-name", specs, archives)

        assert len(result) == 2
        labels = {r[1] for r in result}
        assert labels == {"specs", "archives"}

    def test_substring_single_match(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_dir(specs, "2026-05-20-14-30-feature-login")
        _make_dir(specs, "2026-05-20-14-30-bugfix-logout")

        result = find_topic("login", specs, archives)

        assert len(result) == 1
        assert Path(result[0][0]).name == "2026-05-20-14-30-feature-login"

    def test_substring_multiple_matches(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_dir(specs, "2026-05-20-14-30-edit-alpha")
        _make_dir(archives, "2026-05-20-14-30-edit-beta")

        result = find_topic("edit", specs, archives)

        assert len(result) == 2
        names = [Path(r[0]).name for r in result]
        assert "2026-05-20-14-30-edit-alpha" in names
        assert "2026-05-20-14-30-edit-beta" in names

    def test_no_match(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_dir(specs, "2026-05-20-14-30-something")

        result = find_topic("nonexistent", specs, archives)

        assert result == []

    def test_nonexistent_dirs(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"

        result = find_topic("anything", specs, archives)

        assert result == []

    def test_exact_match_takes_priority(self, tmp_path):
        """Exact match should be returned even when substring matches exist."""
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_dir(specs, "login")
        _make_dir(specs, "2026-05-20-14-30-feature-login")

        result = find_topic("login", specs, archives)

        assert len(result) == 1
        assert Path(result[0][0]).name == "login"

    def test_ignores_files(self, tmp_path):
        """Only directories should be matched, not files."""
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir(parents=True)
        (specs / "my-topic.txt").write_text("not a dir", encoding="utf-8")

        result = find_topic("my-topic", specs, archives)

        assert result == []


class TestOpenDirectory:
    """Tests for open_directory."""

    def test_darwin(self):
        with patch("open_topic.subprocess.run") as mock_run, patch(
            "open_topic.sys.platform", "darwin"
        ):
            open_directory("/some/path")

        mock_run.assert_called_once_with(["open", "/some/path"])

    def test_linux(self):
        with patch("open_topic.subprocess.run") as mock_run, patch(
            "open_topic.sys.platform", "linux"
        ):
            open_directory("/some/path")

        mock_run.assert_called_once_with(["xdg-open", "/some/path"])

    def test_win32(self):
        with patch("open_topic.sys.platform", "win32"), patch(
            "open_topic.os.startfile", create=True
        ) as mock_startfile:
            open_directory("C:\\some\\path")

        mock_startfile.assert_called_once_with("C:\\some\\path")


class TestMain:
    """Tests for the main() CLI entry point."""

    def test_no_topic_opens_spex_root(self, tmp_path):
        spex_root = str(tmp_path / "root")
        with patch.object(sys, "argv", ["open_topic.py"]), patch.object(
            open_topic, "get_spex_root", return_value=spex_root
        ), patch.object(open_topic, "open_directory") as mock_open:
            main()

        mock_open.assert_called_once_with(spex_root)

    def test_single_match_opens_dir(self, tmp_path):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        topic_dir = _make_dir(specs, "2026-05-20-14-30-my-topic")

        with patch.object(
            sys, "argv", ["open_topic.py", "my-topic"]
        ), patch.object(
            open_topic, "get_specs_dir", return_value=str(specs)
        ), patch.object(
            open_topic, "get_archives_dir", return_value=str(archives)
        ), patch.object(
            open_topic, "open_directory"
        ) as mock_open:
            main()

        mock_open.assert_called_once_with(str(topic_dir))

    def test_no_match_exits_with_error(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        specs.mkdir()

        with patch.object(
            sys, "argv", ["open_topic.py", "nonexistent"]
        ), patch.object(
            open_topic, "get_specs_dir", return_value=str(specs)
        ), patch.object(
            open_topic, "get_archives_dir", return_value=str(archives)
        ), pytest.raises(SystemExit, match="1"):
            main()

        err = capsys.readouterr().err
        assert "no topic matching 'nonexistent'" in err

    def test_multiple_matches_lists_and_exits(self, tmp_path, capsys):
        specs = tmp_path / "specs"
        archives = tmp_path / "archives"
        _make_dir(specs, "2026-05-20-14-30-edit-alpha")
        _make_dir(archives, "2026-05-20-14-30-edit-beta")

        with patch.object(
            sys, "argv", ["open_topic.py", "edit"]
        ), patch.object(
            open_topic, "get_specs_dir", return_value=str(specs)
        ), patch.object(
            open_topic, "get_archives_dir", return_value=str(archives)
        ), pytest.raises(SystemExit, match="1"):
            main()

        err = capsys.readouterr().err
        assert "Multiple topics match" in err
        assert "[specs]" in err
        assert "[archives]" in err
