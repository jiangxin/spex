"""Tests for meta.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import meta

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "meta.py")


def _make_topic(tmp_path, topic_name, data):
    """Create a topic directory with meta.json and return the meta path."""
    specs_dir = tmp_path / "specs"
    topic_dir = specs_dir / topic_name
    topic_dir.mkdir(parents=True)
    meta_path = topic_dir / "meta.json"
    meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return meta_path


def _run_script(tmp_path, topic_name, key, value=None):
    """Run meta.py as a subprocess with SPEX_ROOT pointing to tmp_path."""
    args = [sys.executable, SCRIPT, topic_name, key]
    if value is not None:
        args.append(value)
    env = {**subprocess.os.environ, "SPEX_ROOT": str(tmp_path)}
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        input="" if value is not None else None,
    )


class TestAppendToPrompts:
    """Verify that key='prompts' appends to the prompts array."""

    def test_append_to_existing_prompts(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": ["first"]})

        result = _run_script(tmp_path, "my-topic", "prompts", "second")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["prompts"] == ["first", "second"]

    def test_append_creates_prompts_array(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"title": "test"})

        result = _run_script(tmp_path, "my-topic", "prompts", "new prompt")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["prompts"] == ["new prompt"]

    def test_append_replaces_non_list_prompts(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": "not a list"})

        result = _run_script(tmp_path, "my-topic", "prompts", "value")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["prompts"] == ["value"]

    def test_stdout_contains_updated_json(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        result = _run_script(tmp_path, "my-topic", "prompts", "hello")

        output = json.loads(result.stdout)
        assert output["prompts"] == ["hello"]


class TestSetNonPromptsKey:
    """Verify that non-prompts keys are set directly."""

    def test_set_new_key(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {})

        result = _run_script(tmp_path, "my-topic", "title", "My Title")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["title"] == "My Title"

    def test_overwrite_existing_key(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"status": "draft"})

        result = _run_script(tmp_path, "my-topic", "status", "final")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["status"] == "final"

    def test_file_has_trailing_newline(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {})

        _run_script(tmp_path, "my-topic", "key", "val")

        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        content = meta_path.read_text(encoding="utf-8")
        assert content.endswith("\n")

    def test_ensure_ascii_false(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {})

        _run_script(tmp_path, "my-topic", "name", "中文测试")

        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        content = meta_path.read_text(encoding="utf-8")
        assert "中文测试" in content


class TestReadValueFromStdin:
    """Verify value is read from stdin when not provided as argument."""

    def test_read_from_stdin(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        env = {**subprocess.os.environ, "SPEX_ROOT": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, SCRIPT, "my-topic", "prompts"],
            capture_output=True,
            text=True,
            input="stdin value",
            env=env,
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["prompts"] == ["stdin value"]

    def test_read_key_from_stdin(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {})

        env = {**subprocess.os.environ, "SPEX_ROOT": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, SCRIPT, "my-topic", "branch"],
            capture_output=True,
            text=True,
            input="feature-x",
            env=env,
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["branch"] == "feature-x"


class TestErrorOnMissingTopic:
    """Verify error when topic does not exist."""

    def test_missing_topic_exits_1(self, tmp_path):
        (tmp_path / "specs").mkdir(parents=True)

        result = _run_script(tmp_path, "nonexistent", "key", "value")

        assert result.returncode == 1
        assert "file not found" in result.stderr

    def test_missing_topic_via_main(self, monkeypatch, tmp_path):
        (tmp_path / "specs").mkdir(parents=True)
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        monkeypatch.setattr(
            sys, "argv", ["prog", "nonexistent", "key", "val"]
        )

        with pytest.raises(SystemExit) as exc_info:
            meta.main()
        assert exc_info.value.code == 1


class TestErrorOnInsufficientArgs:
    """Verify error when arguments are insufficient."""

    def test_no_args_exits_1(self):
        result = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Usage" in result.stderr

    def test_one_arg_exits_1(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "my-topic"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Usage" in result.stderr

    def test_insufficient_args_via_main(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "my-topic"])

        with pytest.raises(SystemExit) as exc_info:
            meta.main()
        assert exc_info.value.code == 1
