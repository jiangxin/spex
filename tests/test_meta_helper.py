"""Tests for meta_helper.py."""

import json
import subprocess
import sys
from pathlib import Path

import meta_helper
import pytest

SCRIPT = str(
    Path(__file__).resolve().parent.parent
    / "skills" / "spex" / "scripts" / "meta_helper.py"
)


def _make_topic(tmp_path, spec_name, data):
    """Create a spec directory with meta.json and return the meta path."""
    specs_dir = tmp_path / "specs"
    spec_dir = specs_dir / spec_name
    spec_dir.mkdir(parents=True)
    meta_path = spec_dir / "meta.json"
    meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return meta_path


def _setup_spex_toml(tmp_path):
    """Write .spex.toml so the subprocess resolves spex_root to tmp_path."""
    toml = tmp_path / ".spex.toml"
    if not toml.exists():
        toml.write_text(
            f'[spex]\nspex_root = "{tmp_path}"\n', encoding="utf-8"
        )


def _run_script(tmp_path, spec_name, key=None, value=None, stdin_flag=False,
                input_data=None, add_images=None):
    """Run meta_helper.py as subprocess with .spex.toml pointing to tmp_path."""
    _setup_spex_toml(tmp_path)
    args = [sys.executable, SCRIPT, spec_name]
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


def _make_meta(tmp_path, spec_name, data):
    """Create a spec directory with meta.json, return (spec_dir, meta_path)."""
    specs_dir = tmp_path / "specs"
    spec_dir = specs_dir / spec_name
    spec_dir.mkdir(parents=True)
    meta_path = spec_dir / "meta.json"
    meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return spec_dir, meta_path


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
    """Verify error when spec does not exist."""

    def test_missing_spec_exits_1(self, tmp_path):
        (tmp_path / "specs").mkdir(parents=True)

        result = _run_script(tmp_path, "nonexistent", "key", "value")

        assert result.returncode == 1
        assert "no spec matching" in result.stderr

    def test_missing_spec_via_main(self, monkeypatch, tmp_path):
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
            meta_helper.main(["nonexistent", "key", "val"])
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
            meta_helper.main()
        assert exc_info.value.code == 2


class TestGetMode:
    """Verify get mode displays meta contents."""

    def test_get_all_keys(self, tmp_path):
        _make_topic(tmp_path, "my-topic", {
            "name": "my-topic",
            "branch": "main",
        })

        result = _run_script(tmp_path, "my-topic")

        assert result.returncode == 0
        assert "name: my-topic" in result.stdout
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
            "name": "test",
            "prompts": ["hello"],
        })

        result = _run_script(tmp_path, "my-topic")

        assert result.returncode == 0
        assert "name: test" in result.stdout
        assert "prompts:" in result.stdout
        assert "- hello" in result.stdout


class TestSetKeyKnownFields:
    """Verify that known SpecMeta fields use setattr, not extras."""

    def test_set_known_field_branch(self, tmp_path):
        """Setting a known field updates it via setattr."""
        _make_topic(tmp_path, "my-topic", {
            "name": "my-topic",
            "branch": "old-branch",
        })

        result = _run_script(tmp_path, "my-topic", "branch", "new-branch")

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["branch"] == "new-branch"

    def test_set_unknown_field_goes_to_extras(self, tmp_path):
        """Setting an unknown field stores it (appears in output JSON)."""
        _make_topic(tmp_path, "my-topic", {"name": "my-topic"})

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
            "name": "my-topic",
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
        assert keys.index("name") < keys.index("branch")
        assert output["branch"] == "feature-x"

    def test_roundtrip_preserves_json_format(self, tmp_path):
        """Write-then-read roundtrip preserves all fields."""
        original = {
            "name": "rt-topic",
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
        assert data["name"] == "rt-topic"
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


class TestFormatValue:
    """Test _format_value for list formatting paths (lines 31-43)."""

    def test_list_with_simple_items(self, tmp_path):
        """List of strings formats as bullet items."""
        _make_topic(tmp_path, "my-topic", {"tags": ["alpha", "beta"]})

        result = _run_script(tmp_path, "my-topic")

        assert result.returncode == 0
        assert "tags:" in result.stdout
        assert "- alpha" in result.stdout
        assert "- beta" in result.stdout

    def test_list_with_dict_items(self, tmp_path):
        """List of dicts formats each key-value pair (lines 34-39)."""
        _make_topic(tmp_path, "my-topic", {
            "prompts": [
                {"text": "hello", "timestamp": "2026-01-01T00:00:00"},
            ],
        })

        result = _run_script(tmp_path, "my-topic")

        assert result.returncode == 0
        assert "prompts:" in result.stdout
        assert "- text: hello" in result.stdout
        assert "  timestamp: 2026-01-01T00:00:00" in result.stdout

    def test_list_with_mixed_dict_and_string_items(self, tmp_path):
        """Mixed list renders both formats correctly."""
        _make_topic(tmp_path, "my-topic", {
            "prompts": [
                "plain-string-prompt",
                {"text": "structured", "timestamp": "2026-02-02"},
            ],
        })

        result = _run_script(tmp_path, "my-topic")

        assert result.returncode == 0
        assert "- plain-string-prompt" in result.stdout
        assert "- text: structured" in result.stdout
        assert "  timestamp: 2026-02-02" in result.stdout


class TestDisplayKeyEdgeCases:
    """Test _display_key edge cases (lines 54-61)."""

    def test_get_dict_value_as_json(self, tmp_path):
        """Dict values are displayed as pretty JSON."""
        _make_topic(tmp_path, "my-topic", {
            "settings": {"auto_save": True, "theme": "dark"},
        })

        result = _run_script(tmp_path, "my-topic", "settings")

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {"auto_save": True, "theme": "dark"}

    def test_get_nested_list_value(self, tmp_path):
        """Nested list values displayed as JSON (covers isinstance list path)."""
        _make_topic(tmp_path, "my-topic", {
            "steps": [["build", "test"], ["deploy"]],
        })

        result = _run_script(tmp_path, "my-topic", "steps")

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == [["build", "test"], ["deploy"]]


class TestAddImagesEdgeCases:
    """Test _add_images_only edge cases (lines 66-81)."""

    def test_add_images_to_entry_without_images_key(self, tmp_path):
        """Adds images to last prompt that has no images field (line 72)."""
        _make_topic(tmp_path, "my-topic", {
            "prompts": [
                {"text": "prompt without images", "timestamp": "2026-01-01"},
            ],
        })

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            add_images=["photo.png"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["prompts"][0]["images"] == ["photo.png"]

    def test_add_images_with_multiple_existing(self, tmp_path):
        """Adds multiple images when several already exist."""
        _make_topic(tmp_path, "my-topic", {
            "prompts": [
                {
                    "text": "prompt",
                    "timestamp": "2026-01-01",
                    "images": ["a.png", "b.png"],
                },
            ],
        })

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            add_images=["b.png", "c.png", "d.png"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        # b.png is deduplicated, c.png and d.png are new
        assert data["prompts"][0]["images"] == ["a.png", "b.png", "c.png", "d.png"]

    def test_add_images_only_preserves_text(self, tmp_path):
        """Only adding images preserves existing text and timestamp."""
        _make_topic(tmp_path, "my-topic", {
            "prompts": [
                {"text": "keep this", "timestamp": "2026-01-01T00:00:00+00:00"},
            ],
        })

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            add_images=["only-image.png"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        entry = data["prompts"][0]
        assert entry["text"] == "keep this"
        assert entry["timestamp"] == "2026-01-01T00:00:00+00:00"
        assert entry["images"] == ["only-image.png"]


class TestSetKeyWithImages:
    """Test _set_key with images parameter (lines 86-104)."""

    def test_set_prompts_with_images_via_stdin(self, tmp_path):
        """stdin + prompts key + add_images creates entry with both."""
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            stdin_flag=True,
            input_data="multi-line\nstdin\nprompt",
            add_images=["img.png"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        entry = data["prompts"][0]
        assert "multi-line" in entry["text"]
        assert entry["images"] == ["img.png"]

    def test_set_extras_field_via_unknown_key(self, tmp_path):
        """Unknown key goes into extras (covers meta.extras path in _set_key)."""
        _make_topic(tmp_path, "my-topic", {"name": "my-topic"})

        result = _run_script(
            tmp_path, "my-topic", "my_custom_field", "custom-value",
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["my_custom_field"] == "custom-value"

    def test_set_known_field_description(self, tmp_path):
        """Setting description updates via setattr on known field."""
        _make_topic(tmp_path, "my-topic", {
            "name": "my-topic",
            "description": "old desc",
        })

        result = _run_script(
            tmp_path, "my-topic", "description", "new desc",
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["description"] == "new desc"


class TestMainErrorPaths:
    """Test main() error handling (lines 156-186)."""

    def test_invalid_json_in_meta_exits_1(self, tmp_path):
        """meta.json with invalid JSON exits with error."""
        specs_dir = tmp_path / "specs"
        spec_dir = specs_dir / "bad-json"
        spec_dir.mkdir(parents=True)
        meta_path = spec_dir / "meta.json"
        meta_path.write_text("{not valid json}", encoding="utf-8")
        _setup_spex_toml(tmp_path)

        result = _run_script(tmp_path, "bad-json")

        assert result.returncode == 1
        assert "invalid JSON" in result.stderr

    def test_missing_meta_file_exits_1(self, tmp_path):
        """Spec directory without meta.json exits with error."""
        specs_dir = tmp_path / "specs"
        spec_dir = specs_dir / "no-meta"
        spec_dir.mkdir(parents=True)
        _setup_spex_toml(tmp_path)

        result = _run_script(tmp_path, "no-meta")

        assert result.returncode == 1
        assert "file not found" in result.stderr

    def test_main_via_direct_call_no_args_exits_2(self, monkeypatch):
        """main() with no arguments exits 2 (covers arg parsing error)."""
        monkeypatch.setattr(sys, "argv", ["prog"])
        with pytest.raises(SystemExit) as exc_info:
            meta_helper.main()
        assert exc_info.value.code == 2


class TestMainStdinWithPathSet:
    """Test main() stdin routing (lines 177-182)."""

    def test_stdin_set_non_prompts_key(self, tmp_path):
        """stdin with a non-prompts key uses _set_key directly."""
        _make_topic(tmp_path, "my-topic", {"description": "old"})

        result = _run_script(
            tmp_path, "my-topic", "description",
            stdin_flag=True,
            input_data="new description from stdin",
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["description"] == "new description from stdin"

    def test_stdin_prompts_key_with_images(self, tmp_path):
        """stdin + prompts + add_images routes to _set_key with images."""
        _make_topic(tmp_path, "my-topic", {"prompts": []})

        result = _run_script(
            tmp_path, "my-topic", "prompts",
            stdin_flag=True,
            input_data="stdin text with images",
            add_images=["photo.jpg"],
        )

        assert result.returncode == 0
        meta_path = tmp_path / "specs" / "my-topic" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        entry = data["prompts"][0]
        assert entry["text"] == "stdin text with images"
        assert entry["images"] == ["photo.jpg"]


class TestModuleMain:
    """Test if __name__ == '__main__' path (lines 190-192)."""

    def test_direct_script_execution_help(self, tmp_path):
        """Running meta_helper.py directly shows usage on no args."""
        result = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "meta-helper" in result.stderr


class TestDirectImportInternal:
    """Direct-import tests for internal functions to achieve coverage."""

    def test_format_value_list_with_dict_items(self, tmp_path):
        """_format_value formats list of dicts (covers lines 34-39)."""
        _make_meta(tmp_path, "t1", {"prompts": []})

        result = meta_helper._format_value(
            "prompts",
            [{"text": "hello", "timestamp": "2026-01-01"}],
        )
        assert "- text: hello" in result
        assert "  timestamp: 2026-01-01" in result

    def test_format_value_list_with_simple_items(self, tmp_path):
        """_format_value formats list of strings (covers line 41)."""
        result = meta_helper._format_value("tags", ["a", "b"])
        assert "- a" in result
        assert "- b" in result

    def test_format_value_scalar(self, tmp_path):
        """_format_value formats simple value (covers line 43)."""
        result = meta_helper._format_value("name", "my-topic")
        assert result == "name: my-topic"

    def test_display_all(self, capsys, tmp_path):
        """_display_all iterates all keys (covers lines 48-49)."""
        data = {"name": "test", "branch": "main"}
        meta_helper._display_all(data)
        out = capsys.readouterr().out
        assert "name: test" in out
        assert "branch: main" in out

    def test_display_key_simple(self, capsys, tmp_path):
        """_display_key prints scalar value (covers line 61)."""
        data = {"branch": "feature-x"}
        meta_helper._display_key(data, "branch")
        assert capsys.readouterr().out.strip() == "feature-x"

    def test_display_key_dict(self, capsys, tmp_path):
        """_display_key dumps dict as JSON (covers line 59)."""
        data = {"settings": {"key": "val"}}
        meta_helper._display_key(data, "settings")
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed == {"key": "val"}

    def test_display_key_list(self, capsys, tmp_path):
        """_display_key dumps list as JSON (covers isinstance list at line 58)."""
        data = {"prompts": ["a", "b"]}
        meta_helper._display_key(data, "prompts")
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed == ["a", "b"]

    def test_display_key_missing_exits(self, monkeypatch, caplog):
        """_display_key exits when key not found (covers line 55-56)."""
        with caplog.at_level(0):
            with pytest.raises(SystemExit) as exc_info:
                meta_helper._display_key({}, "missing")
        assert exc_info.value.code == 1

    def test_add_images_only(self, tmp_path, capsys):
        """_add_images_only adds images to last prompt (covers lines 66-81)."""
        spec_dir, meta_path = _make_meta(tmp_path, "t1", {
            "prompts": [
                {"text": "prompt", "timestamp": "2026-01-01"},
            ],
        })

        from common import SpecMeta
        meta = SpecMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        meta_helper._add_images_only(meta, ["img1.png", "img2.png"], meta_path)

        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["prompts"][0]["images"] == ["img1.png", "img2.png"]
        # File should also be updated
        file_data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert file_data["prompts"][0]["images"] == ["img1.png", "img2.png"]

    def test_add_images_only_no_prompts_exits(self, monkeypatch, tmp_path):
        """_add_images_only exits when no prompts exist (covers lines 66-68)."""
        spec_dir, meta_path = _make_meta(tmp_path, "t2", {"prompts": []})
        from common import SpecMeta
        meta = SpecMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))

        with pytest.raises(SystemExit) as exc_info:
            meta_helper._add_images_only(meta, ["img.png"], meta_path)
        assert exc_info.value.code == 1

    def test_set_key_prompts_with_images(self, tmp_path, capsys):
        """_set_key creates prompt entry with images (covers lines 86-104)."""
        spec_dir, meta_path = _make_meta(tmp_path, "t3", {"prompts": []})
        from common import SpecMeta
        meta = SpecMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        meta_helper._set_key(meta, "prompts", "hello world", meta_path,
                             images=["photo.jpg"])

        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data["prompts"]) == 1
        assert data["prompts"][0]["text"] == "hello world"
        assert data["prompts"][0]["images"] == ["photo.jpg"]
        assert "timestamp" in data["prompts"][0]

    def test_set_key_prompts_without_images(self, tmp_path, capsys):
        """_set_key creates prompt entry without images (covers line 90-93)."""
        spec_dir, meta_path = _make_meta(tmp_path, "t4", {"prompts": []})
        from common import SpecMeta
        meta = SpecMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        meta_helper._set_key(meta, "prompts", "text only", meta_path)

        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["prompts"][0]["text"] == "text only"
        assert "images" not in data["prompts"][0]

    def test_set_key_known_field(self, tmp_path, capsys):
        """_set_key uses setattr for known fields (covers lines 95-97)."""
        spec_dir, meta_path = _make_meta(tmp_path, "t5", {
            "name": "t5", "branch": "old",
        })
        from common import SpecMeta
        meta = SpecMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        meta_helper._set_key(meta, "branch", "new", meta_path)

        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["branch"] == "new"

    def test_set_key_unknown_field(self, tmp_path, capsys):
        """_set_key stores unknown fields in extras (covers lines 98-99)."""
        spec_dir, meta_path = _make_meta(tmp_path, "t6", {"name": "t6"})
        from common import SpecMeta
        meta = SpecMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        meta_helper._set_key(meta, "custom", "value", meta_path)

        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["custom"] == "value"

    def test_set_key_prompts_initializes_list(self, tmp_path, capsys):
        """_set_key initializes prompts list when meta.prompts is None."""
        spec_dir, meta_path = _make_meta(tmp_path, "t7", {"name": "t7"})
        from common import SpecMeta
        meta = SpecMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        # meta.prompts will be None or not a list
        meta_helper._set_key(meta, "prompts", "first", meta_path)

        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data["prompts"]) == 1
        assert data["prompts"][0]["text"] == "first"

    def test_main_display_all(self, monkeypatch, capsys, tmp_path):
        """main() with no key routes to _display_all (covers line 170-171)."""
        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir, meta_path = _make_meta(tmp_path, "t8", {
            "name": "t8", "branch": "main",
        })
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)

        meta_helper.main(["t8"])
        out = capsys.readouterr().out
        assert "name: t8" in out
        assert "branch: main" in out

    def test_main_display_key(self, monkeypatch, capsys, tmp_path):
        """main() with key only routes to _display_key (covers line 186)."""
        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir, meta_path = _make_meta(tmp_path, "t9", {
            "name": "t9", "branch": "feature-y",
        })
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)

        meta_helper.main(["t9", "branch"])
        assert capsys.readouterr().out.strip() == "feature-y"

    def test_main_set_value(self, monkeypatch, capsys, tmp_path):
        """main() with key+value routes to _set_key (covers line 176)."""
        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir, meta_path = _make_meta(tmp_path, "t10", {
            "name": "t10", "branch": "old",
        })
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)

        meta_helper.main(["t10", "branch", "new"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["branch"] == "new"

    def test_main_add_images_only(self, monkeypatch, capsys, tmp_path):
        """main() prompts+add_images (no value) routes to _add_images_only (lines 183-184)."""
        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir, meta_path = _make_meta(tmp_path, "t11", {
            "prompts": [
                {"text": "existing", "timestamp": "2026-01-01"},
            ],
        })
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)

        meta_helper.main(["t11", "prompts", "--add-images", "img.png"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["prompts"][0]["images"] == ["img.png"]

    def test_main_invalid_json(self, monkeypatch, caplog, tmp_path):
        """main() with invalid JSON exits 1 (covers lines 163-166)."""
        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir, meta_path = _make_meta(tmp_path, "t12", {})
        meta_path.write_text("{bad json}", encoding="utf-8")
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)

        with caplog.at_level(0):
            with pytest.raises(SystemExit) as exc_info:
                meta_helper.main(["t12"])
        assert exc_info.value.code == 1
        assert "invalid JSON" in caplog.text

    def test_main_missing_meta(self, monkeypatch, caplog, tmp_path):
        """main() with missing meta.json exits 1 (covers lines 158-160)."""
        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir = tmp_path / "specs" / "t13"
        spec_dir.mkdir(parents=True)
        # No meta.json
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)

        with caplog.at_level(0):
            with pytest.raises(SystemExit) as exc_info:
                meta_helper.main(["t13"])
        assert exc_info.value.code == 1
        assert "file not found" in caplog.text

    def test_main_set_prompts_via_stdin(self, monkeypatch, capsys, tmp_path):
        """main() stdin with prompts key routes to _set_key (covers lines 177-182)."""
        import io

        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir, meta_path = _make_meta(tmp_path, "t14", {"prompts": []})
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)
        monkeypatch.setattr("sys.stdin", io.StringIO("stdin prompt text"))

        meta_helper.main(["t14", "prompts", "--stdin"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["prompts"][0]["text"] == "stdin prompt text"

    def test_main_set_non_prompts_via_stdin(self, monkeypatch, capsys, tmp_path):
        """main() stdin with non-prompts key routes to _set_key directly (line 182)."""
        import io

        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir, meta_path = _make_meta(tmp_path, "t15", {
            "name": "t15", "description": "old",
        })
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)
        monkeypatch.setattr("sys.stdin", io.StringIO("new desc"))

        meta_helper.main(["t15", "description", "--stdin"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["description"] == "new desc"

    def test_main_prompts_with_images_via_stdin(self, monkeypatch, capsys, tmp_path):
        """main() stdin+prompts+add_images routes to _set_key with images (line 179-180)."""
        import io

        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir, meta_path = _make_meta(tmp_path, "t16", {"prompts": []})
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)
        monkeypatch.setattr("sys.stdin", io.StringIO("stdin with images"))

        meta_helper.main([
            "t16", "prompts", "--stdin",
            "--add-images", "photo.png",
        ])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["prompts"][0]["text"] == "stdin with images"
        assert data["prompts"][0]["images"] == ["photo.png"]

    def test_main_prompts_with_value_and_images(self, monkeypatch, capsys, tmp_path):
        """main() prompts+value+add_images routes to _set_key with images (line 173-174)."""
        from common import clear_spex_root_cache
        from config import ProjectContext
        spec_dir, meta_path = _make_meta(tmp_path, "t17", {"prompts": []})
        ctx = ProjectContext(
            cwd=tmp_path, top_workdir=None, main_worktree=None,
            remote_url="", branch="", user_name="", user_email="",
            spex_tomls=[], config={}, spex_root=str(tmp_path),
            spex_roots=[str(tmp_path)],
        )
        clear_spex_root_cache()
        monkeypatch.setattr("common.get_project_context", lambda w=None: ctx)

        meta_helper.main([
            "t17", "prompts", "prompt text",
            "--add-images", "photo.png",
        ])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["prompts"][0]["text"] == "prompt text"
        assert data["prompts"][0]["images"] == ["photo.png"]

    def test_set_key_replaces_non_list_prompts(self, tmp_path, capsys):
        """_set_key initializes prompts list when meta.prompts is not a list (line 89)."""
        spec_dir, meta_path = _make_meta(tmp_path, "t18", {
            "name": "t18",
            "prompts": "not a list",
        })
        from common import SpecMeta
        meta = SpecMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        meta_helper._set_key(meta, "prompts", "new prompt", meta_path)

        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data["prompts"]) == 1
        assert data["prompts"][0]["text"] == "new prompt"
