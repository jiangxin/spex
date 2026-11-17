"""Collect sandbox ``_handoff/`` replies into trials, then optionally summarize.

Deterministic helper for spex-eval: after agents write
``_handoff/<suite>-<case>-turnN.txt``, run this instead of narrating checks.

Usage (from repository root)::

    python3 eval/spex/collect_handoff.py eval/spex/runs/TIMESTAMP
    python3 eval/spex/collect_handoff.py SANDBOX --no-summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run as eval_run  # noqa: E402


def handoff_reply(sandbox: Path, suite: str, case_id: str, turn: int) -> Path:
    return sandbox / "_handoff" / f"{suite}-{case_id}-turn{turn}.txt"


def resolve_collect_session(metadata: dict, suite: str, case_id: str) -> str:
    existing = metadata.get("session")
    if isinstance(existing, str) and existing:
        return existing
    host = metadata.get("host")
    if not isinstance(host, str) or host == "unknown" or not eval_run.SESSION_ID.fullmatch(host):
        host = "manual"
    label = f"{host}-{suite}-{case_id}"
    if len(label) > 128:
        return f"{label[:111]}-{eval_run.digest(label.encode())[:16]}"
    return label


def collect_trial(sandbox: Path, trial_json: Path) -> dict:
    """Collect successive handoff turns until the trial is no longer pending."""
    metadata = eval_run.read_json(trial_json)
    suite = str(metadata.get("suite") or "")
    case_id = str(metadata.get("case_id") or "")
    trial_dir = trial_json.parent
    if metadata.get("verdict") != "pending":
        return {
            "suite": suite,
            "case_id": case_id,
            "trial": str(trial_dir),
            "status": "already_done",
            "turns": [],
            "verdict": metadata.get("verdict"),
        }
    session = resolve_collect_session(metadata, suite, case_id)
    turns: list[dict] = []
    turn = len(metadata.get("turn_results") or []) + 1
    while True:
        current = eval_run.read_json(trial_json)
        if current.get("verdict") != "pending":
            break
        reply = handoff_reply(sandbox, suite, case_id, turn)
        if not reply.is_file() or reply.is_symlink():
            return {
                "suite": suite,
                "case_id": case_id,
                "trial": str(trial_dir),
                "status": "missing_handoff",
                "missing": str(reply),
                "turns": turns,
                "verdict": current.get("verdict"),
            }
        if any(
            handoff_reply(sandbox, suite, case_id, later).exists()
            for later in range(turn + 1, len(current["case"]["turns"]) + 1)
        ):
            raise ValueError(
                f"{suite}/{case_id}: cannot collect turn {turn} from a workspace "
                "with later replies. Collect each turn before dispatching the next input."
            )
        sidecar = reply.with_suffix(".events.jsonl")
        args = SimpleNamespace(
            session=session,
            reply=reply,
            events=sidecar if sidecar.is_file() and not sidecar.is_symlink() else None,
        )
        result = eval_run.manual_result(eval_run.resolve_trial(trial_dir), args)
        turns.append({
            "turn": turn,
            "reply": str(reply),
            "verdict": result.get("verdict"),
        })
        if not result.get("next_input"):
            break
        turn += 1
    final = eval_run.read_json(trial_json)
    return {
        "suite": suite,
        "case_id": case_id,
        "trial": str(trial_dir),
        "status": "collected",
        "turns": turns,
        "verdict": final.get("verdict"),
    }


def collect_sandbox(sandbox: Path, *, do_summary: bool = True) -> dict:
    """Collect every pending trial under ``sandbox`` that has handoff files."""
    sandbox = eval_run.resolve_sandbox(sandbox)
    rows = []
    for trial_json in eval_run.iter_trial_paths(sandbox):
        rows.append(collect_trial(sandbox, trial_json))
    payload: dict = {
        "sandbox": str(sandbox),
        "trials": rows,
        "missing": [row for row in rows if row.get("status") == "missing_handoff"],
        "collected": [row for row in rows if row.get("status") == "collected"],
    }
    if do_summary:
        payload["summary"] = eval_run.summarize_sandbox(sandbox)
        payload["report"] = payload["summary"].get("report")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect _handoff replies for a spex-eval sandbox",
    )
    parser.add_argument(
        "sandbox",
        type=Path,
        help="Sandbox under eval/spex/runs/YYYY-MM-DD-HH-MM-SS",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip writing report.md / report.json after collect",
    )
    args = parser.parse_args(argv)
    try:
        payload = collect_sandbox(args.sandbox, do_summary=not args.no_summary)
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 2
    print(json.dumps({
        "sandbox": payload["sandbox"],
        "collected": len(payload["collected"]),
        "missing": len(payload["missing"]),
        "trials": payload["trials"],
        "report": payload.get("report"),
        "cleanup_hint": (payload.get("summary") or {}).get("cleanup_hint"),
    }, indent=2))
    return 1 if payload["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
