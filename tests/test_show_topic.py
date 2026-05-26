import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import show_topic


def _make_topic(tmp_path, name="my-topic", spec_content=None, todo=None):
    """Create a topic directory with optional spec and todo."""
    topic_dir = tmp_path / "specs" / name
    topic_dir.mkdir(parents=True)
    meta = {"created_at": "2026-05-20T10:00:00+08:00", "prompts": ["test"]}
    (topic_dir / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    if spec_content:
        (topic_dir / "spec.md").write_text(spec_content, encoding="utf-8")
    if todo:
        (topic_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8"
        )
    return topic_dir


class TestFormatDefault:
    def test_shows_icon_progress_name(self, tmp_path):
        topic_dir = _make_topic(
            tmp_path,
            spec_content='---\ndescription: "A desc"\n---\n\n# Spec',
            todo=[
                {"id": "step-1", "name": "First", "details": "",
                 "completed_at": "2026-01-01", "commit_title": "abc"},
                {"id": "step-2", "name": "Second", "details": "",
                 "completed_at": "", "commit_title": ""},
            ],
        )
        output = show_topic._format_default(topic_dir)
        lines = output.splitlines()
        assert "[1/2]" in lines[0]
        assert "my-topic" in lines[0]
        assert "    A desc" in lines[1]
        assert "    step-1: First" in output
        assert "    step-2: Second" in output

    def test_no_spec_no_steps(self, tmp_path):
        topic_dir = _make_topic(tmp_path)
        output = show_topic._format_default(topic_dir)
        assert "[0/0]" in output
        assert "step-" not in output


class TestFormatVerbose:
    def test_shows_spec_and_todo(self, tmp_path):
        spec = '---\nversion: "0.0.1"\n---\n\n# My Spec\n\nContent here.'
        topic_dir = _make_topic(
            tmp_path,
            spec_content=spec,
            todo=[
                {"id": "step-1", "name": "Do thing", "details": "Detail text",
                 "completed_at": "", "commit_title": ""},
            ],
        )
        output = show_topic._format_verbose(topic_dir)
        assert "# **Specification**" in output
        assert "# My Spec" in output
        assert "Content here." in output
        assert "----" in output
        assert "# **TODO**" in output
        assert "- **step-1: Do thing**" in output
        assert "  Detail text" in output

    def test_no_spec_file(self, tmp_path):
        topic_dir = _make_topic(tmp_path)
        output = show_topic._format_verbose(topic_dir)
        assert "(no spec.md found)" in output

    def test_no_todo(self, tmp_path):
        spec = '---\nversion: "0.0.1"\n---\n\n# Spec'
        topic_dir = _make_topic(tmp_path, spec_content=spec)
        output = show_topic._format_verbose(topic_dir)
        assert "(no tasks)" in output


class TestMain:
    def test_no_args_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])
        with pytest.raises(SystemExit) as exc_info:
            show_topic.main()
        assert exc_info.value.code == 1

    def test_help_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "-h"])
        with pytest.raises(SystemExit) as exc_info:
            show_topic.main()
        assert exc_info.value.code == 0

    def test_nonexistent_topic(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SPEX_ROOT", str(tmp_path))
        (tmp_path / "specs").mkdir()
        monkeypatch.setattr(sys, "argv", ["prog", "nonexistent"])
        from common import clear_spex_root_cache
        clear_spex_root_cache()
        with pytest.raises(SystemExit) as exc_info:
            show_topic.main()
        assert exc_info.value.code == 1
