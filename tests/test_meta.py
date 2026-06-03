"""Tests for meta.py."""

import json
import subprocess
import sys
from pathlib import Path

import meta
import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "meta.py")


def _make_topic(tmp_path, topic_name, data):
    """Create a topic directory with meta.json and return the meta path."""
    specs_dir = tmp_path / "specs"
    topic_dir = specs_dir / topic_name
    topic_dir.mkdir(parents=True)
    meta_path = topic_dir / "meta.json"
    meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return meta_path


def _setup_spex_toml(tmp_path):
    """Write .spex.toml so the subprocess resolves spex_root to tmp_path."""
    toml = tmp_path / ".spex.toml"
    if not toml.exists():
        toml.write_text(
            f'[spex]\nspex_root = "{tmp_path}"\n', encoding="utf-8"
        )


def _run_script(tmp_path, topic_name, key=None, value=None, stdin_flag=False,
                input_data=None, add_images=None):
    """Run meta.py as a subprocess with .spex.toml pointing to tmp_path."""
    _setup_spex_toml(tmp_path)
    args = [sys.executable, SCRIPT, topic_name]
    if key is not None:
        args.append(key)
    if value is not None:
        args.append(value)
    if stdin_flag:
        args.append("--stdin")
    if add_images:
        args.append("--add-images")
        args.extend(add_images)
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        input=input_data,
    )


class TestAppendToPrompts:
    """Verify that key='prompts' appends {text, timestamp} structs."""

    def test_append_to_existing_prompts(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": ["first"]})

        result = _run_script(tmp_path, "my-topic", "prompts", "second")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 2
        assert data["prompts"][0] == "first"
        entry = data["prompts"][1]
        assert isinstance(entry, dict)
        assert entry["text"] == "second"
        assert "timestamp" in entry

    def test_append_creates_prompts_array(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"title": "test"})

        result = _run_script(tmp_path, "my-topic", "prompts", "new prompt")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 1
        entry = data["prompts"][0]
        assert isinstance(entry, dict)
        assert entry["text"] == "new prompt"
        assert "timestamp" in entry

    def test_append_replaces_non_list_prompts(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": "not a list"})

        result = _run_script(tmp_path, "my-topic", "prompts", "value")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 1
        entry = data["prompts"][0]
        assert isinstance(entry, dict)
        assert entry["text"] == "value"
        assert "timestamp" in entry

    def test_stdout_contains_updated_json(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        result = _run_script(tmp_path, "my-topic", "prompts", "hello")

        output = json.loads(result.stdout)
        assert len(output["prompts"]) == 1
        entry = output["prompts"][0]
        assert isinstance(entry, dict)
        assert entry["text"] == "hello"
        assert "timestamp" in entry

    def test_append_via_stdin(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        result = _run_script(tmp_path, "my-topic", "prompts",
                             stdin_flag=True, input_data="stdin prompt")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 1
        entry = data["prompts"][0]
        assert isinstance(entry, dict)
        assert entry["text"] == "stdin prompt"
        assert "timestamp" in entry


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
    """Verify value is read from stdin when --stdin flag is used."""

    def test_read_from_stdin(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        result = _run_script(tmp_path, "my-topic", "prompts",
                             stdin_flag=True, input_data="stdin value")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 1
        entry = data["prompts"][0]
        assert isinstance(entry, dict)
        assert entry["text"] == "stdin value"
        assert "timestamp" in entry

    def test_read_key_from_stdin(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {})

        result = _run_script(tmp_path, "my-topic", "branch",
                             stdin_flag=True, input_data="feature-x")

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
        assert "no topic matching" in result.stderr

    def test_missing_topic_via_main(self, monkeypatch, tmp_path):
        from config import ProjectContext
        (tmp_path / "specs").mkdir(parents=True)
        ctx = ProjectContext(
            cwd=tmp_path,
            top_workdir=None,
            main_worktree=None,
            remote_url="",
            branch="",
            user_name="",
            user_email="",
            spex_tomls=[],
            config={},
            spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)
        from common import clear_spex_root_cache
        clear_spex_root_cache()

        with pytest.raises(SystemExit) as exc_info:
            meta.main(["nonexistent", "key", "val"])
        assert exc_info.value.code == 1


class TestErrorOnInsufficientArgs:
    """Verify error when arguments are insufficient."""

    def test_no_args_exits_2(self):
        result = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2

    def test_no_args_via_main(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])

        with pytest.raises(SystemExit) as exc_info:
            meta.main()
        assert exc_info.value.code == 2


class TestGetMode:
    """Verify get mode displays meta contents."""

    def test_get_all_keys(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {
            "topic": "my-topic",
            "branch": "main",
        })

        result = _run_script(tmp_path, "my-topic")

        assert result.returncode == 0
        assert "topic: my-topic" in result.stdout
        assert "branch: main" in result.stdout

    def test_get_single_key(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"branch": "feature-x"})

        result = _run_script(tmp_path, "my-topic", "branch")

        assert result.returncode == 0
        assert result.stdout.strip() == "feature-x"

    def test_get_missing_key_exits_1(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"branch": "main"})

        result = _run_script(tmp_path, "my-topic", "nonexistent")

        assert result.returncode == 1
        assert "not found" in result.stderr

    def test_get_list_key(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {"prompts": ["first", "second"]})

        result = _run_script(tmp_path, "my-topic", "prompts")

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == ["first", "second"]

    def test_get_all_with_list(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {
            "topic": "test",
            "prompts": ["hello"],
        })

        result = _run_script(tmp_path, "my-topic")

        assert result.returncode == 0
        assert "topic: test" in result.stdout
        assert "prompts:" in result.stdout
        assert "- hello" in result.stdout


class TestSetKeyKnownFields:
    """Verify that known TopicMeta fields use setattr, not extras."""

    def test_set_known_field_branch(self, tmp_path):
        """Setting a known field updates it via setattr."""
        _make_topic(tmp_path, "my-topic", {
            "topic": "my-topic",
            "branch": "old-branch",
        })

        result = _run_script(tmp_path, "my-topic", "branch", "new-branch")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["branch"] == "new-branch"

    def test_set_unknown_field_goes_to_extras(self, tmp_path):
        """Setting an unknown field stores it (appears in output JSON)."""
        _make_topic(tmp_path, "my-topic", {"topic": "my-topic"})

        result = _run_script(
            tmp_path, "my-topic", "custom_flag", "enabled",
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["custom_flag"] == "enabled"

    def test_set_preserves_field_order(self, tmp_path):
        """Known fields appear in canonical order after set."""
        _make_topic(tmp_path, "my-topic", {
            "topic": "my-topic",
            "workdir": "/work",
            "main_worktree": "/work",
            "remote_url": "",
            "branch": "main",
            "user_name": "Dev",
            "user_email": "dev@example.com",
            "created_at": "2026-01-01T00:00:00+00:00",
            "prompts": [],
            "description": "A test topic",
        })

        result = _run_script(
            tmp_path, "my-topic", "branch", "feature-x",
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        keys = list(output.keys())
        assert keys.index("branch") < keys.index("prompts")
        assert keys.index("topic") < keys.index("branch")
        assert output["branch"] == "feature-x"

    def test_roundtrip_preserves_json_format(self, tmp_path):
        """Write-then-read roundtrip preserves all fields."""
        original = {
            "topic": "rt-topic",
            "workdir": "/work",
            "main_worktree": "/work",
            "remote_url": "git@example.com:repo.git",
            "branch": "main",
            "user_name": "Dev",
            "user_email": "dev@example.com",
            "created_at": "2026-01-01T00:00:00+00:00",
            "prompts": ["initial"],
            "description": "A description",
            "spex_branch": "spex/rt-topic",
        }
        _make_topic(tmp_path, "rt-topic", original)

        result = _run_script(
            tmp_path, "rt-topic", "user_name", "NewDev",
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "rt-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["user_name"] == "NewDev"
        assert data["topic"] == "rt-topic"
        assert data["description"] == "A description"
        assert data["spex_branch"] == "spex/rt-topic"
        assert data["prompts"] == ["initial"]


class TestAddImages:
    """Verify --add-images flag behavior for prompts key."""

    def test_text_with_add_images(self, tmp_path):
        """text + --add-images creates prompt entry with images."""
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        result = _run_script(
            tmp_path, "my-topic", "prompts", "new prompt",
            add_images=["img1.png", "img2.png"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 1
        entry = data["prompts"][0]
        assert entry["text"] == "new prompt"
        assert "timestamp" in entry
        assert entry["images"] == ["img1.png", "img2.png"]

    def test_only_add_images_appends_to_last(self, tmp_path):
        """--add-images without text appends images to last entry."""
        _make_topic(tmp_path, "my-topic", {
            "prompts": [
                {"text": "existing", "timestamp": "2026-01-01T00:00:00"},
            ],
        })

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            add_images=["new-img.png"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 1
        entry = data["prompts"][0]
        assert entry["text"] == "existing"
        assert entry["images"] == ["new-img.png"]

    def test_only_add_images_no_prompts_errors(self, tmp_path):
        """--add-images with no existing prompts exits with error."""
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            add_images=["img.png"],
        )

        assert result.returncode == 1
        assert "no prompt entries" in result.stderr

    def test_add_images_deduplication(self, tmp_path):
        """--add-images deduplicates image paths."""
        _make_topic(tmp_path, "my-topic", {
            "prompts": [
                {
                    "text": "prompt",
                    "timestamp": "2026-01-01T00:00:00",
                    "images": ["existing.png"],
                },
            ],
        })

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            add_images=["existing.png", "new.png"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["prompts"][0]["images"] == ["existing.png", "new.png"]

    def test_add_images_normalizes_old_format(self, tmp_path):
        """--add-images normalizes old plain-string prompt format."""
        _make_topic(tmp_path, "my-topic", {
            "prompts": ["plain string prompt"],
        })

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            add_images=["photo.jpg"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        entry = data["prompts"][0]
        assert entry["text"] == "plain string prompt"
        assert entry["images"] == ["photo.jpg"]

    def test_stdin_with_add_images(self, tmp_path):
        """stdin text + --add-images creates prompt entry with images."""
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            stdin_flag=True, input_data="stdin prompt",
            add_images=["screenshot.png"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(data["prompts"]) == 1
        entry = data["prompts"][0]
        assert entry["text"] == "stdin prompt"
        assert entry["images"] == ["screenshot.png"]
