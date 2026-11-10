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
