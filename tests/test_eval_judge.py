"""Offline validation for semantic judging."""

import json
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

EVAL = Path(__file__).resolve().parents[1] / "eval" / "spex"
sys.path.insert(0, str(EVAL))

from evidence import persist_turn  # noqa: E402
from judge import (  # noqa: E402
    apply_grades,
    codex_judge,
    export_packet,
    final_verdict,
    grade,
    packet_for,
    validate,
)
from transport import TransportError  # noqa: E402

CRITERION = {
    "id": "coverage", "turn": 1, "requires": ["state"], "threshold": 2,
    "anchors": ["Missing", "Partial", "Complete"],
}


@pytest.mark.parametrize("tool_event", [None, "item.started", "item.completed"])
def test_codex_judge_disables_tools_and_rejects_search_trace(monkeypatch, tool_event):
    events = [{"type": "thread.started", "thread_id": "judge-session"}]
    if tool_event:
        events.append({"type": tool_event, "item": {"type": "web_search", "query": "search"}})
    events.extend([
        {"type": "item.completed", "item": {"type": "agent_message", "text": "[]"}},
        {"type": "turn.completed"},
    ])

    def fake_run(command, **kwargs):
        assert command[command.index("--disable") + 1] == "shell_tool"
        assert 'web_search="disabled"' in command
        return CompletedProcess(command, 0, "\n".join(map(json.dumps, events)), "")

    monkeypatch.setattr("judge.subprocess.run", fake_run)
    if tool_event:
        with pytest.raises(TransportError, match="judge_used_tools"):
            codex_judge("Grade the evidence.", "judge", 30)
    else:
        assert codex_judge("Grade the evidence.", "judge", 30) == "[]"


def test_packet_blinds_trial_metadata_and_omits_private_state(tmp_path):
    persist_turn(tmp_path, 1, {
        "files": {"private.py": "outside-fixture"},
        "specs": {"spec": {
            "spec.md": "candidate-model token: private-token",
            "meta.json": {"user_name": "Private Name"},
        }},
    })
    packet = packet_for(tmp_path, {"model": "candidate-model"}, [CRITERION])
    rendered = json.dumps(packet)
    for private in ("candidate-model", "private-token", "private.py", "Private Name"):
        assert private not in rendered
    assert packet["evidence"]["turn-1:state"]["specs"]["spec"]["spec.md"].count("[REDACTED]") == 2


def test_packet_distinguishes_historical_commands_from_completed_reviews(tmp_path):
    command = {"action": "apply.review", "mode": "full", "commit": "abc1234", "exit_code": 0}
    persist_turn(tmp_path, 1, {"specs": {}}, events=[command], native={
        "events": [
            {**command, "action": "apply.review-command"},
            {**command, "commit": "def5678", "step": "step-1"},
            {**command, "commit": "def9999", "exit_code": None},
        ],
        "gaps": ["incomplete_review_log"],
    })
    packet = packet_for(tmp_path, {}, [CRITERION])
    assert packet["evidence"]["turn-1:events"] == [{**command, "action": "apply.review-command"}]
    assert packet["evidence"]["turn-1:spex-trace"] == {
        "completed_reviews": [{"step": "step-1", "mode": "full", "commit": "def5678"}],
        "skipped_reviews": [],
        "gaps": ["incomplete_review_log"],
    }


def test_lifecycle_can_cite_only_the_declared_prior_review_trace(tmp_path):
    persist_turn(tmp_path, 1, {"specs": {}}, reply="Prior reply", native={
        "events": [{"action": "apply.review", "mode": "full", "exit_code": 0}],
        "gaps": [],
    })
    persist_turn(tmp_path, 2, {"specs": {}}, reply="Completed")
    criterion = {**CRITERION, "turn": 2, "requires": ["reply"], "review_context_turns": [1]}
    packet = packet_for(tmp_path, {}, [criterion])
    assert "turn-1:reply" not in packet["evidence"]
    row = {
        "criterion_id": criterion["id"], "score": 2, "verdict": "pass",
        "reason": "Both turns support the result.",
        "evidence_refs": ["turn-2:reply", "turn-1:spex-trace"],
    }
    assert apply_grades(packet, json.dumps([row]))["results"] == [row]
    packet["criteria"] = [{**criterion, "review_context_turns": []}]
    assert apply_grades(packet, json.dumps([row]))["error"] == "judge_invalid_output"


@pytest.mark.parametrize("changes", [
    {"criterion_id": "unknown"}, {"score": 3}, {"evidence_refs": ["turn-2:state"]},
    {"evidence_refs": ["turn-1:reply"]},
])
def test_invalid_result_gets_one_repair(changes):
    packet = {"criteria": [CRITERION], "evidence": {"turn-1:state": {}, "turn-1:reply": ""}}
    good = {
        "criterion_id": "coverage", "score": 2, "verdict": "pass",
        "reason": "The specification covers the required behavior.",
        "evidence_refs": ["turn-1:state"],
    }
    prompts = []

    def fake(prompt, model, timeout):
        assert model == "judge" and timeout == 30
        prompts.append(prompt)
        return json.dumps([{**good, **changes} if len(prompts) == 1 else good])

    result = grade(packet, "judge", 30, adapter=fake)
    assert result["results"] == [good]
    assert len(prompts) == 2 and "previous result was invalid" in prompts[-1]
    assert final_verdict("fail", result) == "fail"


def test_missing_evidence_and_exhausted_repair():
    packet = {"criteria": [CRITERION], "evidence": {}}
    result = grade(packet, "judge", 30, adapter=lambda *_: pytest.fail("No call needed"))
    assert result["results"][0]["score"] is None
    assert final_verdict("pass", result) == "insufficient_evidence"
    packet["evidence"]["turn-1:state"] = {}
    result = grade(packet, "judge", 30, adapter=lambda *_: "invalid")
    assert len(result["raw_attempts"]) == 2
    assert final_verdict("pass", result) == "judge_error"
    assert final_verdict("fail", result) == "fail"


def test_export_packet_and_apply_external_grades():
    packet = {
        "criteria": [
            CRITERION,
            {**CRITERION, "id": "events", "requires": ["events"]},
        ],
        "evidence": {"turn-1:state": {"specs": {}}},
    }
    exported = export_packet(packet)
    assert [item["id"] for item in exported["packet"]["criteria"]] == ["coverage"]
    assert exported["insufficient"][0]["criterion_id"] == "events"
    assert exported["insufficient"][0]["verdict"] == "insufficient_evidence"
    assert "Grade the supplied criteria" in exported["prompt"]

    good = [{
        "criterion_id": "coverage", "score": 2, "verdict": "pass",
        "reason": "The specification covers the required behavior.",
        "evidence_refs": ["turn-1:state"],
    }]
    accepted = apply_grades(packet, json.dumps(good))
    assert accepted["source"] == "external"
    assert accepted["results"][0]["criterion_id"] == "events"
    assert accepted["results"][1] == good[0]
    assert final_verdict("pass", accepted) == "insufficient_evidence"

    rejected = apply_grades(packet, json.dumps([{**good[0], "evidence_refs": ["turn-2:state"]}]))
    assert rejected["error"] == "judge_invalid_output"
    assert rejected["invalid_reference_attempts"] == 1


GOOD_ROW = {
    "criterion_id": "coverage", "score": 2, "verdict": "pass",
    "reason": "The specification covers the required behavior.",
    "evidence_refs": ["turn-1:state"],
}


@pytest.mark.parametrize("turn", [1, "1"])
def test_apply_grades_normalizes_matching_turn(turn):
    packet = {"criteria": [CRITERION], "evidence": {"turn-1:state": {}}}
    result = apply_grades(packet, json.dumps([{**GOOD_ROW, "turn": turn}]))
    assert result["results"] == [GOOD_ROW]


@pytest.mark.parametrize("turn", [2, "2", True, 1.0, "１", None])
def test_apply_grades_rejects_invalid_turn(turn):
    evidence = {"turn-1:state": {}}
    packet = {"criteria": [CRITERION], "evidence": evidence}
    raw = json.dumps([{**GOOD_ROW, "turn": turn}])
    with pytest.raises(ValueError, match="Result turn does not match criterion"):
        validate(raw, [CRITERION], evidence)
    assert apply_grades(packet, raw)["error"] == "judge_invalid_output"


def test_validate_strips_turn_from_unscored_row():
    row = {**GOOD_ROW, "score": None, "verdict": "insufficient_evidence", "evidence_refs": []}
    raw = json.dumps([{**row, "turn": 1}])
    assert validate(raw, [CRITERION], {"turn-1:state": {}}) == [row]


def test_validate_names_missing_and_unknown_fields():
    row = {key: value for key, value in GOOD_ROW.items() if key != "verdict"}
    row.update(turn=1, note="extra")
    with pytest.raises(ValueError, match=r"missing \['verdict'\], unexpected \['note'\]"):
        validate(json.dumps([row]), [CRITERION], {"turn-1:state": {}})


def test_repair_does_not_hide_invalid_reference_after_invalid_score():
    packet = {
        "criteria": [CRITERION, {**CRITERION, "id": "clarity"}],
        "evidence": {"turn-1:state": {}},
    }
    good = {
        "criterion_id": "coverage", "score": 2, "verdict": "pass",
        "reason": "The specification covers the required behavior.",
        "evidence_refs": ["turn-1:state"],
    }
    second = {**good, "criterion_id": "clarity"}
    attempts = iter([
        [{**good, "score": 3}, {**second, "evidence_refs": ["turn-1:fabricated"]}],
        [good, second],
    ])
    result = grade(packet, "judge", 30, adapter=lambda *_: json.dumps(next(attempts)))
    assert result["results"] == [good, second]
    assert result["invalid_reference_attempts"] == 1
