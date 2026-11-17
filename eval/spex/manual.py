"""Coordinate prepared current-host Spex trials and collect guarded turns."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import collect_handoff
import host_turn_timer
import manual_batch
import run as runner
from workspace import Trial, case_dir

TERMINAL_VERDICTS = {"pass", "fail", "insufficient_evidence", "judge_error", "run_error"}
WAIT_INTERVAL = 2.0


def validate_keys(sandbox: Path, keys: list[str]) -> None:
    for key in keys:
        suite, delim, case = key.partition("/")
        if not delim:
            raise ValueError(f"Expected a suite/case ID: {key}")
        case_dir(sandbox, suite, case)


def load_trial(sandbox: Path, key: str, entries: dict) -> tuple[Path, Trial, dict]:
    suite, case = key.split("/")
    path = case_dir(sandbox, suite, case)
    if entries.get(key, {}).get("trial") != key or path.resolve() != path:
        raise ValueError(f"No published handoff for {key}")
    output = runner.resolve_trial(path)
    metadata = runner.read_json(output / "trial.json")
    if (
        metadata["suite"] != suite or metadata["case_id"] != case
        or metadata["sandbox"] != str(sandbox) or metadata["collection"] != "manual"
        or metadata["trial_directory"] != str(output / "workspace")
    ):
        raise ValueError(f"Prepared trial identity does not match {key}")
    trial = Trial(Path(metadata["trial_directory"]), metadata["spex_ref"])
    if trial.repo.resolve() != trial.repo:
        raise ValueError(f"Unexpected linked trial workspace for {key}")
    return output, trial, metadata


def outcome(queue: dict) -> dict:
    return {"terminal": all(row["status"] == "completed" for row in queue.values()),
            "cases": queue}


def initialize(sandbox: Path, queue_file: Path, entries: dict, cases: list[str]) -> dict:
    validate_keys(sandbox, cases)
    if len(set(cases)) != len(cases) or set(cases) != set(entries):
        raise ValueError("Pass the exact selected suite/case IDs after all prepares succeed")
    if queue_file.exists():
        return outcome(manual_batch.read(queue_file))
    for key in cases:
        load_trial(sandbox, key, entries)
    queue = {key: {"status": "pending"} for key in cases}
    manual_batch.write(queue_file, queue)
    return outcome(queue)


def turn_action(args, sandbox: Path, output: Path, trial: Trial, metadata: dict, row: dict,
                environment: dict, save_dispatch):
    suite, case = metadata["suite"], metadata["case_id"]
    current = len(metadata["turn_results"]) + 1
    handoff = runner.instructions(output, trial, metadata)
    handoff["environment"] = environment
    dispatch = row.get("dispatch", {})
    if args.command == "collect" and args.turn == current - 1 and current > 1:
        if dispatch.get("turn") == args.turn:
            row.pop("dispatch")
        return handoff  # Collection is committed by trial.json, even on a retry.
    if args.turn != current or not handoff["next_input"]:
        raise ValueError(f"No next input for turn {args.turn}; pending turn is {current}")
    reply = collect_handoff.handoff_reply(sandbox, suite, case, current)
    if reply.parent.is_symlink():
        raise ValueError("Refusing to use a symlink handoff directory")
    timer = host_turn_timer.pending_path(reply)
    wall = collect_handoff.host_wall_clock_sidecar(reply)
    if args.command == "start":
        if any(path.exists() or path.is_symlink() for path in (reply, timer, wall)):
            raise ValueError("Turn already started; stop and collect it before dispatching again")
        session = dispatch.get("session") or metadata["session"]
        if not runner.SESSION_ID.fullmatch(args.session) or session not in ("", args.session):
            raise ValueError("Use the same valid session ID for all turns of this trial")
        row["dispatch"] = {"turn": current, "session": args.session}
        save_dispatch()  # Bind the session before creating the pending timer.
        host_turn_timer.start_timer(sandbox, suite, case, current)
        return {**handoff, "session": args.session, "turn": current, "reply": str(reply)}
    if dispatch.get("turn") != current:
        raise ValueError("Start this turn before stopping or collecting it")
    if args.command == "stop":
        if not timer.is_file() and wall.is_file() and not wall.is_symlink():
            return {"turn": current, "reply": str(reply),
                    **collect_handoff.read_host_wall_clock(reply)}
        return host_turn_timer.stop_timer(sandbox, suite, case, current)
    timing = collect_handoff.read_host_wall_clock(reply)
    if timer.exists() or timer.is_symlink() or any(value is None for value in timing.values()):
        raise ValueError("Stop the current turn timer before collection")
    if reply.parent.is_symlink() or reply.is_symlink() or not reply.is_file():
        raise ValueError(f"Expected a reply file for turn {current}: {reply}")
    events = reply.with_suffix(".events.jsonl")
    result = runner.manual_result(output, SimpleNamespace(
        session=dispatch["session"], reply=reply,
        events=events if events.is_file() and not events.is_symlink() else None,
        **timing,
    ))
    row.pop("dispatch")
    result["environment"] = environment
    return result


def complete_trial(args, output: Path, metadata: dict, row: dict) -> dict:
    verdict = metadata["verdict"]
    if args.command == "fail":
        error = f"manual_host_{args.reason}"
        if verdict == "pending":
            metadata.update(verdict="run_error", error=error)
            metadata["session"] = row.get("dispatch", {}).get("session", metadata["session"])
            manual_batch.write(output / "trial.json", metadata)
            verdict = "run_error"
        elif verdict != "run_error" or metadata.get("error") != error:
            raise ValueError("Only a pending trial can record a host failure")
    if verdict not in TERMINAL_VERDICTS:
        raise ValueError("Trial is still pending")
    if verdict != "run_error" and "hard_verdict" not in metadata:
        raise ValueError("Import semantic grades before completing the trial")
    row.update(status="completed", verdict=verdict)
    row.pop("dispatch", None)
    return {"case": args.case, **row}


def dispatch(args, sandbox: Path) -> tuple[dict, int]:
    with manual_batch.locked(sandbox):
        queue_file = sandbox / "queue.json"
        entries = manual_batch.read(sandbox / "batch-index.json", {})
        if args.command == "init":
            return initialize(sandbox, queue_file, entries, args.cases), 0
        queue = manual_batch.read(queue_file)
        if args.command == "status":
            result = outcome(queue)
            return result, int(args.require_terminal and not result["terminal"])
        key = args.case
        if key not in queue:
            raise ValueError(f"Case was not selected for this batch: {key}")
        output, trial, metadata = load_trial(sandbox, key, entries)
        row = queue[key]
        if args.command == "claim":
            if row["status"] != "pending":
                raise ValueError(f"Case is already {row['status']}: {key}")
            active = sum(row["status"] == "running" for row in queue.values())
            if active >= metadata["execution"]["jobs"]:
                raise ValueError("All configured trial slots are occupied")
            row["status"] = "running"
            result = {"case": key, "trial": str(output)}
        elif row["status"] != "running":
            raise ValueError(f"Case must be claimed and running: {key}")
        elif args.command in ("complete", "fail"):
            result = complete_trial(args, output, metadata, row)
        else:
            result = turn_action(
                args, sandbox, output, trial, metadata, row, entries[key]["environment"],
                lambda: manual_batch.write(queue_file, queue),
            )
        manual_batch.write(queue_file, queue)
    return result, 0


def run_command(args, sandbox: Path) -> int:
    with manual_batch.locked(sandbox):
        queue = manual_batch.read(sandbox / "queue.json")
        entries = manual_batch.read(sandbox / "batch-index.json")
        if queue.get(args.case, {}).get("status") != "running":
            raise ValueError(f"Case must be claimed and running: {args.case}")
        _, trial, _ = load_trial(sandbox, args.case, entries)
        env = {**trial.env, **entries[args.case]["environment"]}
    argv = args.argv
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise ValueError("Pass a command after --")
    os.chdir(trial.repo)
    if argv[0] == "spex":
        # Older handoffs may have recorded a PATH without the pinned CLI.
        executable = trial.skill / "scripts" / "spex"
    else:
        executable = shutil.which(argv[0], path=env["PATH"])
    if not executable and "/" not in argv[0]:
        raise ValueError(f"Command not found in trial PATH: {argv[0]}")
    os.execve(executable or argv[0], argv, env)
    return 0


def pending_reply(sandbox: Path, key: str, row: dict) -> dict | None:
    """Return the reply coordinates when a running turn has finished writing."""
    dispatch = row.get("dispatch") or {}
    turn = dispatch.get("turn")
    if row.get("status") != "running" or type(turn) is not int:
        return None
    suite, case = key.split("/")
    reply = collect_handoff.handoff_reply(sandbox, suite, case, turn)
    if reply.is_symlink() or not reply.is_file():
        return None
    return {
        "case": key, "turn": turn,
        "session": dispatch.get("session"), "reply": str(reply),
    }


def queue_progress(sandbox: Path, queue: dict) -> dict:
    ready = []
    for key, row in queue.items():
        item = pending_reply(sandbox, key, row)
        if item is not None:
            ready.append(item)
    return {
        "ready": ready,
        "running": sum(row["status"] == "running" for row in queue.values()),
        "pending": sum(row["status"] == "pending" for row in queue.values()),
    }


def wait_action(args, sandbox: Path) -> tuple[dict, int]:
    """Block until any running turn has a reply, or no trial is running."""
    deadline = time.monotonic() + args.timeout
    while True:
        with manual_batch.locked(sandbox):
            queue = manual_batch.read(sandbox / "queue.json")
            progress = queue_progress(sandbox, queue)
        progress.update(sandbox=str(sandbox), timed_out=False)
        if progress["ready"] or progress["running"] == 0:
            return progress, 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            progress["timed_out"] = True
            return progress, 1
        time.sleep(min(WAIT_INTERVAL, remaining))


def advance_action(sandbox: Path) -> tuple[dict, int]:
    """Stop, collect, and export every running turn whose reply has appeared."""
    advanced: list[dict] = []
    exported: list[dict] = []
    waiting: list[dict] = []
    errors: list[dict] = []
    with manual_batch.locked(sandbox):
        queue_file = sandbox / "queue.json"
        entries = manual_batch.read(sandbox / "batch-index.json")
        queue = manual_batch.read(queue_file)
        for key, row in queue.items():
            item = pending_reply(sandbox, key, row)
            if item is None:
                continue
            try:
                output, trial, metadata = load_trial(sandbox, key, entries)
                environment = entries[key]["environment"]
                turn = item["turn"]
                for command in ("stop", "collect"):
                    result = turn_action(
                        SimpleNamespace(command=command, case=key, turn=turn),
                        sandbox, output, trial, metadata, row, environment,
                        lambda: None,
                    )
                manual_batch.write(queue_file, queue)
                advanced.append({"case": key, "turn": turn, "reply": item["reply"]})
                if result.get("next_input"):
                    waiting.append(
                        {"case": key, "next_input": result["next_input"]},
                    )
                    continue
                packet = runner.export_judge(output)
                exported.append({
                    "case": key, "verdict": packet["hard_verdict"],
                    "prompt": packet["prompt"], "trial": packet["trial"],
                })
            except (OSError, ValueError, SystemExit, runner.TransportError) as error:
                errors.append({"case": key, "error": str(error)})
                manual_batch.write(queue_file, queue)
    payload = {
        "sandbox": str(sandbox), "advanced": advanced, "exported": exported,
        "waiting": waiting, "errors": errors,
    }
    return payload, 1 if errors else 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--sandbox", required=True, type=Path)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("init").add_argument("cases", nargs="+", metavar="SUITE/CASE")
    sub.add_parser("status").add_argument("--require-terminal", action="store_true")
    wait = sub.add_parser("wait", help="Block until a running turn has a reply")
    wait.add_argument(
        "--any", action="store_true", required=True,
        help="Return as soon as any running trial has a reply",
    )
    wait.add_argument(
        "--timeout", type=int, default=900,
        help="Give up after this many seconds (default: 900)",
    )
    sub.add_parser(
        "advance", help="Stop, collect, and export every finished running turn",
    )
    for command in ("claim", "start", "stop", "collect", "complete", "fail", "exec"):
        action = sub.add_parser(command)
        action.add_argument("case", metavar="SUITE/CASE")
        if command in ("start", "stop", "collect"):
            action.add_argument("turn", type=int)
        if command == "start":
            action.add_argument("--session", required=True)
        if command == "fail":
            action.add_argument(
                "--reason", required=True, choices=("launch_failed", "exited", "timeout"),
            )
        if command == "exec":
            action.add_argument("argv", nargs=argparse.REMAINDER)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        sandbox = runner.resolve_sandbox(args.sandbox)
        if args.command == "exec":
            return run_command(args, sandbox)
        if args.command == "wait":
            result, code = wait_action(args, sandbox)
        elif args.command == "advance":
            result, code = advance_action(sandbox)
        else:
            result, code = dispatch(args, sandbox)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
