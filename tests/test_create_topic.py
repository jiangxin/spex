"""Tests for create-topic-dir.py (direct import)."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
create_topic_dir = importlib.import_module("create-topic-dir")
create_topic = create_topic_dir.create_topic


class TestCreateTopic:
    def test_creates_directory(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        result = create_topic("2026-05-20-hello", specs_dir)

        assert result == specs_dir / "2026-05-20-hello"
        assert result.is_dir()

    def test_creates_specs_dir_if_missing(self, tmp_path):
        specs_dir = tmp_path / "specs"

        result = create_topic("2026-05-20-new-topic", specs_dir)

        assert specs_dir.is_dir()
        assert result.is_dir()

    def test_invalid_name_no_date(self, tmp_path):
        with pytest.raises(ValueError, match="invalid topic name"):
            create_topic("no-date-prefix", tmp_path)

    def test_invalid_name_uppercase(self, tmp_path):
        with pytest.raises(ValueError, match="invalid topic name"):
            create_topic("2026-05-20-UpperCase", tmp_path)

    def test_invalid_name_spaces(self, tmp_path):
        with pytest.raises(ValueError, match="invalid topic name"):
            create_topic("2026-05-20-has space", tmp_path)

    def test_exceeds_max_bytes(self, tmp_path):
        long_name = "2026-05-20-" + "a" * 60
        with pytest.raises(ValueError, match="exceeds 64 bytes"):
            create_topic(long_name, tmp_path)

    def test_already_exists(self, tmp_path):
        specs_dir = tmp_path / "specs"
        (specs_dir / "2026-05-20-existing").mkdir(parents=True)

        with pytest.raises(FileExistsError, match="already exists"):
            create_topic("2026-05-20-existing", specs_dir)

    def test_valid_name_with_numbers(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        result = create_topic("2026-01-01-add-v2-api", specs_dir)

        assert result.is_dir()
