"""Offline regression tests for the eval diagnostics pipeline."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "spex"))
try:
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
    for index, (duration, jobs) in enumerate(((10, 1), (30, 1), (None, 1), (900, 2)), 1):
        output = tmp_path / str(index)
        output.mkdir()
        host = performance.host_metrics(None, duration, "adapter")
        performance.update(output, turn=1, host=host)
        rows.append({
            "suite": "suite", "case_id": "case", "trial": str(index),
            "host": "cursor", "model": "model", "collection": "manual", "spex_ref": "abc",
            "execution": run.execution(jobs),
            "performance": performance.trial_summary(output, {"turn_results": [{}]}),
        })
    report = "\n".join(performance.report_lines(rows))
    assert "[metrics](1/performance.json)" in report
    assert "2/3 samples, median 20.0 ms, max 30 ms" in report
    assert "3/4 samples" not in report


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
    host = performance.host_metrics(
        None, 1000, "adapter",
        started_at="2026-11-17T09:00:20.100000+08:00",
        ended_at="2026-11-17T09:00:21.100000+08:00",
    )
    early = {"events": [
        {"command": "list", "at": "2026-11-17T09:00:01+08:00", "duration_ms": 700},
    ]}
    later = {"events": [
        {"command": "list", "at": "2026-11-17T09:00:21.100000054+08:00", "duration_ms": 700},
    ]}
    performance.update(tmp_path, turn=1, host={**host, "gaps": []}, native=early)
    performance.update(tmp_path, turn=2, host={**host, "gaps": []}, native=later)
    performance.update(tmp_path, turn=2, host={**host, "gaps": []}, native=later)
    turns = performance.read_performance(tmp_path)["turns"]
    assert "implausible_host_duration" in turns["1"]["host"]["gaps"]
    assert turns["2"]["host"]["gaps"] == []
    nano, end = performance.stamp_bounds("2026-11-17T09:00:21.100000054+08:00")
    assert nano == end and nano % 1000 == 54
