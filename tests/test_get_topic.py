import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from get_topic import resolve_topic


def _make_topic(specs_dir, name, completed=False):
    """Create a topic directory with todo.json."""
    topic = specs_dir / name
    topic.mkdir(parents=True, exist_ok=True)
    task = {
        "id": "t1",
        "name": "task",
        "details": "d",
        "completed_at": "2026-01-01T00:00:00+08:00" if completed else "",
        "commit_title": "done" if completed else "",
    }
    (topic / "todo.json").write_text(
        json.dumps([task]), encoding="utf-8"
    )


class TestResolveTopic:
    def test_exact_match(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-my-topic")

        result = resolve_topic("2026-05-20-my-topic", specs)
        assert result == ["2026-05-20-my-topic"]

    def test_fuzzy_single_match(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-fuzzy-topic")
        _make_topic(specs, "2026-05-20-other-thing")

        result = resolve_topic("fuzzy", specs)
        assert result == ["2026-05-20-fuzzy-topic"]

    def test_fuzzy_multiple_matches(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-edit-alpha")
        _make_topic(specs, "2026-05-20-edit-beta")

        result = resolve_topic("edit", specs)
        assert result == ["2026-05-20-edit-alpha", "2026-05-20-edit-beta"]

    def test_fuzzy_no_match(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-something")

        with pytest.raises(SystemExit):
            resolve_topic("nonexistent", specs)

    def test_fuzzy_skips_completed(self, tmp_path):
        specs = tmp_path / "specs"
        _make_topic(specs, "2026-05-20-done-topic", completed=True)
        _make_topic(specs, "2026-05-20-active-topic")

        result = resolve_topic("topic", specs)
        assert result == ["2026-05-20-active-topic"]
