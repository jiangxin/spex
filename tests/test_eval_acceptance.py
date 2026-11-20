"""Offline checks for the Python CLI acceptance task-ID contract."""

import json

import pytest


def task(task_id, *, completed_at="", details=None):
    return {
        "id": task_id,
        "name": f"Add option {task_id}",
        "details": details or f"Implement and test option {task_id}.",
        "completed_at": completed_at,
        "commit_title": "",
    }


def write_spec(repo, name, tasks):
    spec_dir = repo / ".spex" / "specs" / name
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("Plan the greeting options.\n", encoding="utf-8")
    (spec_dir / "meta.json").write_text(json.dumps({"name": "greeting"}), encoding="utf-8")
    (spec_dir / "todo.json").write_text(json.dumps(tasks), encoding="utf-8")


@pytest.mark.parametrize(("ids", "valid"), [
    (["step-1", "step-2"], True),
    ([1, 2], True),
    (["1", "2"], False),
    (["step-1"], False),
    ([1], False),
    ([1, 2, 3], False),
    ([1, 3], False),
    ([0, 1], False),
    ([1, "step-2"], False),
    ([2, 1], False),
    ([True, 2], False),
])
def test_valid_task_ids_accepts_step_and_integer_forms(acceptance_checker, ids, valid):
    assert acceptance_checker.valid_task_ids(ids, 2) is valid


@pytest.mark.parametrize(("clause", "expected"), [
    ("Do not add `--prefix` or `--suffix`.", set()),
    ("Must not support `--suffix`.", set()),
    ("`--features` are not required.", set()),
    ("Do not remove `--prefix`.", {"--prefix"}),
    ("Do not drop `--suffix`.", {"--suffix"}),
    ("Keep `--upper`.", {"--upper"}),
])
def test_active_options_distinguishes_negated_requirements(acceptance_checker, clause, expected):
    spec = f"<!-- spex:begin:requirement -->\n- {clause}"
    assert acceptance_checker.active_options(spec) == expected


def test_plan_checks_accepts_renumbered_integer_ids(acceptance_checker, tmp_path):
    write_spec(tmp_path, "2000-01-01-00-02-new-plan", [task(1), task(2)])
    checks = acceptance_checker.plan_checks(tmp_path, "new-plan")
    assert checks["valid-task-identifiers"] is True


def test_plan_checks_rejects_string_integer_ids(acceptance_checker, tmp_path):
    write_spec(tmp_path, "2000-01-01-00-02-new-plan", [task("1"), task("2")])
    checks = acceptance_checker.plan_checks(tmp_path, "new-plan")
    assert checks["valid-task-identifiers"] is False


def test_modify_plan_checks_accepts_renumbered_integer_ids(acceptance_checker, tmp_path):
    write_spec(tmp_path, acceptance_checker.FORMAT, [
        task(1, details="Keep the existing --upper option."),
        task(2, details="Add the --punctuation option."),
    ])
    checks = acceptance_checker.plan_checks(tmp_path, "modify-plan")
    assert checks["valid-task-identifiers"] is True


def test_modify_plan_checks_rejects_string_integer_ids(acceptance_checker, tmp_path):
    write_spec(tmp_path, acceptance_checker.FORMAT, [
        task("1", details="Keep the existing --upper option."),
        task("2", details="Add the --punctuation option."),
    ])
    checks = acceptance_checker.plan_checks(tmp_path, "modify-plan")
    assert checks["valid-task-identifiers"] is False


def test_modify_path_plan_checks_accepts_renumbered_integer_ids(acceptance_checker, tmp_path):
    write_spec(tmp_path, acceptance_checker.FORMAT, [task(1), task(2)])
    checks = acceptance_checker.modify_path_plan_checks(tmp_path, "modify-targeted")
    assert checks["valid-task-identifiers"] is True


def test_modify_path_plan_checks_rejects_string_integer_ids(acceptance_checker, tmp_path):
    write_spec(tmp_path, acceptance_checker.FORMAT, [task("1"), task("2")])
    checks = acceptance_checker.modify_path_plan_checks(tmp_path, "modify-targeted")
    assert checks["valid-task-identifiers"] is False


def test_decoration_checks_accepts_renumbered_integer_ids(
    acceptance_checker, tmp_path, monkeypatch
):
    write_spec(tmp_path, acceptance_checker.DECORATION, [
        task(1, completed_at="2000-01-02T00:00:00+00:00"),
        task(2, completed_at="2000-01-02T00:00:00+00:00"),
        task(3),
    ])
    monkeypatch.setattr(acceptance_checker, "output_is", lambda *args, **kwargs: True)
    monkeypatch.setattr(acceptance_checker, "commits_ordered", lambda *args, **kwargs: True)
    monkeypatch.setattr(acceptance_checker, "clean_worktree", lambda *args, **kwargs: True)
    checks = acceptance_checker.decoration_checks(tmp_path, "all-decoration")
    assert checks["expected-completed-steps"] is True


def test_decoration_checks_rejects_string_integer_ids(
    acceptance_checker, tmp_path, monkeypatch
):
    write_spec(tmp_path, acceptance_checker.DECORATION, [
        task("1", completed_at="2000-01-02T00:00:00+00:00"),
        task("2", completed_at="2000-01-02T00:00:00+00:00"),
        task(3),
    ])
    monkeypatch.setattr(acceptance_checker, "output_is", lambda *args, **kwargs: True)
    monkeypatch.setattr(acceptance_checker, "commits_ordered", lambda *args, **kwargs: True)
    monkeypatch.setattr(acceptance_checker, "clean_worktree", lambda *args, **kwargs: True)
    checks = acceptance_checker.decoration_checks(tmp_path, "all-decoration")
    assert checks["expected-completed-steps"] is False
