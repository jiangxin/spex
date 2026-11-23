"""Offline regression tests for the eval diagnostics pipeline."""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "spex"))
try:
    import evidence
    import native_trace
    import performance
    import run
    from transport import TransportError
finally:
    sys.path.pop(0)


def trace(*events):
    return "\n".join(json.dumps(event) for event in events)


def item(kind, **fields):
    return {"type": "item.completed", "item": {"type": kind, **fields}}


def test_host_metrics_keep_only_normalized_usage_and_activity():
    command = item("command_execution", id="item-1", command="PRIVATE", exit_code=1)
    raw = trace(
        command, command,
        item("collab_tool_call", id="item-2", tool="spawn_agent", status="completed"),
        item("collab_tool_call", id="item-3", tool="wait", status="completed",
             agents_states={"private-thread": {"status": "errored"}}),
        {"type": "turn.completed", "usage": {
            "input_tokens": 40, "cached_input_tokens": 25, "output_tokens": 8,
        }},
    )
    result = performance.host_metrics(raw, 1234, "adapter")
    assert result["trace"] == "complete"
    assert result["parent_usage"] == {
        "input_tokens": 40, "cached_input_tokens": 25, "output_tokens": 8,
        "reasoning_output_tokens": None,
    }
    assert result["commands"] == result["command_failures"] == 1
    assert result["subagent_starts"] == result["subagent_failures"] == 1
    assert result["model_requests"] is result["subagent_usage"] is None
    assert "PRIVATE" not in json.dumps(result)
    assert "private-thread" not in json.dumps(result)


def test_missing_and_partial_host_telemetry():
    absent = performance.host_metrics(None, None, "adapter")
    assert absent["trace"] == "missing"
    assert absent["commands"] is absent["duration_ms"] is absent["parent_usage"] is None
    raw = trace(item("collab_tool_call", tool="wait", status="completed")) + "\n{"
    partial = performance.host_metrics(raw.encode(), 1500, "runner", "timeout")
    assert partial["trace"] == "partial"
    assert partial["subagent_starts"] is None
    assert partial["duration_ms"] == 1500


def anchor(event, seconds, fields):
    return f"===== APPLY {event} ts=2026-11-11T10:00:{seconds:02}+08:00 {fields} ====="


def test_timeline_tracks_resumed_task_review_rounds_and_incomplete_spans(tmp_path):
    repo = tmp_path / "repo"
    debug = repo / ".spex/specs/example/debug.log"
    debug.parent.mkdir(parents=True)
    first = anchor("task begin", 1, "id=step-1 resume_phase=review")
    review = anchor("review begin", 3, "step=step-1 round=1 mode=full")
    lines = [
        first, first, review, review,
        anchor("review end", 5, "step=step-1 round=1 mode=full duration_ms=2000"),
        anchor("fix begin", 5, "step=step-1 round=1"),
        anchor("checks begin", 6, "step=step-1 count=2"),
        anchor("checks end", 6, "step=step-1 count=2 timed_count=2 duration_ms=800"),
        anchor("fix end", 7, "step=step-1 round=1 duration_ms=2000"),
        anchor("review begin", 8, "step=step-1 round=1 mode=delta"),
        anchor("review end", 9, "step=step-1 round=1 mode=delta duration_ms=1000"),
        anchor("review begin", 10, "step=step-1 round=2 mode=full"),
    ]
    debug.write_text("\n".join(lines) + "\n", encoding="utf-8")
    incomplete = performance.workflow_metrics(repo)["logs"][0]
    assert incomplete["tasks"][0]["status"] == incomplete["spans"][-1]["status"] == "interrupted"
    with debug.open("a", encoding="utf-8") as stream:
        stream.write("\n".join([
            anchor("review end", 11, "step=step-1 round=2 mode=full duration_ms=1000"),
            anchor("task done", 12, "id=step-1"),
            "===== BEGIN 2026-11-11T10:00:12+08:00 =====",
            "argv: spex prompt PRIVATE-ARGUMENT",
            "----- stdout -----",
            "PRIVATE-OUTPUT",
            "===== END exit=0 duration_ms=5 =====",
        ]))
    result = performance.workflow_metrics(repo)["logs"][0]
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["duration_ms"] == 9000
    assert result["tasks"][0]["implementation_and_commit_ms"] is None
    assert [(span["phase"], span["round"], span["mode"]) for span in result["spans"]] == [
        ("review", 1, "full"), ("fix", 1, None), ("checks", None, None),
        ("review", 1, "delta"), ("review", 2, "full"),
    ]
    assert result["commands"][0]["duration_ms"] == 5
    assert "PRIVATE" not in json.dumps(result)
    performance.update(tmp_path, repo=repo)
    old = performance.trial_summary(tmp_path, {})
    assert old["spex_commands"] == [{
        "turn": None, "command": "prompt", "subcommand": None,
        "started_at": None, "ended_at": None, "logged_at": "2026-11-11T10:00:12+08:00",
        "duration_ms": 5, "exit_code": 0, "elapsed_ms": None, "argv": None,
    }]


def test_old_trials_and_unreadable_logs_remain_reportable(tmp_path):
    repo = tmp_path / "repo"
    debug = repo / ".spex/debug.log"
    debug.parent.mkdir(parents=True)
    debug.write_bytes(b"\xff")
    assert "unreadable_debug_log" in performance.workflow_metrics(repo)["gaps"]
    old = performance.trial_summary(tmp_path, {"turn_results": [{}], "duration_ms": 45})
    assert old["host_turns"] == 1
    assert old["host_duration_ms"] is None
    assert old["automatic_total_ms"] == 45
    assert (old["duration_ms"], old["duration_s"], old["duration_source"]) == (
        45, 0.045, "automatic",
    )


@pytest.mark.parametrize(
    ("host_times", "automatic", "expected"),
    [
        ((1000, 2000), 9000, (3000, 3.0, "host")),
        ((0, 0), 9000, (0, 0.0, "host")),
        ((1000,), 9000, (9000, 9.0, "automatic")),
        ((1000, None), 9000, (9000, 9.0, "automatic")),
        ((1000, None), None, (None, None, "unknown")),
    ],
)
def test_summary_reports_case_duration_and_source(
    tmp_path, monkeypatch, host_times, automatic, expected,
):
    monkeypatch.setattr(run, "RUNS", tmp_path)
    sandbox = run.resolve_sandbox()
    output = sandbox / "suite" / "case"
    output.mkdir(parents=True)
    run.write_json(output / "trial.json", {
        "suite": "suite", "case_id": "case", "verdict": "pass",
        "turn_results": [{"turn": 1}, {"turn": 2}],
    })
    for turn, duration in enumerate(host_times, 1):
        host = performance.host_metrics(None, duration, "runner")
        performance.update(output, turn=turn, host=host)
    performance.update(output, automatic_total_ms=automatic)

    result = run.summarize_sandbox(sandbox)
    report = run.read_json(Path(result["report_json"]))
    metrics = report["trials"][0]["performance"]
    assert (metrics["duration_ms"], metrics["duration_s"], metrics["duration_source"]) == expected
    markdown = Path(result["report"]).read_text(encoding="utf-8")
    seconds = "unknown" if expected[1] is None else expected[1]
    assert f"| suite/case | 2 | {seconds} | {expected[2]} |" in markdown


@pytest.mark.parametrize(
    ("verdict", "duration", "source"),
    [("pending", None, "unknown"), ("run_error", 250, "host")],
)
def test_case_duration_with_unattempted_turns(tmp_path, monkeypatch, verdict, duration, source):
    monkeypatch.setattr(run, "RUNS", tmp_path)
    sandbox = run.resolve_sandbox()
    output = sandbox / "suite" / "case"
    output.mkdir(parents=True)
    run.write_json(output / "trial.json", {
        "suite": "suite", "case_id": "case", "verdict": verdict,
        "case": {"turns": [{}, {}]}, "turn_results": [{"turn": 1}],
    })
    performance.update(output, turn=1, host=performance.host_metrics(None, 250, "runner"))

    result = run.summarize_sandbox(sandbox)
    report = run.read_json(Path(result["report_json"]))
    metrics = report["trials"][0]["performance"]
    assert metrics["host_duration_ms"] == 250
    assert (metrics["duration_ms"], metrics["duration_source"]) == (duration, source)
    markdown = Path(result["report"]).read_text(encoding="utf-8")
    assert f"| suite/case | 1 | {performance.format_seconds(duration)} | {source} |" in markdown


def test_summary_renders_ordered_case_timeline(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path)
    sandbox = run.resolve_sandbox()
    output = sandbox / "suite" / "case"
    output.mkdir(parents=True)
    run.write_json(output / "trial.json", {
        "suite": "suite", "case_id": "case", "verdict": "pass",
        "turn_results": [{"turn": 1}, {"turn": 2}],
    })
    first = "2026-01-01T00:00:00+00:00"
    second = "2026-01-01T00:00:10+00:00"
    end = "2026-01-01T00:00:12+00:00"
    start_ns = performance.stamp_bounds(second)[0] + 10**9 + 1
    command = {"command": "apply-helper", "subcommand": "post-action", "duration_ms": 200,
               "start_ns": start_ns, "end_ns": start_ns + 200 * 10**6, "exit_code": 2,
               "argv": ["spex", "apply-helper", "post-action"]}
    host = performance.host_metrics(None, 2000, "runner", started_at=second, ended_at=end)
    performance.update(output, turn=2, native={"timing_events": [command]}, host=host)
    legacy = {"command": "list", "duration_ms": 7, "exit_code": 0,
              "at": "2026-01-01T00:00:01+00:00"}
    host = performance.host_metrics(None, 2000, "runner", started_at=first)
    performance.update(output, turn=1, native={"events": [legacy]}, host=host)

    result = run.summarize_sandbox(sandbox)
    metrics = run.read_json(Path(result["report_json"]))["trials"][0]["performance"]
    assert (metrics["case_started_at"], metrics["case_ended_at"]) == (first, end)
    assert metrics["case_elapsed_ms"] == 12000 and metrics["duration_ms"] == 4000
    assert [turn["index"] for turn in metrics["host_turns_timeline"]] == [1, 2]
    assert [cmd["turn"] for cmd in metrics["spex_commands"]] == [1, 2]
    listed, failed = metrics["spex_commands"]
    assert listed["started_at"] is listed["ended_at"] is listed["elapsed_ms"] is None
    assert failed["started_at"] == "2026-01-01T00:00:11.000000001+00:00"
    assert failed["exit_code"] == 2
    assert abs(failed["elapsed_ms"] - 11000) < 0.001
    markdown = Path(result["report"]).read_text(encoding="utf-8")
    markers = ["Case start", "Host turn 1 start", "`list`", "Host turn 2 start",
               "`apply-helper post-action`", "Host turn 2 end", "Case end"]
    indices = [markdown.index(marker) for marker in markers]
    assert indices == sorted(indices)
    assert "| 0.2 | 11.0 | 2 | spex apply-helper post-action |" in markdown
    assert (
        "| Host turn 1 end | unknown | unknown | unknown | 2.0 | unknown | unknown | — |"
    ) in markdown


@pytest.mark.parametrize("new_turn_has_command", [False, True])
def test_timeline_keeps_legacy_commands_in_partly_upgraded_trials(new_turn_has_command):
    source = "specs/example/debug.log"
    first_stamp = "2026-01-01T00:00:01+00:00"
    second_stamp = "2026-01-01T00:00:04+00:00"
    legacy = {"command": "list", "exit_code": 0, "duration_ms": 5}
    commands = [dict(legacy, logged_at=first_stamp)]
    recorded = []
    if new_turn_has_command:
        commands.append(dict(legacy, logged_at=second_stamp))
        recorded.append(dict(legacy, log="specs/example/trace.jsonl", at=second_stamp))
    turns = {1: {}, 2: {"spex_commands": recorded}}
    timeline = performance.command_timeline(turns, {
        "logs": [{"source": source, "commands": commands}],
    })
    assert [(command["turn"], command["logged_at"]) for command in timeline] == (
        [(None, first_stamp), (2, second_stamp)] if new_turn_has_command
        else [(None, first_stamp)]
    )


@pytest.mark.parametrize("separator", ["|", "\n", "\r"])
def test_timeline_rejects_unsafe_timestamp_separators(separator):
    value = f"2026-01-01{separator}00:00:01.000000001+00:00"
    assert performance.timestamp(value) is not None
    assert performance.report_stamp(value) is None
    precise = "2026-01-01T00:00:01.000000001+00:00"
    assert performance.report_stamp(precise) == precise


@pytest.mark.parametrize("fraction", ["1", "12345", "123456", "123456789"])
def test_timestamp_preserves_fractional_precision(fraction):
    value = f"2026-01-01T00:00:01.{fraction}+00:00"
    start, end = performance.stamp_bounds(value)
    assert end - start == 10 ** (9 - len(fraction)) - 1
    assert start % 10**9 == int(fraction.ljust(9, "0"))


def test_resumed_task_does_not_include_time_between_host_turns(tmp_path):
    debug = tmp_path / "repo/.spex/specs/example/debug.log"
    debug.parent.mkdir(parents=True)
    debug.write_text(anchor("task begin", 1, "id=step-1 resume_phase=implement") + "\n")
    host = performance.host_metrics(None, 1000, "adapter")
    performance.update(tmp_path, turn=1, repo=tmp_path / "repo", host=host)
    with debug.open("a", encoding="utf-8") as stream:
        stream.write("\n".join([
            anchor("task begin", 20, "id=step-1 resume_phase=review"),
            anchor("review begin", 21, "step=step-1 round=1 mode=full"),
            anchor("review end", 22, "step=step-1 round=1 mode=full duration_ms=1000"),
            anchor("task done", 23, "id=step-1"),
            "",
        ]))
    performance.update(tmp_path, turn=2, repo=tmp_path / "repo", host=host)
    tasks = performance.read_performance(tmp_path)["workflow"]["logs"][0]["tasks"]
    assert [(task["status"], task["duration_ms"]) for task in tasks] == [
        ("interrupted", None), ("complete", 2000),
    ]


def test_report_aggregates_only_available_matching_samples(tmp_path):
    rows = []
    samples = [
        (100, None, 1), (300, None, 1), (None, None, 1),
        (None, 500, 1), (None, 700, 1), (900, None, 2),
    ]
    for index, (duration, automatic_total_ms, jobs) in enumerate(samples, 1):
        output = tmp_path / str(index)
        output.mkdir()
        host = performance.host_metrics(None, duration, "adapter")
        performance.update(output, turn=1, host=host)
        performance.update(output, automatic_total_ms=automatic_total_ms)
        rows.append({
            "suite": "suite", "case_id": "case", "trial": str(index),
            "host": "codex", "model": "model", "collection": "automatic", "spex_ref": "abc",
            "execution": run.execution(jobs),
            "performance": performance.trial_summary(output, {"turn_results": [{}]}),
        })
    report = "\n".join(performance.report_lines(rows))
    assert "[metrics](1/performance.json)" in report
    assert "host duration for 2/5 samples, median 0.2 s, max 0.3 s" in report
    assert "automatic duration for 2/5 samples, median 0.6 s, max 0.7 s" in report
    assert "max 0.9 s" not in report


def test_timeout_keeps_host_duration_and_partial_metrics(tmp_path, monkeypatch):
    output = tmp_path / "trial"
    output.mkdir()
    repo = output / "repo"
    repo.mkdir()
    run.write_json(
        output / "trial.json", {"case": {"turns": [{"input": "continue"}]}, "session": ""},
    )

    def timeout(*args, **kwargs):
        raw = trace(item("command_execution", exit_code=1))
        raise TransportError("timeout", partial_events=raw)

    monkeypatch.setattr(run, "verify_trial_workspace", lambda _: None)
    monkeypatch.setattr(run, "codex_turn", timeout)
    with pytest.raises(TransportError, match="timeout"):
        run.drive(output, SimpleNamespace(repo=repo), SimpleNamespace(model="model", timeout=1))
    host = performance.read_performance(output)["turns"]["1"]["host"]
    assert host["trace"] == "partial"
    assert host["duration_ms"] >= 0
    assert host["error"] == "timeout"
    assert host["command_failures"] == 1


def test_turn_timing_uses_only_its_saved_events_and_legacy_flush_stamp(tmp_path):
    started_at = "2026-11-17T09:00:20.100000+08:00"
    host = performance.host_metrics(
        None, 1000, "adapter",
        started_at=started_at,
        ended_at="2026-11-17T09:00:21.100000+08:00",
    )
    start_ns = performance.stamp_bounds(started_at)[0]
    # The precheck BEGIN log is republished into the spec log on the next turn.
    stale = {"command": "create-helper", "subcommand": "precheck",
             "start_ns": start_ns - 20 * 10**9, "end_ns": start_ns - 19 * 10**9}
    current = {"command": "prompt", "subcommand": "apply",
               "start_ns": start_ns + 10**8, "end_ns": start_ns + 3 * 10**8}
    late = {"command": "list", "at": "2026-11-17T09:00:31.000000054+08:00",
            "duration_ms": 700}
    performance.update(tmp_path, turn=1, host={**host, "gaps": []},
                       native={"timing_events": [stale]})
    performance.update(tmp_path, turn=2, host={**host, "gaps": []},
                       native={"timing_events": [stale, current]})
    performance.update(tmp_path, turn=2, host={**host, "gaps": []},
                       native={"timing_events": [stale, current]})
    performance.update(tmp_path, turn=3, host={**host, "gaps": []},
                       native={"events": [late]})
    # A stale event ending 4s before `start` survives the window filter
    # (inside slack); with activity just past `ended_at` (also inside slack),
    # only the short-window span rule can flag the 1000ms host interval.
    # Widening the filter to `start[0]` would drop the stale event and hide
    # the mismatch from every rule.
    stale_at_boundary = {"command": "create-helper", "subcommand": "precheck",
                         "start_ns": start_ns - 4_900_000_000,
                         "end_ns": start_ns - 4 * 10**9}
    tail = {"command": "prompt", "subcommand": "apply",
            "start_ns": start_ns + 1_200_000_000,
            "end_ns": start_ns + 1_700_000_000}
    performance.update(tmp_path, turn=4, host={**host, "gaps": []},
                       native={"timing_events": [stale_at_boundary, tail]})
    turns = performance.read_performance(tmp_path)["turns"]
    assert turns["1"]["host"]["gaps"] == ["missing_turn_timing_evidence"]
    assert turns["2"]["host"]["gaps"] == []
    assert "implausible_host_duration" in turns["3"]["host"]["gaps"]
    assert turns["4"]["host"]["gaps"] == ["implausible_host_duration"]
    assert turns["4"]["spex_commands"] == [stale_at_boundary, tail]
    # Window filtering changes attribution only; reported commands stay complete.
    assert turns["1"]["spex_commands"] == [stale]
    assert turns["2"]["spex_commands"] == [stale, current]
    nano, end = performance.stamp_bounds("2026-11-17T09:00:31.000000054+08:00")
    assert nano == end and nano % 1000 == 54


CREATE_ANCHORS = [
    "===== CREATE prepare-spec ok name=eval-spec =====",
    "===== CREATE post-action ok name=eval-spec steps=2 =====",
]


def test_create_anchor_marks_log_recognized_without_events(tmp_path):
    repo = tmp_path / "repo"
    debug = repo / ".spex/specs/example/debug.log"
    debug.parent.mkdir(parents=True)
    debug.write_text("\n".join(CREATE_ANCHORS) + "\n", encoding="utf-8")
    metrics = performance.workflow_metrics(repo)
    assert metrics["gaps"] == []
    log = metrics["logs"][0]
    assert log["tasks"] == log["spans"] == log["routes"] == log["commands"] == []
    assert log["last_event_at"] is None


def test_apply_log_parsing_is_unchanged_by_create_anchors():
    apply_only = performance.parse_log(["\n".join([
        anchor("task begin", 1, "id=step-1"),
        anchor("route", 1, "id=step-1 result=phase7_no_findings"),
        anchor("task done", 2, "id=step-1"),
    ]) + "\n"])
    assert apply_only["gaps"] == []
    assert [(task["step"], task["duration_ms"]) for task in apply_only["tasks"]] == [
        ("step-1", 1000),
    ]
    assert apply_only["spans"] == apply_only["commands"] == []
    assert [route["result"] for route in apply_only["routes"]] == ["phase7_no_findings"]
    mixed = performance.parse_log(["\n".join([
        CREATE_ANCHORS[0], anchor("route", 3, "id=step-1 result=batch_fix"),
        CREATE_ANCHORS[1],
    ]) + "\n"])
    assert mixed["gaps"] == []
    assert mixed["tasks"] == mixed["spans"] == mixed["commands"] == []
    assert [route["result"] for route in mixed["routes"]] == ["batch_fix"]


def test_empty_log_still_reports_unrecognized_debug_log():
    assert performance.parse_log([""])["gaps"] == ["unrecognized_debug_log"]
    assert performance.parse_log(["\n\n"])["gaps"] == ["unrecognized_debug_log"]


def test_timeline_marks_spex_skill_turns_from_metadata():
    metadata = {
        "case": {"turns": [{"input": "/spex create a thing"}, {"input": "continue"}]},
        "turn_results": [{"turn": 1}, {"turn": 2}],
    }
    data = {"turns": {"1": {"host": {
        "started_at": "2026-01-01T00:00:00+00:00",
        "ended_at": "2026-01-01T00:00:04+00:00",
        "duration_ms": 4000,
    }}}}
    turns = performance.summarize_timeline(data, metadata, False)["host_turns_timeline"]
    assert [(turn["index"], turn["is_spex_skill"], turn["skill_input"]) for turn in turns] == [
        (1, True, "/spex create a thing"),
        (2, False, None),
    ]
    legacy = performance.summarize_timeline(data, {}, False)["host_turns_timeline"]
    assert [turn["is_spex_skill"] for turn in legacy] == [False]


def test_format_argv_cell_joins_truncates_and_escapes():
    assert performance.format_argv_cell(None) == "—"
    assert performance.format_argv_cell([]) == "—"
    assert performance.format_argv_cell(["spex", "todo-helper", "edit"]) == (
        "spex todo-helper edit"
    )
    assert performance.format_argv_cell(["a|b", "c\nd"]) == "a\\|b c d"
    long = performance.format_argv_cell(["x" * 100])
    assert long.endswith("…") and len(long) == performance.ARGV_LIMIT


def test_span_command_fields_keeps_the_process_argv():
    span = {
        "name": "todo-helper",
        "attributes": {
            "process.exit.code": 0,
            "process.command_args": ["/usr/bin/spex", "todo-helper", "edit", "--id", "s1"],
        },
        "spex": {"duration_ms": 5, "subcommand": "edit"},
    }
    fields = native_trace.span_command_fields(span)
    assert fields["argv"] == ["/usr/bin/spex", "todo-helper", "edit", "--id", "s1"]
    assert fields["subcommand"] == "edit"


def test_timeline_lines_render_skill_boundaries(tmp_path):
    output = tmp_path / "1"
    output.mkdir()
    host = performance.host_metrics(
        None, 4000, "adapter",
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:04+00:00",
    )
    performance.update(output, turn=1, host=host)
    metadata = {
        "case": {"turns": [{"input": "/spex create a thing"}]},
        "turn_results": [{"turn": 1}],
    }
    row = {
        "suite": "suite", "case_id": "case", "trial": "1",
        "performance": performance.trial_summary(output, metadata),
    }
    text = "\n".join(performance.timeline_lines([row]))
    assert "skill start: /spex create a thing" in text
    assert "skill end: /spex create a thing" in text
    assert text.index("Host turn 1 start") < text.index("skill start:")
    assert text.index("Host turn 1 end") < text.index("skill end:")


def test_report_lines_use_the_five_column_table(tmp_path):
    output = tmp_path / "1"
    output.mkdir()
    performance.update(output, turn=1, host=performance.host_metrics(None, 1000, "adapter"))
    rows = [{
        "suite": "suite", "case_id": "case", "trial": "1", "host": "codex",
        "model": "model", "collection": "automatic", "spex_ref": "abc",
        "execution": run.execution(None),
        "performance": performance.trial_summary(output, {"turn_results": [{}]}),
    }]
    lines = performance.report_lines(rows)
    assert "| Case | Host turns | Duration (s) | Source | Detail |" in lines
    assert not any("Slowest step" in line for line in lines)


def test_timeline_orders_unstamped_events_last(tmp_path):
    output = tmp_path / "1"
    output.mkdir()
    host = performance.host_metrics(
        None, 4000, "adapter",
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:04+00:00",
    )
    performance.update(output, turn=1, native={"events": [
        {"command": "list", "duration_ms": 5, "exit_code": 0,
         "at": "2026-01-01T00:00:01+00:00"},
        {"command": "show", "duration_ms": 5, "exit_code": 0},
    ]}, host=host)
    metadata = {
        "case": {"turns": [{"input": "/spex create a thing"}]},
        "turn_results": [{"turn": 1}],
    }
    row = {
        "suite": "suite", "case_id": "case", "trial": "1",
        "performance": performance.trial_summary(output, metadata),
    }
    text = "\n".join(performance.timeline_lines([row]))
    assert text.index("`list`") < text.index("`show`") < text.index("Case end")
    assert text.index("skill end:") < text.index("`show`")


REVIEW_ARGV = [
    "prompt", "apply-review", "--json", "spec-x", "--commit", "3240d1a",
    "--mode", "full",
]


def test_positional_selector_skips_options_and_their_values():
    verb = "apply-review"
    assert native_trace.positional_selector(REVIEW_ARGV, verb) == "spec-x"
    assert native_trace.positional_selector(
        ["prompt", verb, "--json", "--commit=3240d1a", "--mode", "full", "spec-x"], verb,
    ) == "spec-x"
    # A boolean flag directly before the selector must not swallow it.
    assert native_trace.positional_selector(
        ["prompt", verb, "--json", "spec-x"], verb,
    ) == "spec-x"
    # Attached short values carry their value inline.
    assert native_trace.positional_selector(
        ["prompt", verb, "--json", "-oreport", "spec-x"], verb,
    ) == "spec-x"
    # Non-identifier positionals are skipped, not reported as a selector.
    assert native_trace.positional_selector(
        ["prompt", verb, "bad:token", "spec-x"], verb,
    ) == "spec-x"
    assert native_trace.positional_selector(
        ["prompt", verb, "--commit", "3240d1a", "--mode", "full"], verb,
    ) is None
    assert native_trace.positional_selector(["prompt", verb], verb) is None


def test_central_debug_log_attributes_option_first_spec_selector():
    log = (
        "===== BEGIN 2026-11-18T10:00:00+08:00 =====\n"
        f"argv: spex {' '.join(REVIEW_ARGV)}\n"
        "===== END exit=0 duration_ms=10 =====\n"
    )
    gaps = set()
    events = native_trace.parse(log.splitlines(), native_trace.CENTRAL_DEBUG_LOG, gaps)
    event, = events
    assert event["action"] == "apply.review-command"
    assert event["spec"] == "spec-x"
    assert gaps == set()
    # Restored attribution lets the no-post-action gate pass instead of abstaining.
    trace = {"events": events, "gaps": gaps}
    assert evidence.native_check(
        "no-post-action", {}, {}, {"artifacts": {}}, trace, [],
    ) is True


def test_format_seconds_rounds_to_one_decimal():
    assert performance.format_seconds(39167.19) == "39.2"
    assert performance.format_seconds(1200.0) == "1.2"
    assert performance.format_seconds(0) == "0.0"
    assert performance.format_seconds(None) == "unknown"


def test_local_time_text_renders_local_hh_mm_ss():
    assert performance.local_time_text("2026-01-01T01:02:03+00:00", timezone.utc) == "01:02:03"
    cst = timezone(timedelta(hours=8))
    assert performance.local_time_text("2026-01-01T01:02:03+00:00", cst) == "09:02:03"
    assert performance.local_time_text("2026-01-01T01:02:03") is None
    assert performance.local_time_text("not-a-timestamp") is None
    assert performance.local_time_text(None) is None


def test_local_time_text_defaults_to_local_zone():
    stamp = "2026-07-15T12:00:00+00:00"
    expected = datetime.fromisoformat(stamp).astimezone().strftime("%H:%M:%S")
    # tz=None must use the local zone at that instant (DST-aware), not a
    # fixed offset captured from the current time.
    assert performance.local_time_text(stamp) == expected
    assert performance.local_time_text(stamp).count(":") == 2


def test_timeline_cells_show_time_of_day_without_date_or_zone(tmp_path):
    output = tmp_path / "1"
    output.mkdir()
    host = performance.host_metrics(
        None, 4000, "adapter",
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:04+00:00",
    )
    performance.update(output, turn=1, host=host)
    row = {
        "suite": "suite", "case_id": "case", "trial": "1",
        "performance": performance.trial_summary(output, {"turn_results": [{"turn": 1}]}),
    }
    lines = performance.timeline_lines([row])
    start = next(line for line in lines if "Host turn 1 start" in line)
    end = next(line for line in lines if "Host turn 1 end" in line)
    for line in (start, end):
        assert re.search(r"\d{2}:\d{2}:\d{2}", line)
        assert "2026-" not in line and "+00:00" not in line
    assert "| 4.0 |" in end


def perf_row(start, end, turns=None):
    return {"performance": {
        "case_started_at": start,
        "case_ended_at": end,
        "host_turns_timeline": turns or [],
    }}


def test_timeline_date_range_reports_local_days():
    same = [perf_row("2026-01-01T08:00:00+00:00", "2026-01-01T09:00:00+00:00")]
    assert performance.timeline_date_range(same, timezone.utc) == "2026-01-01"
    cross = [perf_row("2026-01-01T23:00:00+00:00", "2026-01-02T01:00:00+00:00")]
    assert performance.timeline_date_range(cross, timezone.utc) == "2026-01-01 – 2026-01-02"
    assert performance.timeline_date_range([], timezone.utc) is None
    fallback = [perf_row(None, None, [
        {"started_at": "2026-02-01T00:00:00+00:00"},
        {"ended_at": "2026-02-02T00:00:00+00:00"},
    ])]
    assert performance.timeline_date_range(fallback, timezone.utc) == (
        "2026-02-01 – 2026-02-02"
    )


def test_local_date_returns_local_calendar_date():
    assert performance.local_date("2026-01-01T01:02:03+00:00", timezone.utc).isoformat() == (
        "2026-01-01"
    )
    cst = timezone(timedelta(hours=8))
    assert performance.local_date("2026-01-01T20:00:00+00:00", cst).isoformat() == "2026-01-02"
    assert performance.local_date("2026-01-01T01:02:03") is None
    assert performance.local_date("not-a-timestamp") is None


def test_timeline_date_range_falls_back_per_endpoint():
    pending_end = [perf_row("2026-03-01T00:00:00+00:00", None, [
        {"started_at": "2026-03-01T00:00:00+00:00",
         "ended_at": "2026-03-02T00:00:00+00:00"},
    ])]
    assert performance.timeline_date_range(pending_end, timezone.utc) == (
        "2026-03-01 – 2026-03-02"
    )


def test_timeline_date_range_aggregates_across_trials():
    trials = [
        perf_row("2026-01-01T08:00:00+00:00", "2026-01-01T09:00:00+00:00"),
        perf_row("2026-01-03T08:00:00+00:00", "2026-01-03T09:00:00+00:00"),
    ]
    assert performance.timeline_date_range(trials, timezone.utc) == (
        "2026-01-01 – 2026-01-03"
    )


def test_timeline_date_range_skips_rows_without_performance():
    rows = [{"suite": "suite"}, perf_row("2026-01-01T08:00:00+00:00", None)]
    assert performance.timeline_date_range(rows, timezone.utc) == "2026-01-01"


def test_summary_header_includes_timeline_dates(tmp_path):
    output = tmp_path / "suite" / "case"
    output.mkdir(parents=True)
    host = performance.host_metrics(
        None, 4000, "adapter",
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:04+00:00",
    )
    performance.update(output, turn=1, host=host)
    report = {
        "sandbox": str(tmp_path / "sandbox"),
        "trials": [{
            "suite": "suite", "case_id": "case", "trial": "suite/case",
            "host": "codex", "model": "model", "collection": "automatic",
            "spex_ref": "abc", "execution": run.execution(None),
            "performance": performance.trial_summary(output, {"turn_results": [{"turn": 1}]}),
            "scores": [],
        }],
        "cleanup_hint": "none", "scores": {}, "counts": {}, "classifications": {},
        "issues": [], "improvements": [],
    }
    text = run.render_summary_markdown(report)
    dates = next(line for line in text.splitlines() if line.startswith("- Timeline dates: "))
    assert re.fullmatch(
        r"- Timeline dates: \d{4}-\d{2}-\d{2}(?: – \d{4}-\d{2}-\d{2})? \(local\)", dates,
    )
    assert dates == f"- Timeline dates: {performance.timeline_date_range(report['trials'])} (local)"
