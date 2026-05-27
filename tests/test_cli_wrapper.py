"""Tests for cli.py — ArgumentParser wrapper."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from cli import ArgumentParser


class TestArgumentParser:
    def test_parse_defaults_to_sys_argv(self, monkeypatch):
        """parse() with no args should use sys.argv[1:]."""
        monkeypatch.setattr(
            sys, "argv", ["cli.py", "--verbose", "input.txt"]
        )
        parser = ArgumentParser()
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("input_file")

        args = parser.parse()

        assert args.verbose is True
        assert args.input_file == "input.txt"

    def test_parse_with_explicit_argv(self):
        """parse(argv) should use the provided list."""
        parser = ArgumentParser()
        parser.add_argument("--count", type=int)
        parser.add_argument("name")

        args = parser.parse(["--count", "3", "alice"])

        assert args.count == 3
        assert args.name == "alice"

    def test_parse_known(self):
        """parse_known should return (args, remaining)."""
        parser = ArgumentParser()
        parser.add_argument("--verbose", action="store_true")

        args, remaining = parser.parse_known(
            ["--verbose", "--unknown", "extra"]
        )

        assert args.verbose is True
        assert remaining == ["--unknown", "extra"]

    def test_parse_known_with_explicit_argv(self):
        """parse_known(argv) should use the provided list."""
        parser = ArgumentParser()
        parser.add_argument("-f", "--flag", action="store_true")

        args, remaining = parser.parse_known(
            ["-f", "positional"]
        )

        assert args.flag is True
        assert remaining == ["positional"]

    def test_help_output(self, capsys):
        """--help should print usage and exit 0."""
        parser = ArgumentParser(prog="spex test")
        parser.add_argument("--verbose", action="store_true")

        try:
            parser.parse(["--help"])
        except SystemExit as e:
            assert e.code == 0

        out = capsys.readouterr().out
        assert "spex test" in out
        assert "--verbose" in out

    def test_error_exits_with_code_2(self, capsys):
        """Invalid arguments should exit with code 2."""
        parser = ArgumentParser(prog="spex test")
        parser.add_argument("required_arg")

        try:
            parser.parse([])
        except SystemExit as e:
            assert e.code == 2

    def test_short_and_long_flags(self):
        """Both short (-v) and long (--verbose) flags should work."""
        parser = ArgumentParser()
        parser.add_argument("-v", "--verbose", action="store_true")

        args = parser.parse(["-v"])
        assert args.verbose is True

        args = parser.parse(["--verbose"])
        assert args.verbose is True

    def test_positional_and_flag_order_independent(self):
        """Positional and flag order should not matter."""
        parser = ArgumentParser()
        parser.add_argument("input_file")
        parser.add_argument("--flag", action="store_true")

        args = parser.parse(["--flag", "input.txt"])
        assert args.flag is True
        assert args.input_file == "input.txt"

        args = parser.parse(["input.txt", "--flag"])
        assert args.flag is True
        assert args.input_file == "input.txt"

    def test_default_values(self):
        """Default values should be respected."""
        parser = ArgumentParser()
        parser.add_argument("--count", type=int, default=10)
        parser.add_argument("name", default="unnamed")

        args = parser.parse(["alice"])
        assert args.count == 10
        assert args.name == "alice"
