"""Run and collect Spex evaluation trials."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from calibration import evaluate, load_samples
from compare import calibration_keys, collection_mode, compare, diagnosis, load_run, markdown
from evidence import EXPECTATIONS, capture, check_gate, digest, encode, persist_turn
from judge import (
    PROMPT,
    PROMPT_VERSION,
    apply_grades,
    codex_judge,
    export_packet,
    final_verdict,
    grade,
    packet_for,
    rubric_for,
)
from transport import (
    SESSION_ID,
    CodexRuntime,
    HostTurn,
    TransportError,
    codex_turn,
    parse_events,
    prepare_codex_runtime,
    save_host_trace,
)
from workspace import (
    IDENTIFIER,
    WORKSPACE_NAME,
    Case,
    Trial,
    allocate_sandbox,
    case_dir,
    prepare_trial,
    select_cases,
    verify_sandbox,
    verify_trial_workspace,
)

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
SUITES = HERE / "suites"
RUNS = HERE / "runs"
TIMEOUT = 600


def cleanup_hint(sandbox: Path) -> str:
    return f"Please delete the sandbox manually when finished: {sandbox}"


def resolve_sandbox(path: Path | None = None) -> Path:
    """Return an existing sandbox under RUNS, or allocate a new timestamp sandbox."""
    if path is None:
        sandbox = allocate_sandbox(RUNS)
        verify_sandbox(sandbox, SOURCE)
        return sandbox
    sandbox = Path(path).resolve()
    if not sandbox.is_relative_to(RUNS.resolve()) or sandbox.is_symlink():
        raise ValueError("Expected a sandbox path under eval/spex/runs")
    verify_sandbox(sandbox, SOURCE)
    return sandbox


def iter_trial_paths(sandbox: Path) -> list[Path]:
    trials = []
    for path in sorted(sandbox.rglob("trial.json")):
        if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
            continue
        # Evidence lives beside workspace/, never inside the trial workspace tree.
        if WORKSPACE_NAME in path.relative_to(sandbox).parts:
            continue
        trials.append(path)
    return trials


TRACE_CHECK_IDS = frozenset({"post-action", "no-post-action"})


def earliest_non_pass(turn_results: list) -> str | None:
    for turn in turn_results or []:
        for check in turn.get("checks") or []:
            if check.get("verdict") != "pass":
                return f"turn{turn.get('turn')}:{check.get('check_id')}={check.get('verdict')}"
    return None


def classify_checks(metadata: dict) -> dict:
    """Split non-pass checks into observed fails vs evidence gaps."""
    observed_fails: list[str] = []
    evidence_gaps: list[str] = []
    manual = metadata.get("collection") == "manual"
    for turn in metadata.get("turn_results") or []:
        index = turn.get("turn")
        for check in turn.get("checks") or []:
            check_id = str(check.get("check_id") or "")
            label = f"turn{index}:{check_id}={check.get('verdict')}"
            verdict = check.get("verdict")
            if verdict == "fail":
                observed_fails.append(label)
            elif verdict == "insufficient_evidence":
                evidence_gaps.append(label)
                if manual and check_id in TRACE_CHECK_IDS:
                    # Manual hosts often omit Codex-style --events; treat as gap.
                    pass
    if observed_fails and evidence_gaps:
        kind = "mixed"
    elif observed_fails:
        kind = "fail"
    elif evidence_gaps:
        kind = "evidence_gap"
    else:
        kind = "pass"
    return {
        "classification": kind,
        "observed_fails": observed_fails,
        "evidence_gaps": evidence_gaps,
    }


def render_summary_markdown(report: dict) -> str:
    lines = [
        f"# Spex eval summary: {Path(report['sandbox']).name}",
        "",
        f"- Sandbox: `{report['sandbox']}`",
        f"- Trials: {len(report['trials'])}",
        f"- Counts: {json.dumps(report.get('counts') or {}, sort_keys=True)}",
        f"- Classifications: {json.dumps(report.get('classifications') or {}, sort_keys=True)}",
        f"- Cleanup: {report['cleanup_hint']}",
        "",
        "| Case | Final | Class | Observed fails | Evidence gaps | Path |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["trials"]:
        case = f"{row.get('suite')}/{row.get('case_id')}"
        fails = ", ".join(row.get("observed_fails") or []) or "—"
        gaps = ", ".join(row.get("evidence_gaps") or []) or "—"
        lines.append(
            f"| {case} | {row.get('final_verdict')} | {row.get('classification')} | "
            f"{fails} | {gaps} | `{row.get('trial')}` |"
        )
    lines.extend([
        "",
        "## How to read results",
        "",
        "- **fail / observed fails**: deterministic or acceptance checks failed.",
        "- **evidence_gap / insufficient_evidence**: required artifacts (often "
        "tool traces via `--events`) were missing. Common for manual "
        "`collection` without a Codex-style transcript; not proof the workflow "
        "failed.",
        "- Hard verdicts still take precedence over semantic judge scores.",
        "",
    ])
    return "\n".join(lines)


def summarize_sandbox(sandbox: Path) -> dict:
    sandbox = resolve_sandbox(sandbox)
    rows = []
    counts: dict[str, int] = {}
    classifications: dict[str, int] = {}
    hosts: set[str] = set()
    models: set[str] = set()
    for path in iter_trial_paths(sandbox):
        metadata = read_json(path)
        judge_path = path.parent / "judge.json"
        judge = {}
        if judge_path.is_file() and not judge_path.is_symlink():
            judge = read_json(judge_path)
        final = judge.get("verdict") or metadata.get("verdict")
        hosts.add(str(metadata.get("host") or "unknown"))
        models.add(str(metadata.get("model") or "unknown"))
        split = classify_checks(metadata)
        row = {
            "suite": metadata.get("suite"),
            "case_id": metadata.get("case_id"),
            "trial": str(path.parent.relative_to(sandbox)),
            "hard_verdict": metadata.get("verdict"),
            "final_verdict": final,
            "host": metadata.get("host"),
            "model": metadata.get("model"),
            "collection": metadata.get("collection"),
            "earliest_non_pass": earliest_non_pass(metadata.get("turn_results") or []),
            **split,
        }
        rows.append(row)
        counts[str(final)] = counts.get(str(final), 0) + 1
        classifications[split["classification"]] = (
            classifications.get(split["classification"], 0) + 1
        )
    report = {
        "schema_version": 1,
        "sandbox": str(sandbox),
        "hosts": sorted(hosts),
        "models": sorted(models),
        "trials": rows,
        "counts": counts,
        "classifications": classifications,
        "cleanup_hint": cleanup_hint(sandbox),
    }
    write_json(sandbox / "manifest.json", {
        "schema_version": 1,
        "sandbox": str(sandbox),
        "hosts": report["hosts"],
        "models": report["models"],
        "trials": [
            {"suite": row["suite"], "case_id": row["case_id"], "path": row["trial"]}
            for row in rows
        ],
        "cleanup_hint": report["cleanup_hint"],
    })
    write_json(sandbox / "report.json", report)
    (sandbox / "report.md").write_text(render_summary_markdown(report), encoding="utf-8")
    return {
        **report,
        "manifest": str(sandbox / "manifest.json"),
        "report": str(sandbox / "report.md"),
        "report_json": str(sandbox / "report.json"),
    }


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encode(value) + b"\n")
    temporary.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_hash(case: Case) -> str:
    suite = case.fixture.parent.parent
    paths = [path for path in case.fixture.rglob("*") if path.is_file()]
    paths.extend(path for name in ("setup.py", "acceptance.py")
                 if (path := suite / name).is_file())
    return digest(encode({str(path.relative_to(suite)): digest(path.read_bytes())
                          for path in paths}))


def prune_empty_parents(path: Path, stop: Path) -> None:
    """Remove empty directories from path up to (but not including) stop."""
    stop = stop.resolve()
    current = path.resolve()
    while current != stop and stop in current.parents:
        if not current.is_dir() or any(current.iterdir()):
            break
        current.rmdir()
        current = current.parent


def cleanup_failed_case(sandbox: Path, output: Path, *, remove_sandbox: bool) -> None:
    """Remove a failed case directory; drop a fresh empty sandbox when unused."""
    if output.exists():
        shutil.rmtree(output, ignore_errors=True)
    prune_empty_parents(output.parent, sandbox)
    if remove_sandbox and sandbox.exists() and not iter_trial_paths(sandbox):
        shutil.rmtree(sandbox, ignore_errors=True)


def setup(
    case: Case, output: Path, args: argparse.Namespace, repeat: int = 1,
    *, sandbox: Path,
) -> Trial:
    for turn in case.definition["turns"]:
        if any(check not in EXPECTATIONS for check in turn["checks"]):
            raise ValueError(f"Unknown workflow check in {case.suite}/{case.id}")
    output.mkdir(parents=True, exist_ok=False)
    try:
        trial = prepare_trial(SOURCE, case, args.spex_ref, parent=output)
        persist_turn(output, 0, capture(trial))
        write_json(output / "trial.json", {
            "schema_version": 1, "suite": case.suite, "case_id": case.id,
            "case": case.definition, "case_hash": digest(encode(case.definition)),
            "fixture_hash": fixture_hash(case),
            "sandbox": str(sandbox), "trial_directory": str(trial.directory),
            "spex_ref": trial.ref,
            "host": args.host, "host_version": args.host_version, "model": args.model,
            "collection": "manual" if args.command == "prepare" else "automatic",
            "invocation": args.invocation, "repeat": repeat, "session": "",
            "judge_model": getattr(args, "judge_model", ""),
            "turn_results": [], "verdict": "pending",
        })
    except BaseException:
        if output.exists():
            shutil.rmtree(output, ignore_errors=True)
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
    try:
        located = subprocess.check_output(
            ["/usr/bin/xcrun", "--find", "git"], env=env, text=True, timeout=10,
        )
        system_git = Path(located.strip()).resolve(strict=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise TransportError("acceptance_error") from error
    env["PATH"] = str(system_git.parent) + os.pathsep + env["PATH"]
    paths = {
        trial.directory.resolve(), script.parent.resolve(), Path(sys.prefix).resolve(),
        Path(sys.base_prefix).resolve(), Path("/usr"), Path("/System"),
        Path("/dev"),
    }
    parents = {parent for path in paths for parent in path.parents}
    # Framework Python needs to open the ancestor directories during startup.
    # Literal rules allow those directories without allowing sibling files.
    allowed = " ".join(
        f"({kind} {json.dumps(str(path))})"
        for kind, entries in (
            ("subpath", paths), ("literal", parents | {system_git, *system_git.parents}),
        )
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
    verify_trial_workspace(trial)
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


def score_trial(
    output: Path, metadata: dict, model: str, timeout: int,
    *, runtime: CodexRuntime | None = None,
) -> dict:
    record = {
        "model": model, "prompt_version": PROMPT_VERSION, "prompt_hash": digest(PROMPT.encode()),
        "hard_verdict": metadata.get("hard_verdict", metadata["verdict"]),
    }
    try:
        if not IDENTIFIER.fullmatch(metadata["suite"]):
            raise ValueError("Invalid suite")
        rubric = SUITES / metadata["suite"] / "rubrics.json"
        version, criteria = rubric_for(rubric, metadata["case_id"])
        packet = packet_for(output, metadata, criteria)
        record.update(
            rubric_version=version, rubric_hash=digest(encode(criteria)),
            suite_rubric_hash=digest(rubric.read_bytes()),
            evidence_hash=digest(encode(packet["evidence"])),
        )
        adapter = None
        if runtime is not None:
            def adapter(prompt, judge_model, judge_timeout, current=runtime):
                return codex_judge(prompt, judge_model, judge_timeout, runtime=current)
        record.update(grade(packet, model, timeout, adapter=adapter))
    except (OSError, ValueError, TypeError, KeyError):
        record.update(error="judge_input_error", results=[])
    record["verdict"] = final_verdict(record["hard_verdict"], record)
    return record


def judge_trial(
    output: Path, metadata: dict, model: str, timeout: int,
    *, runtime: CodexRuntime | None = None,
) -> None:
    if not model or metadata["verdict"] in ("pending", "run_error"):
        return
    record = score_trial(output, metadata, model, timeout, runtime=runtime)
    metadata["hard_verdict"] = record["hard_verdict"]
    metadata["verdict"] = record["verdict"]
    write_json(output / "judge.json", record)


def resolve_trial(path: Path) -> Path:
    trial = path.resolve()
    if (
        not trial.is_relative_to(RUNS.resolve())
        or trial.is_symlink()
        or not trial.is_dir()
        or not (trial / "trial.json").is_file()
        or (trial / "trial.json").is_symlink()
    ):
        raise ValueError("Expected a trial path under eval/spex/runs")
    return trial


def trial_packet(output: Path, metadata: dict) -> tuple[dict, int, list]:
    if not IDENTIFIER.fullmatch(metadata["suite"]):
        raise ValueError("Invalid suite")
    if metadata["verdict"] in ("pending", "run_error"):
        raise ValueError("Trial is not ready for judging")
    rubric = SUITES / metadata["suite"] / "rubrics.json"
    version, criteria = rubric_for(rubric, metadata["case_id"])
    return packet_for(output, metadata, criteria), version, criteria


def export_judge(output: Path) -> dict:
    metadata = read_json(output / "trial.json")
    packet, version, criteria = trial_packet(output, metadata)
    exported = export_packet(packet)
    rubric = SUITES / metadata["suite"] / "rubrics.json"
    hard = metadata.get("hard_verdict", metadata["verdict"])
    payload = {
        "schema_version": 1,
        "suite": metadata["suite"],
        "case_id": metadata["case_id"],
        "hard_verdict": hard,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": digest(PROMPT.encode()),
        "rubric_version": version,
        "rubric_hash": digest(encode(criteria)),
        "suite_rubric_hash": digest(rubric.read_bytes()),
        "evidence_hash": digest(encode(packet["evidence"])),
        "packet": exported["packet"],
        "insufficient": exported["insufficient"],
    }
    packet_path = output / "judge-packet.json"
    prompt_path = output / "judge-prompt.txt"
    write_json(packet_path, payload)
    prompt_path.write_text(exported["prompt"], encoding="utf-8")
    return {
        "trial": str(output),
        "packet": str(packet_path),
        "prompt": str(prompt_path),
        "hard_verdict": hard,
        "criteria": len(exported["packet"]["criteria"]),
        "insufficient": len(exported["insufficient"]),
    }


def import_judge(output: Path, grades: Path, model: str) -> dict:
    metadata = read_json(output / "trial.json")
    packet, version, criteria = trial_packet(output, metadata)
    rubric = SUITES / metadata["suite"] / "rubrics.json"
    hard = metadata.get("hard_verdict", metadata["verdict"])
    record = {
        "model": model or "external",
        "source": "external",
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": digest(PROMPT.encode()),
        "hard_verdict": hard,
        "rubric_version": version,
        "rubric_hash": digest(encode(criteria)),
        "suite_rubric_hash": digest(rubric.read_bytes()),
        "evidence_hash": digest(encode(packet["evidence"])),
    }
    raw = grades.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError("The grades file is empty")
    record.update(apply_grades(packet, raw))
    record["verdict"] = final_verdict(hard, record)
    metadata["hard_verdict"] = hard
    metadata["verdict"] = record["verdict"]
    write_json(output / "judge.json", record)
    write_json(output / "trial.json", metadata)
    return {
        "trial": str(output),
        "verdict": record["verdict"],
        "hard_verdict": hard,
        "results": len(record["results"]),
        "error": record.get("error"),
        "judge": str(output / "judge.json"),
    }


def replay(run_id: str, model: str, timeout: int, *, runtime: CodexRuntime | None = None) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Expected a saved run ID")
    output = RUNS.resolve() / run_id
    if output.is_symlink() or not output.is_dir():
        raise ValueError("Saved run does not exist")
    files = sorted({*output.glob("trial.json"), *output.glob("*/*/*/trial.json")})
    if not files:
        raise ValueError("No saved trials in run")
    results = []
    for path in files:
        if path.resolve() != path:
            raise ValueError("Unexpected linked trial")
        metadata = read_json(path)
        hard = metadata.get("hard_verdict", metadata["verdict"])
        record = (
            {"verdict": hard, "skipped": True} if hard in ("pending", "run_error")
            else score_trial(path.parent, metadata, model, timeout, runtime=runtime)
        )
        results.append({"trial": str(path.parent.relative_to(output)), **record})
    directory = output / "rejudges" / uuid.uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    report = {"run": str(output), "model": model, "judgments": results}
    path = directory / "report.json"
    write_json(path, report)
    return {**report, "report": str(path)}


def calibrate(args: argparse.Namespace, *, runtime: CodexRuntime | None = None) -> dict:
    suite_path = HERE / "calibration" / f"{args.split}.json"
    calibration = load_samples(suite_path, SUITES)
    adapter = None
    if runtime is not None:
        def adapter(prompt, judge_model, judge_timeout, current=runtime):
            return codex_judge(prompt, judge_model, judge_timeout, runtime=current)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        grades = list(pool.map(
            lambda sample: grade(
                sample["packet"], args.judge_model, args.timeout, adapter=adapter,
            ),
            calibration["samples"],
        ))
    report = evaluate(calibration, grades, args.judge_model, args.split)
    directory = RUNS / "calibrations"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.json"
    write_json(path, report)
    return {**report, "report": str(path)}


def compare_runs(args: argparse.Namespace) -> dict:
    ids = (args.baseline, args.candidate, args.baseline_rejudge, args.candidate_rejudge)
    if any(value and not re.fullmatch(r"[a-f0-9]{32}", value) for value in ids):
        raise ValueError("Expected saved run and rejudge IDs")
    if args.timeout < 1:
        raise ValueError("Timeout must be positive")
    left = load_run(RUNS, args.baseline, args.baseline_rejudge)
    right = load_run(RUNS, args.candidate, args.candidate_rejudge)
    keys = calibration_keys(RUNS / "calibrations", HERE / "calibration" / "frozen.json")
    report = compare(left, right, keys)
    report["runs"] = list(ids)
    try:
        report["diagnosis"] = diagnosis(report, codex_judge, args.judge_model, args.timeout)
    except (ValueError, OSError, TypeError, KeyError, subprocess.SubprocessError, TransportError):
        report.update(diagnosis=[], diagnostic_error="diagnostic_judge_error")
    directory = RUNS / "comparisons" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    write_json(directory / "report.json", report)
    (directory / "report.md").write_text(markdown(report), encoding="utf-8")
    return {**report, "report": str(directory / "report.json"),
            "markdown": str(directory / "report.md")}


def drive(output: Path, trial: Trial, args: argparse.Namespace) -> dict:
    metadata = read_json(output / "trial.json")
    runtime = getattr(args, "codex_runtime", None)
    for index, turn in enumerate(metadata["case"]["turns"]):
        verify_trial_workspace(trial)
        message = turn["input"]
        if message.startswith("/spex "):
            message = f"$spex\n{message}"
            if index == 0:
                message += f"\nUse the Spex skill at {trial.skill / 'SKILL.md'}."
        host = codex_turn(
            trial, message, args.model, args.timeout, metadata["session"],
            trace_path=output / f"host-{index + 1}.jsonl", runtime=runtime,
        )
        store_turn(output, trial, metadata, host)
        if metadata["verdict"] != "pending":
            break
    return metadata


def automatic(
    case: Case, output: Path, args: argparse.Namespace, repeat: int, *, sandbox: Path,
) -> dict:
    trial = None
    started = time.monotonic()
    try:
        trial = setup(case, output, args, repeat, sandbox=sandbox)
        result = drive(output, trial, args)
    except (OSError, ValueError, subprocess.SubprocessError, TransportError) as error:
        manifest = output / "trial.json"
        result = read_json(manifest) if manifest.is_file() else {
            "suite": case.suite, "case_id": case.id, "repeat": repeat, "model": args.model,
        }
        result.update(verdict="run_error", error=(
            str(error) if isinstance(error, TransportError) else "fixture_or_capture_error"
        ))
    judge_trial(
        output, result, getattr(args, "judge_model", ""), args.timeout,
        runtime=getattr(args, "codex_runtime", None),
    )
    result["duration_ms"] = round((time.monotonic() - started) * 1000)
    write_json(output / "trial.json", result)
    return result


def manual_result(output: Path, args: argparse.Namespace) -> dict:
    metadata = read_json(output / "trial.json")
    if collection_mode(metadata) != "manual" or metadata["verdict"] != "pending":
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
    # Manual / current-host collection keeps deterministic checks only. Semantic
    # grades are imported separately so judging does not require Codex CLI.
    write_json(output / "trial.json", metadata)
    return instructions(output, trial, metadata)


def host_name(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "Host must be a lowercase identifier such as codex, qoder, cursor, or other"
        )
    return value


def unknownable(value: str) -> str:
    text = value.strip() or "unknown"
    if not text or "\n" in text or "\0" in text:
        raise argparse.ArgumentTypeError("Expected a single-line model or version label")
    return text[:128]


def instructions(output: Path, trial: Trial, metadata: dict) -> dict:
    message = None
    if metadata["verdict"] == "pending":
        message = metadata["case"]["turns"][len(metadata["turn_results"])]["input"]
        if message.startswith("/spex ") and metadata["invocation"] == "explicit":
            message = f"Use the Spex skill at {trial.skill / 'SKILL.md'}.\n{message}"
    sandbox = Path(metadata["sandbox"])
    return {
        "trial": str(output), "sandbox": str(sandbox),
        "workspace": str(trial.repo), "skill": str(trial.skill),
        "host": metadata["host"], "host_version": metadata["host_version"],
        "model": metadata["model"], "session": metadata["session"],
        "verdict": metadata["verdict"], "next_input": message,
        "handoff": "manual",
        "cleanup_hint": cleanup_hint(sandbox),
        "environment": {key: trial.env[key] for key in (
            "HOME", "PATH", "TMPDIR", "TMPPREFIX", "SPEX_CONFIG_FILE",
            "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
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
            if name == "run":
                command.add_argument("--model", type=unknownable, required=True)
            else:
                command.add_argument("--model", type=unknownable, default="unknown")
            command.add_argument(
                "--judge-model", default=os.environ.get("SPEX_EVAL_JUDGE_MODEL", "")
            )
            command.add_argument("--spex-ref", default="HEAD")
        if name == "run":
            command.add_argument("--repeat", type=int, default=1)
            command.add_argument("--timeout", type=int, default=TIMEOUT)
        if name == "prepare":
            command.add_argument("--host", type=host_name, required=True)
            command.add_argument("--host-version", type=unknownable, default="unknown")
            command.add_argument("--invocation", choices=("native", "explicit"), default="explicit")
            command.add_argument(
                "--sandbox", type=Path, default=None,
                help="Existing runs/YYYY-MM-DD-HH-MM-SS sandbox; allocate one when omitted",
            )
    collect = sub.add_parser("collect")
    collect.add_argument("trial", type=Path)
    collect.add_argument("--session", required=True)
    collect.add_argument("--reply", type=Path, required=True)
    collect.add_argument("--events", type=Path)
    collect.add_argument("--judge-model", default=os.environ.get("SPEX_EVAL_JUDGE_MODEL", ""))
    export = sub.add_parser("export-packet")
    export.add_argument("trial", type=Path)
    imported = sub.add_parser("import-grades")
    imported.add_argument("trial", type=Path)
    imported.add_argument("--grades", type=Path, required=True)
    imported.add_argument("--model", type=unknownable, default="external")
    summary = sub.add_parser("summary")
    summary.add_argument(
        "sandbox", type=Path,
        help="Sandbox directory under eval/spex/runs/YYYY-MM-DD-HH-MM-SS",
    )
    rejudge = sub.add_parser("judge")
    rejudge.add_argument("run_id")
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--split", choices=("frozen", "development"), default="frozen")
    calibration.add_argument("--jobs", type=int, default=2)
    comparison = sub.add_parser("compare")
    comparison.add_argument("baseline")
    comparison.add_argument("candidate")
    comparison.add_argument("--baseline-rejudge")
    comparison.add_argument("--candidate-rejudge")
    for command in (rejudge, calibration, comparison):
        command.add_argument("--judge-model", default=os.environ.get("SPEX_EVAL_JUDGE_MODEL", ""))
        command.add_argument("--timeout", type=int, default=TIMEOUT)
    return root


def execute(args: argparse.Namespace) -> dict:
    if args.command == "compare":
        return compare_runs(args)
    if args.command in ("judge", "calibrate"):
        if not args.judge_model or args.timeout < 1:
            raise ValueError("A judge model and positive timeout are required")
        runtime = prepare_codex_runtime(
            RUNS / ".codex-home", timeout=min(args.timeout, 60),
        )
        if args.command == "judge":
            return replay(args.run_id, args.judge_model, args.timeout, runtime=runtime)
        if not 1 <= args.jobs <= 4:
            raise ValueError("Choose between one and four calibration workers")
        return calibrate(args, runtime=runtime)
    if args.command == "export-packet":
        return export_judge(resolve_trial(args.trial))
    if args.command == "import-grades":
        return import_judge(resolve_trial(args.trial), args.grades, args.model)
    if args.command == "summary":
        return summarize_sandbox(args.sandbox)
    if args.command == "collect":
        return manual_result(resolve_trial(args.trial), args)
    cases = select_cases(SUITES, suite=args.suite, case_id=args.case, tag=args.tag)
    if args.command == "list":
        return {"cases": [{"suite": case.suite, "id": case.id,
                           "tags": case.definition["tags"]} for case in cases]}
    if not cases or args.command == "prepare" and len(cases) != 1:
        raise ValueError("Select cases for run, or exactly one case for prepare")
    if args.command == "prepare":
        allocated = args.sandbox is None
        sandbox = resolve_sandbox(args.sandbox)
        output = case_dir(sandbox, cases[0].suite, cases[0].id)
        try:
            trial = setup(cases[0], output, args, sandbox=sandbox)
        except BaseException:
            cleanup_failed_case(sandbox, output, remove_sandbox=allocated)
            raise
        return instructions(output, trial, read_json(output / "trial.json"))
    if args.repeat < 1 or args.timeout < 1:
        raise ValueError("Repeat and timeout must be positive")
    # Probe Codex once for the whole batch so the same startup failure is not
    # repeated for every trial or judge call.
    runtime = prepare_codex_runtime(RUNS / ".codex-home", timeout=min(args.timeout, 60))
    args.codex_runtime = runtime
    args.host, args.host_version, args.invocation = "codex", runtime.version, "explicit"
    sandbox = resolve_sandbox(None)
    rows = [
        automatic(
            case, case_dir(sandbox, case.suite, case.id, repeat), args, repeat,
            sandbox=sandbox,
        )
        for case in cases for repeat in range(1, args.repeat + 1)
    ]
    return {
        "run": str(sandbox), "sandbox": str(sandbox), "trials": rows,
        "codex_home": str(runtime.home), "cleanup_hint": cleanup_hint(sandbox),
    }


def main() -> int:
    args = parser().parse_args()
    try:
        result = execute(args)
    except (ValueError, OSError, TransportError, subprocess.SubprocessError) as error:
        payload: dict = {"error": str(error)}
        sandbox = getattr(args, "sandbox", None)
        if sandbox is not None:
            try:
                payload["sandbox"] = str(Path(sandbox).resolve())
            except OSError:
                payload["sandbox"] = str(sandbox)
        elif getattr(args, "command", None) in ("prepare", "run", "summary"):
            payload["cleanup_hint"] = (
                f"Please delete unused sandboxes under {RUNS} manually if any remain"
            )
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
