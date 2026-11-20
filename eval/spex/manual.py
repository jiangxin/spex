"""Coordinate prepared current-host Spex trials and collect guarded turns."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
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
    # The shared bootstrap validates the keys, keeps an existing queue as-is, and
    # only loads each prepared trial when it creates the queue.
    manual_batch.initialize(
        sandbox, cases, loader=lambda key: load_trial(sandbox, key, entries),
    )
    return outcome(manual_batch.read(queue_file))


def read_complete_reply(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular reply file: {path}")
    data = path.read_bytes()
    if not data.decode("utf-8").strip():
        raise ValueError(f"The reply file is empty: {path}")
    return data


def publish_reply(source: Path, reply: Path) -> None:
    data = read_complete_reply(source)
    fd, name = tempfile.mkstemp(dir=reply.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        try:
            os.link(temporary, reply)
        except FileExistsError:
            if read_complete_reply(reply) != data:
                raise ValueError(f"A different reply is already published: {reply}") from None
    finally:
        temporary.unlink(missing_ok=True)


def validate_reply_source(source: Path, reply: Path, workspace: Path) -> None:
    """Require a named staging file beside this turn's canonical reply."""
    expected = f"{reply.name} or {reply.name}.staging"
    if source.is_symlink():
        raise ValueError(f"Expected a regular staging file named {expected}: {source}")
    source = source.resolve()
    if source.parent != reply.parent.resolve() or not (
        source.name == reply.name or source.name.startswith(f"{reply.name}.")
    ):
        raise ValueError(f"Stage {expected} beside {reply}: {source}")
    if workspace.resolve() in source.parents:
        raise ValueError(f"Stage {expected} outside the workspace: {source}")


def turn_paths(sandbox: Path, suite: str, case: str, turn: int) -> tuple[Path, Path, Path]:
    """Return the reply, pending-timer, and wall-clock paths for one turn."""
    reply = collect_handoff.handoff_reply(sandbox, suite, case, turn)
    if reply.parent.is_symlink():
        raise ValueError("Refusing to use a symlink handoff directory")
    timer = host_turn_timer.pending_path(reply)
    return reply, timer, collect_handoff.host_wall_clock_sidecar(reply)


def ensure_unstarted(reply: Path, timer: Path, wall: Path) -> None:
    if any(path.exists() or path.is_symlink() for path in (reply, timer, wall)):
        raise ValueError("Turn already started; stop and collect it before dispatching again")


def check_session(args, row: dict, metadata: dict) -> None:
    """Require one valid session ID for every turn of a trial."""
    session = (row.get("dispatch") or {}).get("session") or metadata["session"]
    if not runner.SESSION_ID.fullmatch(args.session) or session not in ("", args.session):
        raise ValueError("Use the same valid session ID for all turns of this trial")


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
        if not handoff["next_input"]:
            row["slot_released"] = True  # The final turn is already collected.
        return handoff  # Collection is committed by trial.json, even on a retry.
    if args.turn != current or not handoff["next_input"]:
        raise ValueError(f"No next input for turn {args.turn}; pending turn is {current}")
    reply, timer, wall = turn_paths(sandbox, suite, case, current)
    if args.command == "start":
        ensure_unstarted(reply, timer, wall)
        check_session(args, row, metadata)
        row["dispatch"] = {"turn": current, "session": args.session}
        save_dispatch()  # Bind the session before creating the pending timer.
        host_turn_timer.start_timer(sandbox, suite, case, current)
        return {**handoff, "session": args.session, "turn": current, "reply": str(reply)}
    if dispatch.get("turn") != current:
        raise ValueError("Start this turn before stopping or collecting it")
    if args.command == "stop":
        stopped = not timer.exists() and not timer.is_symlink() and (
            wall.is_file() and not wall.is_symlink()
        )
        source = getattr(args, "reply_file", None)
        if source is not None:
            if not stopped and (timer.is_symlink() or not timer.is_file()):
                raise ValueError("Start the current turn timer before publishing its reply")
            validate_reply_source(source, reply, trial.repo)
            publish_reply(source, reply)
        if stopped:
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
    if not result.get("next_input"):
        row["slot_released"] = True  # Only grades keep this trial on the books.
    result["environment"] = environment
    return result


def record_host_failure(reason: str, output: Path, metadata: dict, row: dict) -> None:
    """Turn a pending trial into a stored host failure; a retry is a no-op."""
    error = f"manual_host_{reason}"
    verdict = metadata["verdict"]
    if verdict == "pending":
        metadata.update(verdict="run_error", error=error)
        metadata["session"] = row.get("dispatch", {}).get("session", metadata["session"])
        manual_batch.write(output / "trial.json", metadata)
    elif verdict != "run_error" or metadata.get("error") != error:
        raise ValueError("Only a pending trial can record a host failure")


def awaiting_grades(metadata: dict) -> bool:
    """True while the trial's final verdict has no imported grade behind it.

    A collected trial stores a terminal ``verdict`` as soon as its last turn is
    collected, but only ``import_judge`` writes ``hard_verdict``. So the ordinary
    pre-grade state is a terminal verdict without grades, not ``pending``.
    This is the metadata view; the queue row key ``slot_released`` records that
    the final turn was collected and does not imply grades are missing.
    """
    return metadata["verdict"] != "run_error" and "hard_verdict" not in metadata


def complete_row(key: str, metadata: dict, row: dict) -> dict:
    """Release one trial slot once its verdict is terminal and graded."""
    verdict = metadata["verdict"]
    if verdict not in TERMINAL_VERDICTS:
        raise ValueError("Trial is still pending")
    if verdict != "run_error" and "hard_verdict" not in metadata:
        raise ValueError("Import semantic grades before completing the trial")
    row.update(status="completed", verdict=verdict)
    row.pop("dispatch", None)
    row.pop("slot_released", None)
    return {"case": key, **row}


def complete_trial(args, output: Path, metadata: dict, row: dict) -> dict:
    if args.command == "fail":
        record_host_failure(args.reason, output, metadata, row)
    return complete_row(args.case, metadata, row)


def complete_all(sandbox: Path, queue_file: Path, queue: dict, entries: dict) -> dict:
    """Complete every running trial that already holds a terminal verdict.

    Rows are visited in queue insertion order. A running trial that is not
    graded yet keeps its slot, a row in any other state is skipped, and an
    unexpected per-case failure is reported without aborting the batch.
    Callers already hold ``manual_batch.locked(sandbox)`` and pass the state
    they loaded under it.
    """
    completed, skipped, errors = [], [], []
    for key, row in queue.items():
        try:
            if row["status"] != "running":
                skipped.append({"case": key, "reason": "not_running"})
                continue
            _, _, metadata = load_trial(sandbox, key, entries)
            if awaiting_grades(metadata):
                skipped.append({"case": key, "reason": "not_graded"})
                continue
            result = complete_row(key, metadata, row)
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append({"case": key, "error": str(error)})
            continue
        completed.append({"case": result["case"], "verdict": result["verdict"]})
    manual_batch.write(queue_file, queue)  # One write for the whole close-out.
    return {"completed": completed, "skipped": skipped, "errors": errors}


def running_keys(queue: dict) -> list[str]:
    """Return claimed case keys in queue insertion order."""
    return [key for key, row in queue.items() if row["status"] == "running"]


def active_keys(queue: dict) -> list[str]:
    """Return running keys that still execute, i.e. whose slot is not released.

    A trial whose final turn is collected and exported no longer runs, so it
    must not hold an execution slot while the judge catches up. The row key
    ``slot_released`` tracks that collection; it is distinct from the
    ``awaiting_grades(metadata)`` predicate used by ``complete_all``. Rows
    written before ``slot_released`` existed keep occupying a slot.
    """
    return [
        key for key, row in queue.items()
        if row["status"] == "running" and not row.get("slot_released")
    ]


def claim_row(queue: dict, key: str, jobs: int) -> None:
    """Refuse a claim that conflicts with the row state or the slot limit."""
    row = queue[key]
    if row["status"] != "pending":
        raise ValueError(f"Case is already {row['status']}: {key}")
    active = active_keys(queue)
    if len(active) >= jobs:
        raise ValueError(
            f"All configured trial slots are occupied (jobs={jobs}): {', '.join(active)}"
        )


def queue_row(queue: dict, key: str) -> dict:
    if key not in queue:
        raise ValueError(f"Case was not selected for this batch: {key}")
    return queue[key]


def dispatch_target(args, sandbox: Path, queue: dict, entries: dict) -> dict:
    """Validate one dispatch without touching the queue; return what it will publish."""
    key = args.case
    row = queue_row(queue, key)
    output, trial, metadata = load_trial(sandbox, key, entries)
    suite, case = metadata["suite"], metadata["case_id"]
    current = len(metadata["turn_results"]) + 1
    if args.turn is not None and args.turn != current:
        raise ValueError(f"No next input for turn {args.turn}; pending turn is {current}")
    if row["status"] == "pending":
        claim_row(queue, key, metadata["execution"]["jobs"])
    elif row["status"] != "running":
        raise ValueError(f"Case is already {row['status']}: {key}")
    check_session(args, row, metadata)
    handoff = runner.instructions(output, trial, metadata)
    if not handoff["next_input"]:
        raise ValueError(f"No next input for turn {current}")
    reply, timer, wall = turn_paths(sandbox, suite, case, current)
    ensure_unstarted(reply, timer, wall)
    script = runner.env_script_path(sandbox, suite, case)
    if script.is_symlink() or not script.is_file():
        raise ValueError(
            f"Missing prepared environment script: {script}; re-run prepare for {key}"
        )
    return {
        "row": row, "suite": suite, "case_id": case, "turn": current,
        "handoff": handoff, "reply": reply, "script": script,
    }


def dispatch_case(args, sandbox: Path, queue_file: Path, queue: dict, entries: dict) -> dict:
    """Claim a pending case and start its next turn in one call, returning the bundle."""
    target = dispatch_target(args, sandbox, queue, entries)
    row, handoff, current = target["row"], target["handoff"], target["turn"]
    reply = target["reply"]
    snapshot = dict(row)
    row["status"] = "running"
    row["dispatch"] = {"turn": current, "session": args.session}
    try:
        host_turn_timer.start_timer(sandbox, target["suite"], target["case_id"], current)
        manual_batch.write(queue_file, queue)
    except BaseException:
        timer = host_turn_timer.pending_path(reply)
        if timer.is_file() and not timer.is_symlink():
            timer.unlink(missing_ok=True)  # Keep the case dispatchable after a failed write.
        row.clear()
        row.update(snapshot)
        raise
    return {
        "case": args.case, "turn": current, "session": args.session,
        "trial": handoff["trial"], "workspace": handoff["workspace"],
        "skill": handoff["skill"], "env_script": str(target["script"]),
        "reply": str(reply), "staging_reply": f"{reply}.staging",
        "next_input": handoff["next_input"],
    }


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
        if args.command == "dispatch":
            return dispatch_case(args, sandbox, queue_file, queue, entries), 0
        if args.command == "complete" and args.all_cases:
            result = complete_all(sandbox, queue_file, queue, entries)
            return result, int(bool(result["errors"]))
        key = args.case
        row = queue_row(queue, key)
        output, trial, metadata = load_trial(sandbox, key, entries)
        if args.command == "claim":
            claim_row(queue, key, metadata["execution"]["jobs"])
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
    """Return a running turn's coordinates once its published reply is readable."""
    dispatch = row.get("dispatch") or {}
    turn = dispatch.get("turn")
    if row.get("status") != "running" or type(turn) is not int:
        return None
    suite, case = key.split("/")
    reply = collect_handoff.handoff_reply(sandbox, suite, case, turn)
    if reply.parent.is_symlink():
        return None
    try:
        read_complete_reply(reply)
    except (OSError, ValueError):
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
        "running": len(running_keys(queue)),
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
    commands = ("claim", "start", "dispatch", "stop", "collect", "complete", "fail", "exec")
    for command in commands:
        action = sub.add_parser(command)
        if command == "complete":
            action.add_argument(
                "case", metavar="SUITE/CASE", nargs="?",
                help="One suite/case ID; pass --all instead for a whole batch",
            )
            action.add_argument(
                "--all", dest="all_cases", action="store_true",
                help=(
                    "Complete every running case that holds a terminal verdict "
                    "and exit 1 when any case fails"
                ),
            )
        else:
            action.add_argument("case", metavar="SUITE/CASE")
        if command in ("start", "stop", "collect"):
            action.add_argument("turn", type=int)
        if command in ("start", "dispatch"):
            action.add_argument("--session", required=True)
        if command == "dispatch":
            action.add_argument("--turn", type=int, help="Assert the next turn number")
        if command == "stop":
            action.add_argument("--reply-file", type=Path, help="Publish a completed reply file")
        if command == "fail":
            action.add_argument(
                "--reason", required=True, choices=("launch_failed", "exited", "timeout"),
            )
        if command == "exec":
            action.add_argument("argv", nargs=argparse.REMAINDER)
    return root


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the manual command line and enforce the complete-mode contract."""
    command = parser()
    args = command.parse_args(argv)
    if args.command == "complete":
        if args.all_cases and args.case is not None:
            command.error("--all cannot be combined with a single case")
        if not args.all_cases and args.case is None:
            command.error("Pass one suite/case ID or --all")
    return args


def main() -> int:
    args = parse_arguments()
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
