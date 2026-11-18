"""Offline checks for structured execution diagnostics."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "spex"))
try:
    import issues
    import performance
finally:
    sys.path.pop(0)


def stamp(value):
    return performance.timestamp(value)


def command(name, subcommand, exit_code, turn=1, started_at=None, argv=None):
    entry = {
        "turn": turn, "command": name, "subcommand": subcommand,
        "exit_code": exit_code,
    }
    if started_at is not None:
        entry["started_at"] = started_at
    if argv is not None:
        entry["argv"] = argv
    return entry


def test_helper_identity_parses_spex_argv():
    assert issues.helper_identity(
        {"argv": ["/usr/bin/spex", "todo-helper", "edit", "--id", "step-1"]},
    ) == ("todo-helper", "edit")
    assert issues.helper_identity({"argv": ["spex", "review-helper", "status"]}) == (
        "review-helper", "status",
    )


def test_helper_identity_rejects_other_commands():
    assert issues.helper_identity({"argv": ["python3", "todo-helper", "edit"]}) is None
    assert issues.helper_identity({"argv": ["spex", "apply", "run"]}) is None
    assert issues.helper_identity({"argv": ["spex", "todo-helper"]}) is None
    assert issues.helper_identity({"argv": ["spex", "todo-helper", "--flag"]}) is None
    assert issues.helper_identity({"command": "todo-helper"}) is None


def test_turn_windows_use_host_stamps_only():
    data = {"turns": {
        "1": {"host": {"started_at": "2026-11-16T12:00:00+00:00",
                       "ended_at": "2026-11-16T12:10:00+00:00"}},
        "2": {"host": {"started_at": "not a stamp",
                       "ended_at": "2026-11-16T12:20:00+00:00"}},
        "bad": {"host": {}},
    }}
    assert issues.turn_windows(data) == {
        1: (stamp("2026-11-16T12:00:00+00:00"), stamp("2026-11-16T12:10:00+00:00")),
    }


def test_recovered_by_retry_requires_same_turn_and_identity():
    windows = {1: (stamp("2026-11-16T12:00:00+00:00"),
                   stamp("2026-11-16T12:10:00+00:00"))}
    retried = [
        command("todo-helper", "edit", 1, started_at="2026-11-16T12:01:00+00:00"),
        command("todo-helper", "edit", 0, started_at="2026-11-16T12:02:00+00:00"),
    ]
    assert issues.recovered_by_retry(0, retried, windows, 1) is True
    cross_turn = [
        command("todo-helper", "edit", 1, started_at="2026-11-16T12:01:00+00:00"),
        command("todo-helper", "edit", 0, turn=2,
                started_at="2026-11-16T12:02:00+00:00"),
    ]
    assert issues.recovered_by_retry(0, cross_turn, windows, 1) is False
    other_subcommand = [
        command("todo-helper", "append", 2, started_at="2026-11-16T12:01:00+00:00"),
        command("todo-helper", "edit", 0, started_at="2026-11-16T12:02:00+00:00"),
    ]
    assert issues.recovered_by_retry(0, other_subcommand, windows, 1) is False


def test_recovered_by_retry_ignores_exits_after_the_window():
    windows = {1: (stamp("2026-11-16T12:00:00+00:00"),
                   stamp("2026-11-16T12:10:00+00:00"))}
    commands = [
        command("todo-helper", "edit", 1),
        command("todo-helper", "edit", 0, started_at="2026-11-16T12:11:00+00:00"),
    ]
    assert issues.recovered_by_retry(0, commands, windows, 1) is False


def test_recovered_by_retry_matches_argv_identity():
    commands = [
        command("todo-helper", "edit", 1, argv=["spex", "todo-helper", "edit"]),
        command("todo-helper", "edit", 0, argv=["spex", "todo-helper", "edit"]),
    ]
    assert issues.recovered_by_retry(0, commands, {}, 1) is True


def test_recovered_by_retry_requires_the_same_operation_target():
    def targeted(name, subcommand, exit_code, spec, step, todo=None):
        entry = command(name, subcommand, exit_code)
        entry.update(spec=spec, step=step, todo_file_hash=todo)
        return entry

    commands = [
        targeted("todo-helper", "edit", 3, "demo", "step-2"),
        targeted("todo-helper", "edit", 0, "demo", "step-3"),
    ]
    assert issues.recovered_by_retry(0, commands, {}, 1) is False
    files = [
        targeted("todo-helper", "edit", 4, None, "step-1", "one"),
        targeted("todo-helper", "edit", 0, None, "step-1", "two"),
    ]
    assert issues.recovered_by_retry(0, files, {}, 1) is False
    same = [
        targeted("todo-helper", "edit", 5, None, "step-1", "two"),
        targeted("todo-helper", "edit", 0, None, "step-1", "two"),
    ]
    assert issues.recovered_by_retry(0, same, {}, 1) is True


def test_trial_issues_reports_script_exits_with_recovery():
    row = {
        "suite": "example", "case_id": "retry", "trial": "example/retry",
        "performance": {"spex_commands": [
            command("todo-helper", "edit", 2, started_at="2026-11-16T12:01:00+00:00"),
            command("todo-helper", "edit", 0, started_at="2026-11-16T12:02:00+00:00"),
        ]},
    }
    data = {"turns": {"1": {"host": {
        "started_at": "2026-11-16T12:00:00+00:00",
        "ended_at": "2026-11-16T12:10:00+00:00",
    }}}}
    result = issues.trial_issues(row, {"turn_results": [{"turn": 1}]}, {}, data)
    assert result == [{
        "case": "example/retry", "trial": "example/retry",
        "stage": "script", "kind": "script_exit",
        "message": "Turn 1: todo-helper edit exited with code 2",
        "turn": 1, "recovered": True,
        "evidence": ["example/retry/performance.json"],
        "command": "todo-helper edit", "exit_code": 2,
    }]


def test_trial_issues_exempts_the_expected_review_stop():
    row = {
        "suite": "example", "case_id": "review", "trial": "example/review",
        "performance": {"spex_commands": [
            command("review-helper", "entry", 1),
            command("review-helper", "entry", 0),
        ]},
    }
    metadata = {"turn_results": [{
        "turn": 1,
        "checks": [{"check_id": "review-failure-stop", "verdict": "pass"}],
    }]}
    assert issues.trial_issues(row, metadata, {}, {"turns": {}}) == []


def test_trial_issues_structures_host_and_judge_failures():
    row = {"suite": "example", "case_id": "broken", "trial": "example/broken"}
    metadata = {
        "verdict": "run_error", "error": "manual_host_timeout",
        "error_stage": "collect", "turn_results": [],
    }
    judge = {"verdict": "judge_error", "error": "bad_json", "attempt_errors": ["bad"]}
    data = {"turns": {"1": {"host": {
        "error": "host_timeout",
        "gaps": ["implausible_host_duration"],
        "command_failures": 2,
        "subagent_spawn_failures": 1,
        "subagent_failures": 1,
    }}}}
    result = issues.trial_issues(row, metadata, judge, data)
    assert {(item["stage"], item["kind"]) for item in result} == {
        ("host", "host_error"),
        ("host", "implausible_host_duration"),
        ("host", "command_failures"),
        ("host", "subagent_spawn_failures"),
        ("host", "subagent_failures"),
        ("collect", "run_error"),
        ("judge", "judge_error"),
    }
    assert all(item["case"] == "example/broken" for item in result)


def test_trial_issues_reports_only_recovered_judge_attempts():
    row = {"suite": "example", "case_id": "judged", "trial": "example/judged"}
    judge = {"verdict": "pass", "attempt_errors": ["invalid reference"]}
    result = issues.trial_issues(row, {"verdict": "pass"}, judge, {"turns": {}})
    assert [(item["kind"], item["recovered"]) for item in result] == [
        ("judge_attempt", True),
    ]


def test_trial_issues_keeps_only_residual_host_failure_counts():
    row = {
        "suite": "example", "case_id": "covered", "trial": "example/covered",
        "performance": {"spex_commands": [command("todo-helper", "edit", 2)]},
    }
    data = {"turns": {"1": {"host": {"command_failures": 4}}}}
    result = issues.trial_issues(row, {"turn_results": []}, {}, data)
    assert [(item["kind"], item["message"]) for item in result] == [
        ("script_exit", "Turn 1: todo-helper edit exited with code 2"),
        ("command_failures", "Turn 1: 3 other host command(s) failed"),
    ]
    covered = {"turns": {"1": {"host": {"command_failures": 1}}}}
    assert [
        item["kind"] for item in issues.trial_issues(row, {"turn_results": []}, {}, covered)
    ] == ["script_exit"]


def test_read_recorded_normalizes_and_skips_unsafe_entries(tmp_path):
    root = tmp_path / "_issues"
    root.mkdir()
    (root / "one.json").write_text(json.dumps({
        "suite": "example", "case_id": "x", "kind": "capacity",
        "message": "host refused a session", "stage": "host", "recovered": False,
    }), encoding="utf-8")
    (root / "broken.json").write_text("{not json", encoding="utf-8")
    (root / "no-message.json").write_text(json.dumps({"kind": "capacity"}),
                                          encoding="utf-8")
    (root / "list.json").write_text(json.dumps(["capacity"]), encoding="utf-8")
    (root / "huge.json").write_text("x" * (issues.MAX_RECORDED_BYTES + 1),
                                    encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"kind": "leak", "message": "leak"}), encoding="utf-8")
    (root / "linked.json").symlink_to(outside)
    assert issues.read_recorded(tmp_path) == [{
        "suite": "example", "case_id": "x", "kind": "capacity",
        "message": "host refused a session", "stage": "host", "recovered": False,
        "case": "example/x", "trial": None, "turn": None,
        "evidence": ["_issues/one.json"], "command": None, "exit_code": None,
    }]


def test_read_recorded_rejects_symlinked_directory(tmp_path):
    target = tmp_path / "records"
    target.mkdir()
    (target / "one.json").write_text(json.dumps({"kind": "capacity"}), encoding="utf-8")
    (tmp_path / "_issues").symlink_to(target, target_is_directory=True)
    assert issues.read_recorded(tmp_path) == []


def test_read_recorded_defaults_an_unknown_stage(tmp_path):
    root = tmp_path / "_issues"
    root.mkdir()
    (root / "one.json").write_text(json.dumps({
        "kind": "capacity", "message": "host refused a session", "stage": "bogus",
    }), encoding="utf-8")
    record = issues.read_recorded(tmp_path)[0]
    assert record["stage"] == "unknown"
    assert record["case"] == "unknown"
    assert record["recovered"] is None
