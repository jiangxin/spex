"""Unit tests for todo_helper.py — JSON CRUD operations."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest
import todo_helper


@pytest.fixture()
def todo_file(tmp_path):
    return tmp_path / "todo.json"


def _write(path, data):
    path.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8",
    )


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


SAMPLE_DATA = [
    {
        "id": "step-1",
        "name": "First step",
        "details": "Do the first thing",
        "completed_at": "2026-01-01T10:00:00+08:00",
        "commit_title": "feat: first step",
    },
    {
        "id": "step-2",
        "name": "Second step",
        "details": "Do the second thing",
        "completed_at": "",
        "commit_title": "",
    },
    {
        "id": "step-3",
        "name": "Third step",
        "details": "Do the third thing",
        "completed_at": "2026-01-02T12:00:00+08:00",
        "commit_title": "feat: third step",
    },
]

EVIDENCE = [
    {"kind": "command", "criterion": "Valid report", "command": "check", "exit_code": 0},
    {"kind": "inspection", "criterion": "Readable", "location": "/tmp/report",
     "observation": "All sections are present"},
]


@pytest.fixture
def general_todo(todo_file):
    _write(todo_file, SAMPLE_DATA)
    _write(todo_file.parent / "meta.json", {"task_mode": "general"})
    return todo_file


def _complete(path, *flags):
    return ["complete", "--todo-file", str(path), "--id", "2", *flags]


def test_complete_general_is_atomic_and_idempotent(general_todo, monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(EVIDENCE)))
    todo_helper.main(_complete(
        general_todo, "--acceptance-evidence-stdin", "--commit-title", "abc: docs",
    ))
    task = _read(general_todo)[1]
    assert task["completed_at"]
    assert task["acceptance_evidence"] == EVIDENCE
    assert task["commit_title"] == "abc: docs"
    snapshot = general_todo.read_bytes()
    monkeypatch.setattr("sys.stdin", StringIO("invalid"))
    todo_helper.main(_complete(general_todo, "--acceptance-evidence-stdin"))
    assert general_todo.read_bytes() == snapshot


def test_complete_cannot_skip_general_tasks(general_todo, monkeypatch):
    data = _read(general_todo)
    data[2]["completed_at"] = ""
    _write(general_todo, data)
    snapshot = general_todo.read_bytes()
    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(EVIDENCE)))
    with pytest.raises(SystemExit) as error:
        todo_helper.main([
            "complete", "--todo-file", str(general_todo), "--id", "3",
            "--acceptance-evidence-stdin",
        ])
    assert error.value.code == 1
    assert general_todo.read_bytes() == snapshot


@pytest.mark.parametrize("payload", [
    None, "invalid JSON", "[]", "{}", "[false]", '[{"kind":[]}]',
    json.dumps([{**EVIDENCE[0], "exit_code": False}]),
    json.dumps([{**EVIDENCE[0], "exit_code": 0.0}]),
    json.dumps([{**EVIDENCE[0], "exit_code": 1}]),
    json.dumps([{**EVIDENCE[0], "command": " "}]),
    json.dumps([{**EVIDENCE[1], "location": None}]),
])
def test_complete_rejects_missing_or_invalid_evidence(general_todo, monkeypatch, payload):
    snapshot = general_todo.read_bytes()
    flags = []
    if payload is not None:
        monkeypatch.setattr("sys.stdin", StringIO(payload))
        flags.append("--acceptance-evidence-stdin")
    with pytest.raises(SystemExit) as error:
        todo_helper.main(_complete(general_todo, *flags))
    assert error.value.code == 1
    assert general_todo.read_bytes() == snapshot


@pytest.mark.parametrize("subcommand, flags", [
    ("append", ["--step-name", "Extra", "--details", "New"]),
    ("insert", ["--before", "2", "--step-name", "Extra", "--details", "New"]),
    ("edit", ["--id", "2"]),
])
def test_general_plan_mutations_cannot_set_completion(general_todo, subcommand, flags):
    snapshot = general_todo.read_bytes()
    with pytest.raises(SystemExit) as error:
        todo_helper.main([
            subcommand, "--todo-file", str(general_todo), "--completed-at", "now", *flags,
        ])
    assert error.value.code == 1
    assert general_todo.read_bytes() == snapshot


def test_complete_general_write_failure_and_transaction_rollback(general_todo, monkeypatch):
    snapshot = general_todo.read_bytes()
    locator = ["--todo-file", str(general_todo)]
    todo_helper.main(["transaction", "start", *locator])

    def fail_to_write(*_args):
        raise OSError("todo write failed")

    args = _complete(general_todo, "--acceptance-evidence-stdin")
    with monkeypatch.context() as patch:
        patch.setattr(todo_helper, "atomic_write_json", fail_to_write)
        patch.setattr("sys.stdin", StringIO(json.dumps(EVIDENCE)))
        with pytest.raises(SystemExit) as error:
            todo_helper.main(args)
        assert error.value.code == 1
    assert general_todo.read_bytes() == snapshot

    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(EVIDENCE)))
    todo_helper.main(args)
    assert _read(general_todo)[1]["acceptance_evidence"] == EVIDENCE
    todo_helper.main(["transaction", "rollback", *locator])
    assert general_todo.read_bytes() == snapshot


# -----------------------------------------------------------------------
# File locating
# -----------------------------------------------------------------------
class TestFileLocating:
    def test_topic_resolves_todo_json(self, tmp_path, monkeypatch):
        spec_dir = tmp_path / "my-topic"
        spec_dir.mkdir()
        todo = spec_dir / "todo.json"
        _write(todo, SAMPLE_DATA)

        monkeypatch.setattr(
            todo_helper, "resolve_spec_dir",
            lambda name, **kw: spec_dir,
        )
        todo_helper.main([
            "validate", "my-topic",
        ])

    def test_todo_file_direct_path(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "validate",
        ])

    def test_name_after_subcommand(self, tmp_path, monkeypatch):
        """The positional name can follow value-taking options."""
        spec_dir = tmp_path / "2026-08-04-15-50-create-debug-session"
        spec_dir.mkdir()
        todo = spec_dir / "todo.json"
        _write(todo, SAMPLE_DATA)

        monkeypatch.setattr(
            todo_helper, "resolve_spec_dir",
            lambda name, **kw: spec_dir,
        )
        # Keep value-taking options distinct from the positional selector.
        todo_helper.main([
            "edit",
            "--id", "3",
            "--commit-title",
            "84e59c4: feat(create-helper): handoff session on prepare-spec",
            "2026-08-04-15-50-create-debug-session",
        ])
        result = _read(todo)
        step3 = [i for i in result if i["id"] == 3][0]
        assert step3["commit_title"] == (
            "84e59c4: feat(create-helper): handoff session on prepare-spec"
        )

    def test_todo_file_after_subcommand(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "validate", "--todo-file", str(todo_file),
        ])

    def test_name_after_boolean_option(
        self, tmp_path, monkeypatch,
    ):
        spec_dir = tmp_path / "my-topic"
        spec_dir.mkdir()
        todo = spec_dir / "todo.json"
        _write(todo, SAMPLE_DATA)

        monkeypatch.setattr(
            todo_helper, "resolve_spec_dir",
            lambda name, **kw: spec_dir,
        )
        todo_helper.main(["show", "--undone", "my-topic"])

    def test_both_topic_and_todo_file_error(self, todo_file):
        with pytest.raises(SystemExit):
            todo_helper.main([
                "validate", "x",
                "--todo-file", str(todo_file),
            ])

    def test_both_name_and_todo_file_mixed_positions_error(
        self, todo_file,
    ):
        with pytest.raises(SystemExit):
            todo_helper.main([
                "validate", "x",
                "--todo-file", str(todo_file),
            ])

    def test_neither_topic_nor_todo_file_error(self):
        with pytest.raises(SystemExit):
            todo_helper.main(["validate"])


class TestTransaction:
    @pytest.mark.parametrize("action", ["commit", "rollback"])
    def test_split_pending_step_preserves_prior_progress(self, todo_file, action):
        completed, pending, following = [
            dict(item, id=idx) for idx, item in enumerate(SAMPLE_DATA, 1)
        ]
        following.update(completed_at="", commit_title="")
        _write(todo_file, [completed, pending, following])
        original = todo_file.read_bytes()
        locator = ["--todo-file", str(todo_file)]

        todo_helper.main(["transaction", "start", *locator])
        todo_helper.main([
            "edit", *locator, "--id", "2", "--step-name", "Narrowed step",
            "--details", "Verify the first increment",
        ])
        for position, name in [(2, "First follow-up"), (3, "Second follow-up")]:
            todo_helper.main([
                "insert", *locator, "--after", str(position), "--step-name", name,
                "--details", "Verify the follow-up increment",
            ])
        todo_helper.main(["transaction", action, *locator])

        assert not todo_file.with_suffix(".json.lock").exists()
        if action == "rollback":
            assert todo_file.read_bytes() == original
            return

        finished, first, *follow_ups, last = _read(todo_file)
        assert finished == completed
        assert first == dict(pending, name="Narrowed step", details="Verify the first increment")
        assert [task["id"] for task in follow_ups] == [3, 4]
        assert [task["name"] for task in follow_ups] == ["First follow-up", "Second follow-up"]
        assert all(task["commit_title"] == task["completed_at"] == "" for task in follow_ups)
        assert last == dict(following, id=5)

    def test_commit_by_spec_name(self, todo_file, monkeypatch):
        monkeypatch.setattr(
            todo_helper, "resolve_spec_dir", lambda name: todo_file.parent,
        )
        todo_file.write_bytes(b"[]")

        todo_helper.main(["transaction", "start", "my-topic"])
        backup = todo_file.with_suffix(".json.lock")
        assert backup.read_bytes() == b"[]"
        _write(todo_file, SAMPLE_DATA)

        todo_helper.main(["transaction", "commit", "my-topic"])
        assert _read(todo_file) == [
            dict(item, id=index) for index, item in enumerate(SAMPLE_DATA, 1)
        ]
        assert not backup.exists()

    def test_pending_appends_get_ids_on_commit(self, todo_file):
        locator = ["--todo-file", str(todo_file)]
        todo_helper.main(["transaction", "start", *locator])
        for name in ("First", "Second"):
            todo_helper.main(["append", *locator, "--step-name", name, "--details", ""])
        assert all("id" not in item for item in _read(todo_file))
        todo_helper.main(["remove", *locator, "--id", "1"])
        todo_helper.main(["edit", *locator, "--id", "1", "--step-name", "Edited"])
        assert "id" not in _read(todo_file)[0]

        todo_helper.main(["transaction", "commit", *locator])

        assert _read(todo_file) == [{
            "id": 1, "name": "Edited", "details": "",
            "completed_at": "", "commit_title": "",
        }]

    def test_invalid_commit_keeps_snapshot_available_for_rollback(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        original = todo_file.read_bytes()
        locator = ["--todo-file", str(todo_file)]
        todo_helper.main(["transaction", "start", *locator])
        todo_file.write_bytes(b"[{}]")

        with pytest.raises(SystemExit) as error:
            todo_helper.main(["transaction", "commit", *locator])
        assert error.value.code == 1
        assert todo_file.with_suffix(".json.lock").read_bytes() == original
        assert todo_file.read_bytes() == b"[{}]"

        todo_helper.main(["transaction", "rollback", *locator])
        assert todo_file.read_bytes() == original

    def test_failed_commit_write_keeps_snapshot_for_retry(self, todo_file, monkeypatch):
        _write(todo_file, SAMPLE_DATA)
        original = todo_file.read_bytes()
        locator = ["--todo-file", str(todo_file)]
        todo_helper.main(["transaction", "start", *locator])

        def fail_to_write(*_args):
            raise OSError("todo write failed")

        with monkeypatch.context() as patch:
            patch.setattr(todo_helper, "atomic_write_json", fail_to_write)
            with pytest.raises(SystemExit) as error:
                todo_helper.main(["transaction", "commit", *locator])
        assert error.value.code == 1
        assert todo_file.with_suffix(".json.lock").read_bytes() == original
        assert todo_file.read_bytes() == original

        todo_helper.main(["transaction", "commit", *locator])
        assert [item["id"] for item in _read(todo_file)] == [1, 2, 3]

    @pytest.mark.parametrize("original", [b"[]", b" [\r\n {} ]\n", b"\xff"])
    def test_rollback_restores_snapshot_bytes(self, todo_file, original):
        todo_file.write_bytes(original)
        locator = ["--todo-file", str(todo_file)]
        todo_helper.main(["transaction", "start", *locator])
        backup = todo_file.with_suffix(".json.lock")
        assert backup.read_bytes() == original
        todo_file.write_bytes(b"updated")

        todo_helper.main([*locator, "transaction", "rollback"])
        assert todo_file.read_bytes() == original
        assert not backup.exists()

    @pytest.mark.parametrize(
        "original", [None, b"", b" \t\r\n", "\u2003".encode("utf-8")],
    )
    def test_rollback_empty_snapshot_removes_todo(self, todo_file, original):
        if original is not None:
            todo_file.write_bytes(original)
        locator = ["--todo-file", str(todo_file)]
        todo_helper.main(["transaction", "start", *locator])
        backup = todo_file.with_suffix(".json.lock")
        assert backup.read_bytes() == b""
        todo_file.write_bytes(b"updated")

        todo_helper.main(["transaction", "rollback", *locator])
        assert not todo_file.exists()
        assert not backup.exists()

    def test_repeated_start_preserves_backup(self, todo_file):
        todo_file.write_bytes(b"original")
        start = ["transaction", "start", "--todo-file", str(todo_file)]
        todo_helper.main(start)
        todo_file.write_bytes(b"updated")

        with pytest.raises(SystemExit) as error:
            todo_helper.main(start)
        assert error.value.code == 1
        assert todo_file.with_suffix(".json.lock").read_bytes() == b"original"
        assert todo_file.read_bytes() == b"updated"

    def test_failed_publish_cleans_temporary_file(self, todo_file, monkeypatch, caplog):
        todo_file.write_bytes(b"original")

        def fail_to_link(_source, _target):
            raise OSError("snapshot publication failed")

        monkeypatch.setattr(todo_helper.os, "link", fail_to_link)
        with pytest.raises(SystemExit) as error:
            todo_helper.main(["transaction", "start", "--todo-file", str(todo_file)])
        assert error.value.code == 1
        assert "snapshot publication failed" in caplog.text
        assert list(todo_file.parent.iterdir()) == [todo_file]
        assert todo_file.read_bytes() == b"original"

    @pytest.mark.parametrize("action", ["commit", "rollback"])
    def test_ending_without_backup_preserves_todo(self, todo_file, action):
        todo_file.write_bytes(b"original")

        with pytest.raises(SystemExit) as error:
            todo_helper.main(["transaction", action, "--todo-file", str(todo_file)])
        assert error.value.code == 1
        assert todo_file.read_bytes() == b"original"


# -----------------------------------------------------------------------
# validate
# -----------------------------------------------------------------------
class TestValidate:
    def test_valid_file(self, todo_file, caplog):
        _write(todo_file, SAMPLE_DATA)
        with caplog.at_level(logging.INFO):
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert "OK" in caplog.text

    def test_duplicate_ids_fail(self, todo_file):
        data = [
            {"id": "s1", "name": "A", "details": "",
             "completed_at": "", "commit_title": ""},
            {"id": "s1", "name": "B", "details": "",
             "completed_at": "", "commit_title": ""},
        ]
        _write(todo_file, data)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert exc.value.code == 1

    def test_missing_required_field_fails(self, todo_file):
        data = [{"id": "s1", "name": "A"}]  # missing details etc.
        _write(todo_file, data)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert exc.value.code == 1

    def test_empty_file_ok(self, todo_file, caplog):
        _write(todo_file, [])
        with caplog.at_level(logging.INFO):
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert "OK" in caplog.text

    def test_skip_commit_valid_values(self, todo_file, caplog):
        for value in (False, "false", "auto", True, "true"):
            data = [{
                "id": "s1", "name": "A", "details": "",
                "completed_at": "", "commit_title": "",
                "skip_commit": value,
            }]
            _write(todo_file, data)
            with caplog.at_level(logging.INFO):
                todo_helper.main([
                    "--todo-file", str(todo_file), "validate",
                ])
            assert "OK" in caplog.text

    def test_skip_commit_invalid_value_fails(self, todo_file):
        data = [{
            "id": "s1", "name": "A", "details": "",
            "completed_at": "", "commit_title": "",
            "skip_commit": "yes",
        }]
        _write(todo_file, data)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert exc.value.code == 1

    def test_skip_commit_absent_ok(self, todo_file, caplog):
        _write(todo_file, SAMPLE_DATA)
        with caplog.at_level(logging.INFO):
            todo_helper.main([
                "--todo-file", str(todo_file), "validate",
            ])
        assert "OK" in caplog.text


# -----------------------------------------------------------------------
# normalize_skip_commit
# -----------------------------------------------------------------------
class TestNormalizeSkipCommit:
    def test_missing_and_false(self):
        assert todo_helper.normalize_skip_commit() == "false"
        assert todo_helper.normalize_skip_commit(None) == "false"
        assert todo_helper.normalize_skip_commit(False) == "false"
        assert todo_helper.normalize_skip_commit("false") == "false"

    def test_auto(self):
        assert todo_helper.normalize_skip_commit("auto") == "auto"

    def test_true(self):
        assert todo_helper.normalize_skip_commit(True) == "true"
        assert todo_helper.normalize_skip_commit("true") == "true"

    def test_invalid(self):
        with pytest.raises(SystemExit) as exc:
            todo_helper.normalize_skip_commit("yes")
        assert exc.value.code == 1
        with pytest.raises(SystemExit):
            todo_helper.normalize_skip_commit("False")
        with pytest.raises(SystemExit):
            todo_helper.normalize_skip_commit(1)


# -----------------------------------------------------------------------
# append
# -----------------------------------------------------------------------
class TestAppend:
    def test_append_to_existing(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--step-name", "Fourth step",
            "--details", "Do the fourth thing",
        ])
        result = _read(todo_file)
        assert len(result) == 4
        assert result[-1]["id"] == 4
        assert result[-1]["name"] == "Fourth step"
        assert result[-1]["completed_at"] == ""
        assert result[-1]["commit_title"] == ""

    def test_append_creates_new_file(self, todo_file):
        assert not todo_file.exists()
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--step-name", "First",
            "--details", "Details here",
        ])
        result = _read(todo_file)
        assert len(result) == 1
        assert result[0]["id"] == 1

    @pytest.mark.parametrize("id_option", [["--id", "1"], ["--id=1"]])
    def test_append_rejects_id(self, todo_file, id_option):
        _write(todo_file, SAMPLE_DATA)
        original = todo_file.read_bytes()
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "append",
                *id_option,
                "--step-name", "Explicit ID",
                "--details", "Details",
            ])
        assert exc.value.code == 2
        assert todo_file.read_bytes() == original

    def test_append_with_optional_fields(self, todo_file):
        _write(todo_file, [])
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--step-name", "Done task",
            "--details", "Already done",
            "--completed-at", "2026-05-30",
            "--commit-title", "feat: done",
        ])
        result = _read(todo_file)
        assert result[0]["completed_at"] == "2026-05-30"
        assert result[0]["commit_title"] == "feat: done"

    def test_append_details_from_stdin(self, todo_file, monkeypatch):
        _write(todo_file, [])
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(
            "Multi-line details\n\n- Item 1\n- Item 2\n",
        ))
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--step-name", "Stdin step",
            "--details-from-stdin",
        ])
        result = _read(todo_file)
        assert "Multi-line details" in result[0]["details"]
        assert "- Item 1" in result[0]["details"]

    def test_append_no_details_fails(self, todo_file):
        _write(todo_file, [])
        with pytest.raises(SystemExit):
            todo_helper.main([
                "--todo-file", str(todo_file), "append",
            "--step-name", "No details",
            ])

    def test_append_omits_skip_commit_by_default(self, todo_file):
        _write(todo_file, [])
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--step-name", "Default skip",
            "--details", "No flag",
        ])
        result = _read(todo_file)
        assert "skip_commit" not in result[0]

    def test_append_skip_commit_false_omits_key(self, todo_file):
        _write(todo_file, [])
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--step-name", "Explicit false",
            "--details", "Details",
            "--skip-commit", "false",
        ])
        result = _read(todo_file)
        assert "skip_commit" not in result[0]

    def test_append_skip_commit_auto(self, todo_file):
        _write(todo_file, [])
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--step-name", "Auto skip",
            "--details", "Details",
            "--skip-commit", "auto",
        ])
        result = _read(todo_file)
        assert result[0]["skip_commit"] == "auto"

    def test_append_skip_commit_true(self, todo_file):
        _write(todo_file, [])
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--step-name", "True skip",
            "--details", "Details",
            "--skip-commit", "true",
        ])
        result = _read(todo_file)
        assert result[0]["skip_commit"] == "true"


# -----------------------------------------------------------------------
# edit
# -----------------------------------------------------------------------
class TestEdit:
    def test_edit_details_from_stdin(self, todo_file, monkeypatch):
        _write(todo_file, SAMPLE_DATA)
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(
            "Updated multi-line\n\n- New item\n",
        ))
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "1", "--details-from-stdin",
        ])
        result = _read(todo_file)
        step1 = [i for i in result if i["id"] == 1][0]
        assert "Updated multi-line" in step1["details"]
        assert "- New item" in step1["details"]
        assert step1["name"] == SAMPLE_DATA[0]["name"]

    def test_update_specific_fields(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "2",
            "--step-name", "Updated name",
        ])
        result = _read(todo_file)
        step2 = [i for i in result if i["id"] == 2][0]
        assert step2["name"] == "Updated name"
        # Unchanged fields remain
        assert step2["details"] == "Do the second thing"
        assert step2["completed_at"] == ""

    def test_unspecified_fields_unchanged(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        original = SAMPLE_DATA[0].copy()
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "1",
            "--details", "New details",
        ])
        result = _read(todo_file)
        step1 = [i for i in result if i["id"] == 1][0]
        assert step1["name"] == original["name"]
        assert step1["completed_at"] == original["completed_at"]
        assert step1["commit_title"] == original["commit_title"]
        assert step1["details"] == "New details"

    def test_id_not_found_fails(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "edit",
                "--id", "999",
                "--step-name", "X",
            ])
        assert exc.value.code == 1

    def test_edit_skip_commit_auto(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "2",
            "--skip-commit", "auto",
        ])
        result = _read(todo_file)
        step2 = [i for i in result if i["id"] == 2][0]
        assert step2["skip_commit"] == "auto"
        assert step2["name"] == "Second step"

    def test_edit_skip_commit_true(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "2",
            "--skip-commit", "true",
        ])
        result = _read(todo_file)
        step2 = [i for i in result if i["id"] == 2][0]
        assert step2["skip_commit"] == "true"

    def test_edit_skip_commit_false_clears_key(self, todo_file):
        data = [dict(SAMPLE_DATA[1], skip_commit="auto")]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "1",
            "--skip-commit", "false",
        ])
        result = _read(todo_file)
        assert "skip_commit" not in result[0]


# -----------------------------------------------------------------------
# edit --completed-at now
# -----------------------------------------------------------------------
class TestEditCompletedAtNow:
    def test_edit_completed_at_now(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "2",
            "--completed-at", "now",
        ])
        result = _read(todo_file)
        step2 = [i for i in result if i["id"] == 2][0]
        assert step2["completed_at"].startswith("2026-")

    def test_edit_completed_at_explicit_value(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "edit",
            "--id", "2",
            "--completed-at", "2026-01-01T00:00:00",
        ])
        result = _read(todo_file)
        step2 = [i for i in result if i["id"] == 2][0]
        assert step2["completed_at"] == "2026-01-01T00:00:00"


# -----------------------------------------------------------------------
# append --completed-at now
# -----------------------------------------------------------------------
class TestAppendCompletedAtNow:
    def test_append_completed_at_now(self, todo_file):
        _write(todo_file, [])
        todo_helper.main([
            "--todo-file", str(todo_file), "append",
            "--step-name", "Task done now",
            "--details", "Details",
            "--completed-at", "now",
        ])
        result = _read(todo_file)
        assert result[0]["completed_at"].startswith("2026-")


# -----------------------------------------------------------------------
# insert
# -----------------------------------------------------------------------
class TestInsert:
    @pytest.mark.parametrize(
        ("anchor", "position", "index"),
        [
            ("--before", "1", 0), ("--after", "1", 1), ("--after", "3", 3),
            ("--before", "2", 1), ("--after", "2", 2),
            ("--before", "Step-2/5", 1), ("--after", "Step-2/5", 2),
            ("--before", "STEP 2/ignored", 1), ("--after", "STEP 2/ignored", 2),
            ("--before", "STEP 2/5", 1), ("--after", "STEP 2/5", 2),
        ],
    )
    def test_insert_by_spec_name(self, todo_file, monkeypatch, anchor, position, index):
        monkeypatch.setattr(todo_helper, "resolve_spec_dir", lambda name: todo_file.parent)
        _write(todo_file, SAMPLE_DATA)

        todo_helper.main([
            "insert", "my-topic", anchor, position,
            "--step-name", "Inserted", "--details", "Details",
        ])

        entry = {"name": "Inserted", "details": "Details", "completed_at": "", "commit_title": ""}
        expected = [*SAMPLE_DATA[:index], entry, *SAMPLE_DATA[index:]]
        assert _read(todo_file) == [
            dict(item, id=number) for number, item in enumerate(expected, 1)
        ]

    @pytest.mark.parametrize(
        ("anchors", "items", "exit_code"),
        [
            ([], SAMPLE_DATA, 2),
            (["--before", "1", "--after", "2"], SAMPLE_DATA, 2),
            (["--before", "0"], SAMPLE_DATA, 2),
            (["--after", "4"], SAMPLE_DATA, 1),
            (["--before", "Step-4/5"], SAMPLE_DATA, 1),
            (["--after", "STEP 0/5"], SAMPLE_DATA, 2),
            (["--before", "1"], [], 1),
        ],
    )
    def test_invalid_anchor_keeps_file(self, todo_file, anchors, items, exit_code):
        _write(todo_file, items)
        original = todo_file.read_bytes()
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "insert", *anchors,
                "--step-name", "Inserted", "--details", "Details",
            ])
        assert exc.value.code == exit_code
        assert todo_file.read_bytes() == original

    @pytest.mark.parametrize("action", ["commit", "rollback"])
    def test_insert_inside_transaction(self, todo_file, monkeypatch, action):
        import io

        _write(todo_file, SAMPLE_DATA)
        original = todo_file.read_bytes()
        locator = ["--todo-file", str(todo_file)]
        details = "First line\nSecond line\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(details))
        todo_helper.main(["transaction", "start", *locator])
        todo_helper.main([
            "insert", "--before", "2", "--step-name", "Inserted",
            "--details-from-stdin", "--skip-commit", "auto",
            "--completed-at", "2026-01-03", "--commit-title", "feat: inserted",
            *locator,
        ])

        entry = {
            "name": "Inserted", "details": details, "completed_at": "2026-01-03",
            "commit_title": "feat: inserted", "skip_commit": "auto",
        }
        expected = [SAMPLE_DATA[0], entry, *SAMPLE_DATA[1:]]
        assert _read(todo_file) == expected
        todo_helper.main(["transaction", action, *locator])

        if action == "rollback":
            assert todo_file.read_bytes() == original
        else:
            assert _read(todo_file) == [
                dict(item, id=number) for number, item in enumerate(expected, 1)
            ]
        assert not todo_file.with_suffix(".json.lock").exists()


# -----------------------------------------------------------------------
# move
# -----------------------------------------------------------------------
class TestMove:
    @pytest.mark.parametrize("selector", ["2", "Step-2/5", "STEP 2/5", "STEP 2/ignored"])
    @pytest.mark.parametrize("flag", ["--from", "--to"])
    def test_swap_by_position(self, todo_file, selector, flag):
        _write(todo_file, SAMPLE_DATA)
        other_flag = "--to" if flag == "--from" else "--from"
        todo_helper.main([
            "move", "--todo-file", str(todo_file), flag, selector, other_flag, "1",
        ])
        assert _read(todo_file) == [SAMPLE_DATA[1], SAMPLE_DATA[0], SAMPLE_DATA[2]]

    def test_swap_by_spec_name_preserves_full_entries(self, todo_file, monkeypatch, capsys):
        monkeypatch.setattr(
            todo_helper, "resolve_spec_dir", lambda name: todo_file.parent,
        )
        _write(todo_file, SAMPLE_DATA)

        todo_helper.main(["move", "my-topic", "--from", "1", "--to", "3"])

        swapped = [SAMPLE_DATA[2], SAMPLE_DATA[1], SAMPLE_DATA[0]]
        assert _read(todo_file) == swapped
        todo_helper.main(["show", "my-topic"])
        assert json.loads(capsys.readouterr().out) == [
            dict(item, id=index) for index, item in enumerate(swapped, 1)
        ]

    @pytest.mark.parametrize(
        ("source", "target", "exit_code"),
        [
            ("2", "2", None), ("4", "4", 1), ("1", "4", 1), ("0", "1", 2),
            ("Step-4/5", "1", 1), ("1", "STEP 0/5", 2),
        ],
    )
    def test_invalid_or_same_position_keeps_file(self, todo_file, source, target, exit_code):
        todo_file.write_text(json.dumps(SAMPLE_DATA), encoding="utf-8")
        original = todo_file.read_bytes()
        arguments = ["move", "--from", source, "--to", target, "--todo-file", str(todo_file)]

        if exit_code is None:
            todo_helper.main(arguments)
        else:
            with pytest.raises(SystemExit) as exc:
                todo_helper.main(arguments)
            assert exc.value.code == exit_code

        assert todo_file.read_bytes() == original

    @pytest.mark.parametrize("action", ["commit", "rollback"])
    def test_transaction_completion(self, todo_file, action):
        _write(todo_file, SAMPLE_DATA)
        original = todo_file.read_bytes()
        locator = ["--todo-file", str(todo_file)]
        todo_helper.main(["transaction", "start", *locator])
        todo_helper.main([*locator, "move", "--from", "3", "--to", "1"])

        swapped = [SAMPLE_DATA[2], SAMPLE_DATA[1], SAMPLE_DATA[0]]
        assert _read(todo_file) == swapped
        todo_helper.main(["transaction", action, *locator])

        if action == "rollback":
            assert todo_file.read_bytes() == original
        else:
            assert _read(todo_file) == [
                dict(item, id=index) for index, item in enumerate(swapped, 1)
            ]
        assert not todo_file.with_suffix(".json.lock").exists()


# -----------------------------------------------------------------------
# renumber
# -----------------------------------------------------------------------
class TestRenumber:
    @pytest.mark.parametrize("by_spec_name", [True, False])
    def test_repair_ids_and_preserve_payload(self, todo_file, monkeypatch, by_spec_name):
        monkeypatch.setattr(todo_helper, "resolve_spec_dir", lambda name: todo_file.parent)
        missing_id = {key: value for key, value in SAMPLE_DATA[0].items() if key != "id"}
        items = [
            missing_id,
            dict(SAMPLE_DATA[1], id=None, skip_commit="auto", extra={"labels": ["new"]}),
            dict(SAMPLE_DATA[2], id="legacy"),
            dict(SAMPLE_DATA[1], id="legacy"),
        ]
        _write(todo_file, items)
        argv = ["renumber", "topic"] if by_spec_name else [
            "--todo-file", str(todo_file), "renumber",
        ]

        todo_helper.main(argv)

        assert _read(todo_file) == [
            dict(item, id=index) for index, item in enumerate(items, 1)
        ]
        numbered = todo_file.read_bytes()
        todo_helper.main(argv)
        assert todo_file.read_bytes() == numbered

    def test_empty_array(self, todo_file):
        _write(todo_file, [])
        todo_helper.main(["renumber", "--todo-file", str(todo_file)])
        assert _read(todo_file) == []

    @pytest.mark.parametrize("contents", ["", "{", "{}", "[null]", "[{}]"])
    def test_reject_invalid_contents(self, todo_file, contents):
        todo_file.write_text(contents, encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            todo_helper.main(["renumber", "--todo-file", str(todo_file)])
        assert exc.value.code == 1
        assert todo_file.read_text(encoding="utf-8") == contents

    def test_reject_invalid_skip_commit(self, todo_file):
        _write(todo_file, [dict(SAMPLE_DATA[0], skip_commit="invalid")])
        original = todo_file.read_bytes()
        with pytest.raises(SystemExit) as exc:
            todo_helper.main(["renumber", "--todo-file", str(todo_file)])
        assert exc.value.code == 1
        assert todo_file.read_bytes() == original

    def test_reject_missing_file(self, todo_file):
        with pytest.raises(SystemExit) as exc:
            todo_helper.main(["renumber", "--todo-file", str(todo_file)])
        assert exc.value.code == 1
        assert not todo_file.exists()

    def test_reject_open_transaction(self, todo_file, caplog):
        _write(todo_file, SAMPLE_DATA)
        original = todo_file.read_bytes()
        locator = ["--todo-file", str(todo_file)]
        todo_helper.main(["transaction", "start", *locator])
        todo_helper.main(["move", "--from", "3", "--to", "1", *locator])
        pending = todo_file.read_bytes()

        with pytest.raises(SystemExit) as exc:
            todo_helper.main(["renumber", *locator])

        assert exc.value.code == 1
        assert "transaction commit" in caplog.text
        assert todo_file.read_bytes() == pending
        assert todo_file.with_suffix(".json.lock").read_bytes() == original


# -----------------------------------------------------------------------
# --id selectors
# -----------------------------------------------------------------------
class TestStepSelector:
    @pytest.mark.parametrize(("command", "flags"), [
        ("show", []),
        ("edit", ["--step-name", "Updated step"]),
        ("complete", []),
        ("remove", []),
    ])
    @pytest.mark.parametrize("label", [
        "step-2", "step-2/5", "STEP-2", "STEP-2/5",
        "step 2", "step 2/5", "STEP 2", "STEP 2/5", "Step 2/5",
        "STEP 2/0", "step-2/", "STEP-2/unknown", "step-2/3/4",
    ])
    def test_label_matches_numeric_id(self, todo_file, command, flags, label, capsys, monkeypatch):
        monkeypatch.setattr(todo_helper, "local_iso_timestamp", lambda: "2026-01-03T12:00:00+08:00")
        argv = [command, "--todo-file", str(todo_file), *flags, "--id"]
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([*argv, "2"])
        expected_output = capsys.readouterr().out
        expected_file = todo_file.read_bytes()
        _write(todo_file, SAMPLE_DATA)

        todo_helper.main([*argv, label])

        assert capsys.readouterr().out == expected_output
        assert todo_file.read_bytes() == expected_file

    @pytest.mark.parametrize("command", ["edit", "complete", "remove"])
    @pytest.mark.parametrize(("value", "exit_code"), [
        (None, 2), ("", 2), ("0", 2), ("step-0", 2), ("step-１", 2),
        ("step-/5", 2), ("step-4/5", 1),
        ("STEP 0", 2), ("STEP2", 2), ("STEP 4/5", 1),
    ])
    def test_invalid_mutation_selector_preserves_file(self, todo_file, command, value, exit_code):
        _write(todo_file, SAMPLE_DATA)
        original = todo_file.read_bytes()
        selector = [] if value is None else ["--id", value]
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([command, "--todo-file", str(todo_file), *selector])
        assert exc.value.code == exit_code
        assert todo_file.read_bytes() == original


# -----------------------------------------------------------------------
# remove
# -----------------------------------------------------------------------
class TestRemove:
    def test_remove_by_id(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "remove",
            "--id", "2",
        ])
        result = _read(todo_file)
        assert len(result) == 2
        ids = [i["id"] for i in result]
        assert ids == [1, 2]
        assert result[1]["name"] == "Third step"

    def test_id_not_found_fails(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file), "remove",
                "--id", "999",
            ])
        assert exc.value.code == 1


# -----------------------------------------------------------------------
# show
# -----------------------------------------------------------------------
class TestShow:
    def test_show_all_items_json(self, todo_file, capsys):
        data = [dict(SAMPLE_DATA[0], id="old-custom-id"), *SAMPLE_DATA[1:]]
        _write(todo_file, data)
        original = todo_file.read_bytes()
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result == [dict(item, id=index) for index, item in enumerate(data, 1)]
        assert todo_file.read_bytes() == original

    def test_show_done_filter(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show", "--done",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert len(result) == 2
        assert all(i["completed_at"] for i in result)

    def test_show_undone_filter(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show", "--undone",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert len(result) == 1
        assert result[0]["id"] == 2

    def test_show_by_id(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show", "--id", "2",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert len(result) == 1
        assert result[0]["id"] == 2
        assert result[0]["name"] == "Second step"

    def test_show_by_id_json(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--id", "1", "--format", "json",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_show_by_id_not_found(self, todo_file, caplog):
        _write(todo_file, SAMPLE_DATA)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc:
                todo_helper.main([
                    "--todo-file", str(todo_file), "show",
                    "--id", "999",
                ])
        assert exc.value.code == 1
        assert "999" in caplog.text

    def test_show_by_id_ignores_done_filter(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--id", "2", "--done",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert len(result) == 1
        assert result[0]["id"] == 2

    def test_show_by_id_markdown(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--id", "1", "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "1. ✅ step-1/3\n" in out
        assert "step-2" not in out

    def test_done_and_undone_mutual_exclusion(self, todo_file):
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit):
            todo_helper.main([
                "--todo-file", str(todo_file), "show",
                "--done", "--undone",
            ])

    def test_show_format_json(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA[:1])
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "json",
        ])
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result[0]["id"] == 1

    def test_show_format_markdown_done(self, todo_file, capsys):
        data = [SAMPLE_DATA[0]]  # completed item
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "1. ✅ step-1/1\n" in out
        assert "   - name: First step\n" in out
        assert "completed_at:" in out
        assert "commit_title:" in out

    def test_show_format_markdown_undone(self, todo_file, capsys):
        data = [SAMPLE_DATA[1]]  # incomplete item
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "1. 🔲 step-1/1\n" in out
        assert "   - name: Second step\n" in out
        assert "completed_at:" not in out
        assert "commit_title:" not in out

    def test_show_markdown_numbered_list(self, todo_file, capsys):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "1. ✅ step-1/3\n" in out
        assert "2. 🔲 step-2/3\n" in out
        assert "3. ✅ step-3/3\n" in out

    @pytest.mark.parametrize(
        ("flag", "label"), [("--done", "step-3/3"), ("--undone", "step-2/3")],
    )
    def test_filtered_markdown_uses_full_total(self, todo_file, capsys, flag, label):
        _write(todo_file, SAMPLE_DATA)
        todo_helper.main(["--todo-file", str(todo_file), "show", flag, "--format", "markdown"])
        assert label in capsys.readouterr().out

    def test_show_markdown_empty_fields_skipped(
        self, todo_file, capsys,
    ):
        data = [{
            "id": "s1", "name": "Test",
            "details": "", "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "1. 🔲 step-1/1\n" in out
        assert "   - name: Test\n" in out
        assert "details:" not in out
        assert "completed_at:" not in out
        assert "commit_title:" not in out

    def test_show_skip_commit_when_not_false(
        self, todo_file, capsys,
    ):
        data = [{
            "id": "s1", "name": "Test",
            "details": "D", "completed_at": "", "commit_title": "",
            "skip_commit": "auto",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "skip_commit: auto" in out

        data[0]["skip_commit"] = "true"
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "skip_commit: true" in out

    def test_show_skip_commit_false_omitted(
        self, todo_file, capsys,
    ):
        data = [{
            "id": "s1", "name": "Test",
            "details": "D", "completed_at": "", "commit_title": "",
            "skip_commit": "false",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "skip_commit" not in out

        data[0].pop("skip_commit")
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "skip_commit" not in out

    def test_show_markdown_no_wrap_by_default(
        self, todo_file, capsys,
    ):
        long_details = "word " * 30  # ~150 chars
        data = [{
            "id": "s1", "name": "Test",
            "details": long_details.strip(),
            "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        detail_lines = [
            line for line in out.split("\n")
            if "details:" in line or "word" in line
        ]
        assert len(detail_lines) == 1
        assert detail_lines[0].startswith("   - details: word")

    def test_show_markdown_wrap(
        self, todo_file, capsys,
    ):
        long_details = "word " * 30  # ~150 chars
        data = [{
            "id": "s1", "name": "Test",
            "details": long_details.strip(),
            "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown", "--wrap",
        ])
        out = capsys.readouterr().out
        detail_lines = [
            line for line in out.split("\n")
            if "details:" in line
            or (line.startswith("              ") and "word" in line)
        ]
        assert len(detail_lines) > 1
        for line in out.split("\n"):
            assert len(line) <= 80

    def test_show_markdown_multiline_details(
        self, todo_file, capsys,
    ):
        details = "First line\nSecond line\nThird line"
        data = [{
            "id": "s1", "name": "Test",
            "details": details,
            "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown",
        ])
        out = capsys.readouterr().out
        assert "   - details: |\n" in out
        assert "       First line\n" in out
        assert "       Second line\n" in out
        assert "       Third line" in out

    def test_show_markdown_multiline_details_wrap(
        self, todo_file, capsys,
    ):
        details = "First line\nSecond line\nThird line"
        data = [{
            "id": "s1", "name": "Test",
            "details": details,
            "completed_at": "", "commit_title": "",
        }]
        _write(todo_file, data)
        todo_helper.main([
            "--todo-file", str(todo_file), "show",
            "--format", "markdown", "--wrap",
        ])
        out = capsys.readouterr().out
        assert "   - details: |\n" in out
        assert "       First line\n" in out
        assert "       Second line\n" in out
        assert "       Third line" in out
        for line in out.split("\n"):
            assert len(line) <= 80


# -----------------------------------------------------------------------
# remove-undone
# -----------------------------------------------------------------------
class TestRemoveUndone:
    @pytest.mark.parametrize("command", ["remove-undone", "remove_undone"])
    def test_preserves_completed_items_and_is_idempotent(self, todo_file, command):
        _write(todo_file, SAMPLE_DATA)
        args = [command, "--todo-file", str(todo_file)]

        todo_helper.main(args)

        assert _read(todo_file) == [
            dict(SAMPLE_DATA[0], id=1), dict(SAMPLE_DATA[2], id=2),
        ]
        todo_file.write_bytes(todo_file.read_bytes().rstrip())
        original = todo_file.read_bytes()
        todo_helper.main(args)
        assert todo_file.read_bytes() == original

    def test_removes_all_unfinished_items(self, todo_file, monkeypatch):
        _write(todo_file, [SAMPLE_DATA[1]])
        monkeypatch.setattr(
            todo_helper, "resolve_spec_dir", lambda name: todo_file.parent,
        )

        todo_helper.main(["remove-undone", "my-topic"])

        assert _read(todo_file) == []

    def test_invalid_json_fails_without_rewriting(self, todo_file):
        original = b"[invalid"
        todo_file.write_bytes(original)

        with pytest.raises(SystemExit) as error:
            todo_helper.main(["remove-undone", "--todo-file", str(todo_file)])

        assert error.value.code == 1
        assert todo_file.read_bytes() == original


# -----------------------------------------------------------------------
# Help flag
# -----------------------------------------------------------------------
class TestHelp:
    def test_main_help(self):
        with pytest.raises(SystemExit) as exc:
            todo_helper.main(["-h"])
        assert exc.value.code == 0

    def test_main_help_long(self, capsys):
        with pytest.raises(SystemExit) as exc:
            todo_helper.main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Subcommands:" in out

    def test_no_args_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([])
        assert exc.value.code == 0
        err = capsys.readouterr().err
        assert "Subcommands:" in err

    def test_subcmd_help_shows_subcmd_usage(self, capsys, todo_file):
        """--help after a subcommand shows subcommand-specific help."""
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file),
                "edit", "--help",
            ])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "edit" in out
        assert "Subcommands:" not in out

    def test_subcmd_help_short_flag(self, capsys, todo_file):
        """Short -h after a subcommand shows subcommand-specific help."""
        _write(todo_file, SAMPLE_DATA)
        with pytest.raises(SystemExit) as exc:
            todo_helper.main([
                "--todo-file", str(todo_file),
                "append", "-h",
            ])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "append" in out
        assert "Subcommands:" not in out


class TestHoistLocatorFlags:
    def test_hoists_todo_file_from_end(self):
        assert todo_helper._hoist_locator_flags([
            "edit", "--id", "3", "--todo-file", "todo.json",
        ]) == ["--todo-file", "todo.json", "edit", "--id", "3"]

    def test_preserves_leading_name(self):
        assert todo_helper._hoist_locator_flags([
            "edit", "spec", "--id", "3",
        ]) == ["edit", "spec", "--id", "3"]

    def test_leaves_bare_name_in_place(self):
        # Bare --name must not steal the subcommand as its value.
        assert todo_helper._hoist_locator_flags([
            "edit", "--id", "3", "--name",
        ]) == ["edit", "--id", "3", "--name"]

    def test_leaves_bare_todo_file_in_place(self):
        assert todo_helper._hoist_locator_flags([
            "show", "--todo-file",
        ]) == ["show", "--todo-file"]

    def test_hoists_equals_form(self):
        assert todo_helper._hoist_locator_flags([
            "edit", "--id", "3", "--todo-file=todo.json",
        ]) == ["--todo-file=todo.json", "edit", "--id", "3"]

    def test_does_not_steal_option_values(self):
        # --todo-file is the commit-title value, not a locator flag.
        assert todo_helper._hoist_locator_flags([
            "edit", "spec", "--id", "3",
            "--commit-title", "--todo-file",
        ]) == [
            "edit", "spec", "--id", "3",
            "--commit-title", "--todo-file",
        ]

    def test_does_not_steal_equals_option_value(self):
        assert todo_helper._hoist_locator_flags([
            "edit", "spec", "--commit-title=--todo-file",
        ]) == ["edit", "spec", "--commit-title=--todo-file"]


class TestSubcommandHelp:
    """Tests for subcommand help working without a todo locator."""

    def test_validate_help_exits_0(self, capsys):
        """validate -h should show help and exit 0."""
        with pytest.raises(SystemExit) as exc_info:
            todo_helper.main(["validate", "-h"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "validate" in out.lower()

    def test_append_help_exits_0(self, capsys):
        """append -h should show usage and exit 0."""
        with pytest.raises(SystemExit) as exc_info:
            todo_helper.main(["append", "-h"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "--id" not in out

    def test_show_help_exits_0(self, capsys):
        """show -h should show usage and exit 0."""
        with pytest.raises(SystemExit) as exc_info:
            todo_helper.main(["show", "-h"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "--format" in out

    def test_no_locator_errors(self, capsys):
        """Without a name or --todo-file, error with exit 2."""
        with pytest.raises(SystemExit) as exc_info:
            todo_helper.main(["validate"])
        assert exc_info.value.code == 2
        assert "<spec-name>" in capsys.readouterr().err
