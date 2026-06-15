import sys
from unittest.mock import MagicMock, patch

import open as spex_open  # noqa: A004
import pytest
from open import main, open_directory, run_in_directory  # noqa: A004


class TestOpenDirectory:
    """Tests for open_directory."""

    def test_darwin(self):
        with patch("open.subprocess.run") as mock_run, patch(
            "open.sys.platform", "darwin"
        ):
            open_directory("/some/path")

        mock_run.assert_called_once_with(["open", "/some/path"])

    def test_linux(self):
        with patch("open.subprocess.run") as mock_run, patch(
            "open.sys.platform", "linux"
        ):
            open_directory("/some/path")

        mock_run.assert_called_once_with(["xdg-open", "/some/path"])

    def test_win32(self):
        with patch("open.sys.platform", "win32"), patch(
            "open.os.startfile", create=True
        ) as mock_startfile:
            open_directory("C:\\some\\path")

        mock_startfile.assert_called_once_with("C:\\some\\path")


class TestMain:
    """Tests for the main() CLI entry point."""

    def test_has_topic_specs_found(self, tmp_path):
        """When topic arg is given and found in specs, opens the directory."""
        topic_dir = tmp_path / "specs" / "2026-05-20-14-30-my-topic"
        topic_dir.mkdir(parents=True)

        with patch.object(sys, "argv", ["open.py", "my-topic"]), patch.object(
            spex_open, "resolve_spec", return_value=topic_dir
        ) as mock_resolve, patch.object(
            spex_open, "open_directory"
        ) as mock_open:
            main()

        mock_resolve.assert_called_once_with("my-topic", include_archives=False)
        mock_open.assert_called_once_with(str(topic_dir))

    def test_has_topic_not_found_suggests_archives(self, capsys):
        """When topic arg is given but not found, resolve_spec exits with hint."""
        # resolve_spec itself prints error and exits; verify the integration
        def fake_resolve(name, include_archives=False):
            print(f"Error: no topic matching '{name}' found.", file=sys.stderr)
            if not include_archives:
                print(
                    "Hint: try --archives to search archived topics.",
                    file=sys.stderr,
                )
            sys.exit(1)

        with patch.object(
            sys, "argv", ["open.py", "nonexistent"]
        ), patch.object(
            spex_open, "resolve_spec", side_effect=fake_resolve
        ), pytest.raises(SystemExit, match="1"):
            main()

        err = capsys.readouterr().err
        assert "no topic matching 'nonexistent'" in err
        assert "--archives" in err

    def test_no_topic_has_topics_interactive(self, tmp_path):
        """When no topic arg and topics exist, interactive selection opens topic."""
        selected_dir = tmp_path / "specs" / "2026-05-20-14-30-feature"
        selected_dir.mkdir(parents=True)

        with patch.object(sys, "argv", ["open.py"]), patch.object(
            spex_open, "select_spec_interactive", return_value=selected_dir
        ) as mock_select, patch.object(
            spex_open, "open_directory"
        ) as mock_open:
            main()

        mock_select.assert_called_once_with(
            include_archives=False, all_projects=False, allow_empty=True
        )
        mock_open.assert_called_once_with(str(selected_dir))

    def test_no_topic_no_topics_opens_spex_root(self, tmp_path):
        """When no topic arg and no topics found, opens spex_root."""
        spex_root = str(tmp_path / "root")

        with patch.object(sys, "argv", ["open.py"]), patch.object(
            spex_open, "select_spec_interactive", return_value=None
        ), patch.object(
            spex_open, "get_spex_root", return_value=spex_root
        ), patch.object(
            spex_open, "open_directory"
        ) as mock_open:
            main()

        mock_open.assert_called_once_with(spex_root)

    def test_no_topic_user_empty_input_opens_spex_root(self, tmp_path):
        """When no topic arg and user enters empty input, opens spex_root."""
        spex_root = str(tmp_path / "root")

        # select_spec_interactive returns None when allow_empty=True and
        # user enters empty input
        with patch.object(sys, "argv", ["open.py"]), patch.object(
            spex_open, "select_spec_interactive", return_value=None
        ), patch.object(
            spex_open, "get_spex_root", return_value=spex_root
        ), patch.object(
            spex_open, "open_directory"
        ) as mock_open:
            main()

        mock_open.assert_called_once_with(spex_root)

    def test_archives_flag_passed_with_topic(self, tmp_path):
        """--archives flag is forwarded to resolve_spec."""
        topic_dir = tmp_path / "archives" / "2026-05-20-14-30-old-topic"
        topic_dir.mkdir(parents=True)

        with patch.object(
            sys, "argv", ["open.py", "--archives", "old-topic"]
        ), patch.object(
            spex_open, "resolve_spec", return_value=topic_dir
        ) as mock_resolve, patch.object(
            spex_open, "open_directory"
        ):
            main()

        mock_resolve.assert_called_once_with("old-topic", include_archives=True)

    def test_all_projects_flag_passed_without_topic(self, tmp_path):
        """--all-projects flag is forwarded to select_spec_interactive."""
        selected_dir = tmp_path / "specs" / "2026-05-20-14-30-feature"
        selected_dir.mkdir(parents=True)

        with patch.object(
            sys, "argv", ["open.py", "--all-projects"]
        ), patch.object(
            spex_open, "select_spec_interactive", return_value=selected_dir
        ) as mock_select, patch.object(
            spex_open, "open_directory"
        ):
            main()

        mock_select.assert_called_once_with(
            include_archives=False, all_projects=True, allow_empty=True
        )


class TestRunInDirectory:
    """Tests for run_in_directory."""

    def test_runs_command_in_directory(self, tmp_path):
        """run_in_directory calls subprocess.run with shell=True and cwd."""
        mock_result = MagicMock(returncode=0)
        with patch("open.subprocess.run", return_value=mock_result) as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                run_in_directory(str(tmp_path), "ls -la")

        mock_run.assert_called_once_with("ls -la", shell=True, cwd=str(tmp_path))
        assert exc_info.value.code == 0

    def test_propagates_nonzero_exit_code(self, tmp_path):
        """run_in_directory propagates non-zero exit codes via sys.exit."""
        mock_result = MagicMock(returncode=42)
        with patch("open.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                run_in_directory(str(tmp_path), "false")

        assert exc_info.value.code == 42


class TestRunOption:
    """Tests for the --run option in main()."""

    def test_no_run_with_topic_calls_open_directory(self, tmp_path):
        """No --run + has topic calls open_directory (existing behavior)."""
        topic_dir = tmp_path / "specs" / "2026-05-20-14-30-my-topic"
        topic_dir.mkdir(parents=True)

        with patch.object(sys, "argv", ["open.py", "my-topic"]), patch.object(
            spex_open, "resolve_spec", return_value=topic_dir
        ), patch.object(spex_open, "open_directory") as mock_open:
            main()

        mock_open.assert_called_once_with(str(topic_dir))

    def test_run_without_value_calls_open_directory(self, tmp_path):
        """--run without value + has topic calls open_directory."""
        topic_dir = tmp_path / "specs" / "2026-05-20-14-30-my-topic"
        topic_dir.mkdir(parents=True)

        with patch.object(
            sys, "argv", ["open.py", "my-topic", "--run"]
        ), patch.object(
            spex_open, "resolve_spec", return_value=topic_dir
        ), patch.object(spex_open, "open_directory") as mock_open:
            main()

        mock_open.assert_called_once_with(str(topic_dir))

    def test_run_with_command_calls_subprocess(self, tmp_path):
        """--run "ls" + has topic calls subprocess.run in topic dir."""
        topic_dir = tmp_path / "specs" / "2026-05-20-14-30-my-topic"
        topic_dir.mkdir(parents=True)

        mock_result = MagicMock(returncode=0)
        with patch.object(
            sys, "argv", ["open.py", "--run", "ls", "my-topic"]
        ), patch.object(
            spex_open, "resolve_spec", return_value=topic_dir
        ), patch("open.subprocess.run", return_value=mock_result) as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                main()

        mock_run.assert_called_once_with("ls", shell=True, cwd=str(topic_dir))
        assert exc_info.value.code == 0

    def test_run_no_topic_no_topics_runs_in_spex_root(self, tmp_path):
        """--run "ls" + no topic + no topics runs in spex_root."""
        spex_root = str(tmp_path / "root")

        mock_result = MagicMock(returncode=0)
        with patch.object(
            sys, "argv", ["open.py", "--run", "ls"]
        ), patch.object(
            spex_open, "select_spec_interactive", return_value=None
        ), patch.object(
            spex_open, "get_spex_root", return_value=spex_root
        ), patch("open.subprocess.run", return_value=mock_result) as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                main()

        mock_run.assert_called_once_with("ls", shell=True, cwd=spex_root)
        assert exc_info.value.code == 0

    def test_run_command_nonzero_exit_propagates(self, tmp_path):
        """--run command returns non-zero exit code, sys.exit propagates it."""
        topic_dir = tmp_path / "specs" / "2026-05-20-14-30-my-topic"
        topic_dir.mkdir(parents=True)

        mock_result = MagicMock(returncode=7)
        with patch.object(
            sys, "argv", ["open.py", "--run", "bad-cmd", "my-topic"]
        ), patch.object(
            spex_open, "resolve_spec", return_value=topic_dir
        ), patch("open.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 7
