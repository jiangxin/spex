"""Tests for write-log.py (direct import)."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
write_log_mod = importlib.import_module("write-log")
write_log = write_log_mod.write_log
format_prompt = write_log_mod.format_prompt


class TestWriteLog:
    def test_creates_log_file(self, tmp_path):
        topic_dir = tmp_path / "2026-05-20-test"
        topic_dir.mkdir()

        result = write_log(
            "2026-05-20-test", "hello world", tmp_path,
            timestamp="2026-05-20T10:00:00+08:00",
        )

        assert result == topic_dir / "prompt.log"
        assert result.is_file()

    def test_log_content_format(self, tmp_path):
        topic_dir = tmp_path / "2026-05-20-test"
        topic_dir.mkdir()

        write_log(
            "2026-05-20-test", "my prompt", tmp_path,
            timestamp="2026-05-20T10:00:00+08:00",
        )

        content = (topic_dir / "prompt.log").read_text()
        assert "**[2026-05-20T10:00:00+08:00]**" in content
        assert "```prompt" in content
        assert "    my prompt" in content

    def test_appends_to_existing_log(self, tmp_path):
        topic_dir = tmp_path / "2026-05-20-test"
        topic_dir.mkdir()

        write_log("2026-05-20-test", "first", tmp_path, timestamp="T1")
        write_log("2026-05-20-test", "second", tmp_path, timestamp="T2")

        content = (topic_dir / "prompt.log").read_text()
        assert "**[T1]**" in content
        assert "**[T2]**" in content

    def test_topic_dir_not_exist(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="does not exist"):
            write_log("2026-05-20-missing", "hello", tmp_path)

    def test_empty_content(self, tmp_path):
        topic_dir = tmp_path / "2026-05-20-test"
        topic_dir.mkdir()

        with pytest.raises(ValueError, match="no input provided"):
            write_log("2026-05-20-test", "", tmp_path)

    def test_whitespace_only_content(self, tmp_path):
        topic_dir = tmp_path / "2026-05-20-test"
        topic_dir.mkdir()

        with pytest.raises(ValueError, match="no input provided"):
            write_log("2026-05-20-test", "   ", tmp_path)


class TestFormatPrompt:
    def test_basic_indent(self):
        result = format_prompt("hello")
        assert result == "    hello"

    def test_multiline(self):
        result = format_prompt("line1\nline2")
        assert result == "    line1\n    line2"

    def test_wraps_long_line(self):
        long_text = "word " * 20
        result = format_prompt(long_text.strip(), width=30)
        lines = result.split("\n")
        assert len(lines) > 1

    def test_cjk_characters(self):
        cjk = "中文测试" * 10
        result = format_prompt(cjk, width=20)
        lines = result.split("\n")
        assert len(lines) > 1
