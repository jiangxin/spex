"""Start/stop host wall-clock timing for current-host Spex-eval turns.

Manual workers must not invent timestamps. Call ``start`` immediately before
sending ``next_input``, then ``stop`` after the final user-facing reply is
ready. ``stop`` writes the handoff sidecars that ``collect`` /
``collect_handoff.py`` already understand:

- ``_handoff/<suite>-<case>-turnN.host-duration-ms``
- ``_handoff/<suite>-<case>-turnN.host-wall-clock.json``

Duration comes from the ``started_at`` / ``ended_at`` wall-clock stamps
because hosts may virtualize ``CLOCK_MONOTONIC`` per process.

Usage (from repository root)::

    python3 eval/spex/host_turn_timer.py start \\
      --sandbox eval/spex/runs/TIMESTAMP --suite docs --case analyze-incident --turn 1
    # ... execute the Spex turn ...
    python3 eval/spex/host_turn_timer.py stop \\
      --sandbox eval/spex/runs/TIMESTAMP --suite docs --case analyze-incident --turn 1
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import collect_handoff  # noqa: E402
import performance  # noqa: E402

SCHEMA_VERSION = 1
IDENTIFIER = performance.IDENTIFIER


def reply_stem(sandbox: Path, suite: str, case_id: str, turn: int) -> Path:
    return collect_handoff.handoff_reply(sandbox, suite, case_id, turn)


def pending_path(reply: Path) -> Path:
    return reply.with_suffix(".host-turn-timer.json")


def wall_clock_duration_ms(started_at: str, ended_at: str) -> int | None:
    """Wall-clock duration, or None when a stamp is unusable."""
    return performance.delta_ms(
        performance.timestamp(started_at), performance.timestamp(ended_at),
    )


def validate_identity(suite: str, case_id: str, turn: int) -> None:
    if not IDENTIFIER.fullmatch(suite):
        raise SystemExit(f"Invalid suite: {suite!r}")
    if not IDENTIFIER.fullmatch(case_id):
        raise SystemExit(f"Invalid case id: {case_id!r}")
    if type(turn) is not int or turn < 1:
        raise SystemExit(f"Turn must be a positive integer, got {turn!r}")


def start_timer(sandbox: Path, suite: str, case_id: str, turn: int) -> dict:
    validate_identity(suite, case_id, turn)
    handoff = sandbox / "_handoff"
    if sandbox.is_symlink() or not sandbox.is_dir():
        raise SystemExit(f"Sandbox is not a directory: {sandbox}")
    handoff.mkdir(parents=True, exist_ok=True)
    reply = reply_stem(sandbox, suite, case_id, turn)
    if reply.parent.is_symlink():
        raise SystemExit("Refusing to use a symlink handoff directory")
    pending = pending_path(reply)
    if pending.is_symlink() or reply.is_symlink():
        raise SystemExit("Refusing to write through a symlink handoff path")
    if pending.is_file():
        raise SystemExit(
            f"Timer already started for {suite}/{case_id} turn {turn}; "
            "call stop first or remove the pending file"
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "suite": suite,
        "case_id": case_id,
        "turn": turn,
        "started_at": performance.wall_clock_iso(),
        "monotonic": time.monotonic(),
    }
    try:
        with pending.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream)
    except FileExistsError as error:
        raise SystemExit("Timer already started") from error
    return {
        "action": "start",
        "pending": str(pending),
        "started_at": payload["started_at"],
    }


def stop_timer(sandbox: Path, suite: str, case_id: str, turn: int) -> dict:
    validate_identity(suite, case_id, turn)
    if sandbox.is_symlink() or not sandbox.is_dir():
        raise SystemExit(f"Sandbox is not a directory: {sandbox}")
    reply = reply_stem(sandbox, suite, case_id, turn)
    if reply.parent.is_symlink():
        raise SystemExit("Refusing to use a symlink handoff directory")
    pending = pending_path(reply)
    if pending.is_symlink() or reply.is_symlink():
        raise SystemExit("Refusing to write through a symlink handoff path")
    if not pending.is_file():
        raise SystemExit(
            f"No pending timer for {suite}/{case_id} turn {turn}; call start first"
        )
    try:
        data = json.loads(pending.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(f"Unreadable pending timer: {error}") from error
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != SCHEMA_VERSION
        or data.get("suite") != suite
        or data.get("case_id") != case_id
        or data.get("turn") != turn
        or not isinstance(data.get("started_at"), str)
        or type(data.get("monotonic")) is not float
        or not math.isfinite(data["monotonic"])
    ):
        raise SystemExit("Pending timer does not match this suite/case/turn")
    ended_at = performance.wall_clock_iso()
    duration_ms = wall_clock_duration_ms(data["started_at"], ended_at)
    if duration_ms is None:
        duration_ms = max(0, round((time.monotonic() - data["monotonic"]) * 1000))
    wall = {
        "started_at": data["started_at"],
        "ended_at": ended_at,
        "duration_ms": duration_ms,
    }
    duration_sidecar = collect_handoff.host_duration_sidecar(reply)
    wall_sidecar = collect_handoff.host_wall_clock_sidecar(reply)
    if any(path.is_symlink() or (path.exists() and not path.is_file())
           for path in (duration_sidecar, wall_sidecar)):
        raise SystemExit("Refusing to overwrite an unsafe timing sidecar")
    duration_sidecar.write_text(f"{duration_ms}\n", encoding="utf-8")
    wall_sidecar.write_text(json.dumps(wall, indent=2) + "\n", encoding="utf-8")
    pending.unlink()
    return {
        "action": "stop",
        "duration_ms": duration_ms,
        "started_at": wall["started_at"],
        "ended_at": ended_at,
        "host_duration_ms": str(duration_sidecar),
        "host_wall_clock": str(wall_sidecar),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "stop"):
        command = sub.add_parser(name, help=f"{name} host turn timing")
        command.add_argument("--sandbox", type=Path, required=True)
        command.add_argument("--suite", required=True)
        command.add_argument("--case", required=True, dest="case_id")
        command.add_argument("--turn", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sandbox = args.sandbox.absolute()
    if args.command == "start":
        result = start_timer(sandbox, args.suite, args.case_id, args.turn)
    else:
        result = stop_timer(sandbox, args.suite, args.case_id, args.turn)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
