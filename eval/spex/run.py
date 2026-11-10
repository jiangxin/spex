"""Run and collect Spex evaluation trials."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from evidence import EXPECTATIONS, capture, check_gate, digest, encode, persist_turn
from transport import (
    SESSION_ID,
    HostTurn,
    TransportError,
    codex_turn,
    host_version,
    parse_events,
    save_host_trace,
)
from workspace import IDENTIFIER, Case, Trial, prepare_trial, select_cases, verify_spex_roots

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
SUITES = HERE / "suites"
RUNS = HERE / "runs"
TIMEOUT = 600


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encode(value) + b"\n")
    temporary.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def setup(case: Case, output: Path, args: argparse.Namespace, repeat: int = 1) -> Trial:
    for turn in case.definition["turns"]:
        if any(check not in EXPECTATIONS for check in turn["checks"]):
            raise ValueError(f"Unknown workflow check in {case.suite}/{case.id}")
    trial = prepare_trial(SOURCE, case, args.spex_ref)
    try:
        persist_turn(output, 0, capture(trial))
        write_json(output / "trial.json", {
            "schema_version": 1, "suite": case.suite, "case_id": case.id,
            "case": case.definition, "case_hash": digest(encode(case.definition)),
            "trial_directory": str(trial.directory), "spex_ref": trial.ref,
            "host": args.host, "host_version": args.host_version, "model": args.model,
            "invocation": args.invocation, "repeat": repeat, "session": "",
            "turn_results": [], "verdict": "pending",
        })
    except BaseException:
        shutil.rmtree(trial.directory)
        raise
    return trial


def acceptance(trial: Trial, suite: str, selector: str) -> dict:
    script = SUITES / suite / "acceptance.py"
    if not IDENTIFIER.fullmatch(selector) or not script.is_file() or script.is_symlink():
        raise ValueError("Invalid acceptance selector or script")
    # Acceptance may invoke code authored by the evaluated model. Run with a
    # small environment and deny network access and all filesystem writes.
    env = {key: trial.env[key] for key in (
        "HOME", "PATH", "SPEX_CONFIG_FILE", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
        "GIT_ATTR_NOSYSTEM", "PYTHONNOUSERSITE",
    )}
    env.update(GIT_OPTIONAL_LOCKS="0", PYTHONDONTWRITEBYTECODE="1")
    paths = {
        trial.directory.resolve(), script.parent.resolve(), Path(sys.prefix).resolve(),
        Path(sys.base_prefix).resolve(), Path("/usr"), Path("/System"),
        Path("/Library/Developer/CommandLineTools"), Path("/dev"),
    }
    parents = {parent for path in paths for parent in path.parents}
    # Framework Python needs to open the ancestor directories during startup.
    # Literal rules allow those directories without allowing sibling files.
    allowed = " ".join(
        f"({kind} {json.dumps(str(path))})"
        for kind, entries in (("subpath", paths), ("literal", parents))
        for path in sorted(entries)
    )
    policy = f"""
    (version 1)
    (allow default)
    (deny network*)
    (deny file-write*)
    (allow file-write* (literal "/dev/null"))
    (deny file-read-data)
    (allow file-read-data {allowed})
    """
    try:
        result = subprocess.run(
            ["/usr/bin/sandbox-exec", "-p", policy, sys.executable, "-I", str(script),
             str(trial.repo), selector],
            cwd=trial.repo, env=env, capture_output=True, text=True, timeout=30, check=False,
        )
        data = json.loads(result.stdout)
        if (result.returncode not in (0, 1) or type(data["passed"]) is not bool
                or data["passed"] != (result.returncode == 0)):
            raise ValueError("Invalid acceptance result")
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        raise TransportError("acceptance_error") from error
    return data


def store_turn(output: Path, trial: Trial, metadata: dict, host: HostTurn) -> None:
    index = len(metadata["turn_results"])
    turn = metadata["case"]["turns"][index]
    previous = read_json(output / f"turn-{index}.json")
    verify_spex_roots(trial)
    state = capture(trial)
    result = acceptance(trial, metadata["suite"], turn["acceptance"]) if turn.get(
        "acceptance"
    ) else None
    current = persist_turn(
        output, index + 1, state, user_input=turn["input"], reply=host.reply,
        events=host.events, acceptance=result,
    )
    checks = [check_gate(check, previous, current) for check in turn["checks"]]
    if result is not None:
        checks.append({
            "check_id": turn["acceptance"], "phase": "acceptance",
            "verdict": "pass" if result["passed"] else "fail",
            "evidence_refs": [current["artifacts"]["acceptance"]["id"]],
        })
    turns = metadata["case"]["turns"]
    if index + 1 < len(turns) and not turns[index + 1]["input"].startswith("/spex "):
        checks.append({
            "check_id": "requests-clarification", "phase": "continuation",
            "verdict": "pass" if re.search(r"[?？]|\b(?:please|choose|select)\b|请选择|请确认",
                                          host.reply, re.I) else "fail",
            "evidence_refs": [current["artifacts"]["reply"]["id"]],
        })
    metadata["session"] = host.session
    metadata["turn_results"].append({"turn": index + 1, "checks": checks})
    metadata["verdict"] = trial_verdict(metadata["turn_results"], index + 1 == len(turns))
    write_json(output / "trial.json", metadata)


def trial_verdict(turn_results: list, final: bool) -> str:
    verdicts = {check["verdict"] for turn in turn_results for check in turn["checks"]}
    if "fail" in verdicts:
        return "fail"
    if not final:
        return "pending"
    if "insufficient_evidence" in verdicts:
        return "insufficient_evidence"
    return "pass"


def drive(output: Path, trial: Trial, args: argparse.Namespace) -> dict:
    metadata = read_json(output / "trial.json")
    for index, turn in enumerate(metadata["case"]["turns"]):
        verify_spex_roots(trial)
        message = turn["input"]
        if message.startswith("/spex "):
            message = f"$spex\n{message}"
            if index == 0:
                message += f"\nUse the Spex skill at {trial.skill / 'SKILL.md'}."
        host = codex_turn(
            trial, message, args.model, args.timeout, metadata["session"],
            trace_path=output / f"host-{index + 1}.jsonl",
        )
        store_turn(output, trial, metadata, host)
        if metadata["verdict"] != "pending":
            break
    return metadata


def automatic(case: Case, output: Path, args: argparse.Namespace, repeat: int) -> dict:
    trial = None
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    try:
        trial = setup(case, output, args, repeat)
        result = drive(output, trial, args)
    except (OSError, ValueError, subprocess.SubprocessError, TransportError) as error:
        manifest = output / "trial.json"
        result = read_json(manifest) if manifest.is_file() else {
            "suite": case.suite, "case_id": case.id, "repeat": repeat, "model": args.model,
        }
        result.update(verdict="run_error", error=(
            str(error) if isinstance(error, TransportError) else "fixture_or_capture_error"
        ))
    finally:
        if trial is not None:
            shutil.rmtree(trial.directory)
    result["duration_ms"] = round((time.monotonic() - started) * 1000)
    write_json(output / "trial.json", result)
    return result


def manual_result(output: Path, args: argparse.Namespace) -> dict:
    metadata = read_json(output / "trial.json")
    if metadata["host"] == "codex" or metadata["verdict"] != "pending":
        raise ValueError("Expected a pending manual trial")
    if not SESSION_ID.fullmatch(args.session) or metadata["session"] not in ("", args.session):
        raise ValueError("Use the same valid session ID for all turns of this trial")
    trial = Trial(Path(metadata["trial_directory"]), metadata["spex_ref"])
    reply = args.reply.read_text(encoding="utf-8")
    if not reply.strip():
        raise ValueError("The reply file is empty")
    host = HostTurn(args.session, reply, None, "")
    if args.events is not None:
        raw = args.events.read_text(encoding="utf-8")
        save_host_trace(output / f"host-{len(metadata['turn_results']) + 1}.jsonl", raw)
        trace = parse_events(raw, args.session)
        if trace.reply != reply.strip():
            raise ValueError("The supplied reply and trace disagree")
        host = trace
    store_turn(output, trial, metadata, host)
    return instructions(output, trial, metadata)


def instructions(output: Path, trial: Trial, metadata: dict) -> dict:
    message = None
    if metadata["verdict"] == "pending":
        message = metadata["case"]["turns"][len(metadata["turn_results"])]["input"]
        if message.startswith("/spex ") and metadata["invocation"] == "explicit":
            message = f"Use the Spex skill at {trial.skill / 'SKILL.md'}.\n{message}"
    return {
        "trial": str(output), "workspace": str(trial.repo), "skill": str(trial.skill),
        "session": metadata["session"], "verdict": metadata["verdict"], "next_input": message,
        "environment": {key: trial.env[key] for key in (
            "HOME", "SPEX_CONFIG_FILE", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"
        )},
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("list", "run", "prepare"):
        command = sub.add_parser(name)
        command.add_argument("--suite", default="")
        command.add_argument("--case", default="")
        command.add_argument("--tag", default="")
        if name != "list":
            command.add_argument("--model", required=True)
            command.add_argument("--spex-ref", default="HEAD")
        if name == "run":
            command.add_argument("--repeat", type=int, default=1)
            command.add_argument("--timeout", type=int, default=TIMEOUT)
        if name == "prepare":
            command.add_argument("--host", choices=("cursor", "claude-code"), required=True)
            command.add_argument("--host-version", required=True)
            command.add_argument("--invocation", choices=("native", "explicit"), default="explicit")
    collect = sub.add_parser("collect")
    collect.add_argument("trial", type=Path)
    collect.add_argument("--session", required=True)
    collect.add_argument("--reply", type=Path, required=True)
    collect.add_argument("--events", type=Path)
    return root


def execute(args: argparse.Namespace) -> dict:
    if args.command == "collect":
        path = args.trial.resolve()
        if not path.is_relative_to(RUNS.resolve()):
            raise ValueError("Expected a trial path under eval/spex/runs")
        return manual_result(path, args)
    cases = select_cases(SUITES, suite=args.suite, case_id=args.case, tag=args.tag)
    if args.command == "list":
        return {"cases": [{"suite": case.suite, "id": case.id,
                           "tags": case.definition["tags"]} for case in cases]}
    if not cases or args.command == "prepare" and len(cases) != 1:
        raise ValueError("Select cases for run, or exactly one case for prepare")
    output = RUNS / uuid.uuid4().hex
    if args.command == "prepare":
        trial = setup(cases[0], output, args)
        return instructions(output, trial, read_json(output / "trial.json"))
    if args.repeat < 1 or args.timeout < 1:
        raise ValueError("Repeat and timeout must be positive")
    args.host, args.host_version, args.invocation = "codex", host_version(), "explicit"
    rows = [
        automatic(case, output / case.suite / case.id / str(repeat), args, repeat)
        for case in cases for repeat in range(1, args.repeat + 1)
    ]
    return {"run": str(output), "trials": rows}


def main() -> int:
    args = parser().parse_args()
    try:
        result = execute(args)
    except (ValueError, OSError, TransportError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
