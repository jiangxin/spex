"""End-to-end tests for spex todo-helper subcommand."""

from __future__ import annotations

import json

import pytest

from tests.e2e.conftest import run_spex


def _make_todo_json(done: bool = False) -> list[dict]:
    """Build a standard two-step todo list."""
    items = [
        {
            "id": "step-1",
            "name": "First step",
            "details": "Details for First step",
            "completed_at": "",
            "commit_title": "",
        },
        {
            "id": "step-2",
            "name": "Second step",
            "details": "Details for Second step",
            "completed_at": "",
            "commit_title": "",
        },
    ]
    if done:
        for item in items:
            item["completed_at"] = "2026-05-30T00:00:00"
            item["commit_title"] = f"abc1234: {item['name']}"
    return items


def _create_topic(sandbox, name, *, done=False):
    """Create a spec directory with meta.json, spec.md, todo.json.

    Returns dict with spec_name and spec_path keys.
    """
    specs_dir = sandbox.spex_root / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)

    spec_dir = specs_dir / name
    spec_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "workdir": str(sandbox.repo),
        "branch": "main",
        "user_name": "Test User",
        "user_email": "test@example.com",
        "created_at": "2026-05-30T00:00:00",
        "description": "",
        "prompts": [],
    }
    (spec_dir / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8",
    )
    (spec_dir / "spec.md").write_text(
        f"# {name}\n\nTest spec.\n", encoding="utf-8",
    )

    todo = _make_todo_json(done=done)
    (spec_dir / "todo.json").write_text(
        json.dumps(todo, indent=2), encoding="utf-8",
    )

    return {
        "spec_name": name,
        "spec_path": str(spec_dir),
    }


@pytest.mark.e2e
class TestTodoHelperValidate:
    def test_validate_json_via_topic(self, sandbox):
        """Validate a spec's todo.json via a positional name."""
        data = _create_topic(sandbox, "val-json")
        spec_name = data["spec_name"]

        result = run_spex(
            "todo-helper", "validate", spec_name,
            sandbox=sandbox,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stderr


@pytest.mark.e2e
class TestTodoHelperAppendShow:
    def test_append_and_show(self, sandbox):
        """Append a step and verify it appears in show output."""
        data = _create_topic(sandbox, "append-test")
        spec_name = data["spec_name"]

        result = run_spex(
            "todo-helper", "append", spec_name,
            "--id", "step-3",
            "--step-name", "New step",
            "--details", "New details",
            sandbox=sandbox,
        )
        assert result.returncode == 0, result.stderr

        result = run_spex(
            "todo-helper", "show", spec_name,
            sandbox=sandbox,
        )
        assert result.returncode == 0, result.stderr
        items = json.loads(result.stdout)
        ids = [item["id"] for item in items]
        assert "step-3" in ids

    def test_show_done_filter(self, sandbox):
        """Show --done returns only completed steps."""
        data = _create_topic(
            sandbox, "done-filter", done=True,
        )
        spec_name = data["spec_name"]

        result = run_spex(
            "todo-helper", "show", spec_name, "--done",
            sandbox=sandbox,
        )
        assert result.returncode == 0, result.stderr
        items = json.loads(result.stdout)
        ids = [item["id"] for item in items]
        assert "step-1" in ids
        assert "step-2" in ids


@pytest.mark.e2e
class TestTodoHelperWorkflow:
    def test_full_crud_workflow(self, sandbox):
        """Exercise append, edit, show, remove sequence."""
        data = _create_topic(sandbox, "crud-test")
        spec_name = data["spec_name"]

        # 1. Append step-3
        result = run_spex(
            "todo-helper", "append", spec_name,
            "--id", "step-3",
            "--step-name", "Task 3",
            "--details", "Do thing 3",
            sandbox=sandbox,
        )
        assert result.returncode == 0, result.stderr

        # 2. Edit step-3
        result = run_spex(
            "todo-helper", "edit", spec_name,
            "--id", "step-3",
            "--step-name", "Updated Task 3",
            sandbox=sandbox,
        )
        assert result.returncode == 0, result.stderr

        # 3. Show all — verify updated name
        result = run_spex(
            "todo-helper", "show", spec_name,
            sandbox=sandbox,
        )
        assert result.returncode == 0, result.stderr
        items = json.loads(result.stdout)
        step3 = [
            i for i in items if i["id"] == "step-3"
        ]
        assert len(step3) == 1
        assert step3[0]["name"] == "Updated Task 3"

        # 4. Remove step-3
        result = run_spex(
            "todo-helper", "remove", spec_name,
            "--id", "step-3",
            sandbox=sandbox,
        )
        assert result.returncode == 0, result.stderr

        # 5. Show again — step-3 should be gone
        result = run_spex(
            "todo-helper", "show", spec_name,
            sandbox=sandbox,
        )
        assert result.returncode == 0, result.stderr
        items = json.loads(result.stdout)
        ids = [item["id"] for item in items]
        assert "step-3" not in ids
        assert "step-1" in ids
        assert "step-2" in ids
