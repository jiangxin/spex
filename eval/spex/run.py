"""Run and collect Spex evaluation trials."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import performance
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
from scheduling import execution, execution_label, ordered_map, worker_count
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
    saved_run_id,
    saved_trial_paths,
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
    return sorted(trials, key=lambda path: trial_order(path.relative_to(sandbox)))


def trial_order(relative: Path) -> tuple:
    return tuple((0, int(part)) if part.isascii() and part.isdecimal() else (1, part)
                 for part in relative.parts)


TRACE_CHECK_IDS = frozenset({"post-action", "no-post-action"})


def earliest_non_pass(turn_results: list) -> str | None:
    for turn in turn_results or []:
        for check in turn.get("checks") or []:
            if check.get("verdict") != "pass":
                return f"turn{turn.get('turn')}:{check.get('check_id')}={check.get('verdict')}"
    return None


def judge_score_summary(judge: dict) -> dict:
    """Aggregate rubric scores from a trial ``judge.json`` record."""
    results = [
        row for row in (judge.get("results") or [])
        if isinstance(row, dict)
    ]
    scored = [
        row for row in results
        if isinstance(row.get("score"), int)
    ]
    score_sum = sum(int(row["score"]) for row in scored)
    # Each criterion is anchored 0–2.
    score_max = 2 * len(scored)
    return {
        "criteria_total": len(results),
        "criteria_scored": len(scored),
        "score_sum": score_sum,
        "score_max": score_max,
        "scores": [
            {
                "criterion_id": row.get("criterion_id"),
                "score": row.get("score"),
                "verdict": row.get("verdict"),
            }
            for row in results
        ],
    }


def aggregate_scores(trials: list[dict]) -> dict:
    """Sandbox-level score totals across trials that have judge results."""
    scored_trials = [row for row in trials if row.get("criteria_scored")]
    score_sum = sum(int(row.get("score_sum") or 0) for row in scored_trials)
    score_max = sum(int(row.get("score_max") or 0) for row in scored_trials)
    return {
        "trials_scored": len(scored_trials),
        "trials_total": len(trials),
        "score_sum": score_sum,
        "score_max": score_max,
        "score_ratio": (
            round(score_sum / score_max, 4) if score_max else None
        ),
    }


def render_improvements_markdown(report: dict) -> str:
    """Render a backlog snippet from summary improvements + score totals."""
    scores = report.get("scores") or {}
    ratio = scores.get("score_ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio:.0%}"
    lines = [
        "# Spex-eval improvement backlog",
        "",
        f"Generated from sandbox `{Path(report['sandbox']).name}`.",
        (
            f"Semantic score: {scores.get('score_sum', 0)}/"
            f"{scores.get('score_max', 0)} ({ratio_text}). "
            f"Verdict counts: {json.dumps(report.get('counts') or {}, sort_keys=True)}. "
            f"Classifications: "
            f"{json.dumps(report.get('classifications') or {}, sort_keys=True)}."
        ),
        "",
        "## Prioritized items",
        "",
    ]
    improvements = report.get("improvements") or []
    if not improvements:
        lines.append(
            "No improvement items derived from available trial evidence."
        )
        lines.append("")
        return "\n".join(lines)
    current = None
    for item in improvements:
        priority = item.get("priority") or "P2"
        if priority != current:
            current = priority
            lines.append(f"### {priority}")
            lines.append("")
        lines.append(
            f"- **{item.get('category')}** (`{item.get('case')}`) — "
            f"{item.get('summary')}"
        )
    lines.append("")
    lines.append(
        "See the sandbox `report.md` for per-trial scores and evidence gaps."
    )
    lines.append("")
    return "\n".join(lines)


def write_improvements_backlog(report: dict, path: Path) -> Path:
    """Write ``IMPROVEMENTS.md`` (or another path) from a summary report."""
    target = Path(path)
    if target.exists() and target.is_symlink():
        raise ValueError(f"Refusing to write through symlink: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_improvements_markdown(report), encoding="utf-8")
    return target



def derive_skill_improvements(trials: list[dict]) -> list[dict]:
    """Prioritized Spex-skill issues derived from hard checks and verdicts.

    Categories: functionality, execution, efficiency. Host-only trace gaps
    are listed as efficiency/evidence friction for the eval harness, not as
    Spex workflow proof-failures.
    """
    items: list[dict] = []
    for row in trials:
        case = f"{row.get('suite')}/{row.get('case_id')}"
        hard = str(row.get("hard_verdict") or "")
        if hard == "run_error":
            items.append({
                "priority": "P0",
                "category": "execution",
                "case": case,
                "summary": (
                    f"{case} ended in run_error"
                    + (
                        f" ({row.get('earliest_non_pass')})"
                        if row.get("earliest_non_pass") else ""
                    )
                ),
            })
        for label in row.get("observed_fails") or []:
            check_id = label.split(":", 1)[-1].split("=", 1)[0]
            if check_id in TRACE_CHECK_IDS:
                category = "efficiency"
                priority = "P2"
            else:
                category = "functionality"
                priority = "P0"
            items.append({
                "priority": priority,
                "category": category,
                "case": case,
                "summary": f"{case} failed check {label}",
            })
        gaps = row.get("evidence_gaps") or []
        non_trace_gaps = [
            g for g in gaps
            if g.split(":", 1)[-1].split("=", 1)[0] not in TRACE_CHECK_IDS
        ]
        trace_gaps = [
            g for g in gaps
            if g.split(":", 1)[-1].split("=", 1)[0] in TRACE_CHECK_IDS
        ]
        for label in non_trace_gaps:
            items.append({
                "priority": "P1",
                "category": "execution",
                "case": case,
                "summary": (
                    f"{case} missing evidence for {label} "
                    "(not a pure tool-trace gap)"
                ),
            })
        if trace_gaps and hard == "pass" and not (row.get("observed_fails") or []):
            items.append({
                "priority": "P2",
                "category": "efficiency",
                "case": case,
                "summary": (
                    f"{case} passed hard checks but lacked --events for "
                    f"{', '.join(trace_gaps)}; supply traces or keep soft-fail"
                ),
            })
        scores = row.get("scores") or []
        weak = [
            s for s in scores
            if isinstance(s.get("score"), int) and s["score"] < 2
            and s.get("verdict") != "insufficient_evidence"
        ]
        for entry in weak:
            items.append({
                "priority": "P1",
                "category": "functionality",
                "case": case,
                "summary": (
                    f"{case} semantic criterion {entry.get('criterion_id')} "
                    f"scored {entry.get('score')}/2 ({entry.get('verdict')})"
                ),
            })

    order = {"P0": 0, "P1": 1, "P2": 2}
    items.sort(key=lambda item: (order.get(item["priority"], 9), item["case"]))
    # De-dupe identical summaries while preserving order.
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items:
        key = item["summary"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def classify_checks(metadata: dict) -> dict:
    """Split non-pass checks into observed fails vs evidence gaps."""
    observed_fails: list[str] = []
    evidence_gaps: list[str] = []
    hard = metadata.get("hard_verdict", metadata.get("verdict"))
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
    if hard in ("pending", "run_error"):
        kind = hard
    elif observed_fails and evidence_gaps:
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
    scores = report.get("scores") or {}
    ratio = scores.get("score_ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio:.0%}"
    lines = [
        f"# Spex eval summary: {Path(report['sandbox']).name}",
        "",
        f"- Sandbox: `{report['sandbox']}`",
        f"- Trials: {len(report['trials'])}",
        f"- Configured execution: {execution_label(report.get('execution', execution(None)))}",
        f"- Counts: {json.dumps(report.get('counts') or {}, sort_keys=True)}",
        f"- Classifications: {json.dumps(report.get('classifications') or {}, sort_keys=True)}",
        (
            f"- Semantic score total: {scores.get('score_sum', 0)}/"
            f"{scores.get('score_max', 0)} "
            f"({ratio_text}; "
            f"{scores.get('trials_scored', 0)}/"
            f"{scores.get('trials_total', 0)} trials judged)"
        ),
        f"- Cleanup: {report['cleanup_hint']}",
        "",
        "## Score summary",
        "",
        "| Case | Final | Hard | Score | Criteria |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["trials"]:
        case = f"{row.get('suite')}/{row.get('case_id')}"
        if row.get("criteria_scored"):
            score = f"{row.get('score_sum')}/{row.get('score_max')}"
            criteria = ", ".join(
                f"{item.get('criterion_id')}={item.get('score')}"
                for item in (row.get("scores") or [])
            ) or "—"
        else:
            score = "—"
            criteria = "ungraded"
        lines.append(
            f"| {case} | {row.get('final_verdict')} | {row.get('hard_verdict')} | "
            f"{score} | {criteria} |"
        )
    lines.extend([
        "",
        "## Trial outcomes",
        "",
        "| Case | Trial agent | Trial model | Judge agent | Judge model | "
        "Final | Class | Observed fails | Evidence gaps | Path | Configured execution |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in report["trials"]:
        case = f"{row.get('suite')}/{row.get('case_id')}"
        identities = " | ".join(
            str(row.get(field) or "unknown").replace("|", r"\|")
            for field in ("host", "model", "judge_host", "judge_model")
        )
        fails = ", ".join(row.get("observed_fails") or []) or "—"
        gaps = ", ".join(row.get("evidence_gaps") or []) or "—"
        lines.append(
            f"| {case} | {identities} | {row.get('final_verdict')} | {row.get('classification')} | "
            f"{fails} | {gaps} | `{row.get('trial')}` | "
            f"{execution_label(row.get('execution', execution(None)))} |"
        )
    if any(row.get("collection") == "manual" for row in report["trials"]):
        lines.extend(["", "For manual trials, execution describes the adapter's configured limit."])
    performance_rows = [row for row in report["trials"] if "performance" in row]
    if performance_rows:
        lines.extend(performance.report_lines(performance_rows))
    lines.extend([
        "",
        "## Spex skill improvements",
        "",
        "Auto-derived from hard checks and semantic scores in this sandbox. "
        "Categories: **functionality** (acceptance/workflow), **execution** "
        "(runtime / non-trace evidence gaps), **efficiency** (trace/host "
        "friction that slows re-runs).",
        "",
    ])
    improvements = report.get("improvements") or []
    if not improvements:
        lines.append(
            "No improvement items derived from available trial evidence."
        )
        lines.append("")
    else:
        current = None
        for item in improvements:
            priority = item.get("priority") or "P2"
            if priority != current:
                current = priority
                lines.append(f"### {priority}")
                lines.append("")
            lines.append(
                f"- **{item.get('category')}** — {item.get('summary')}"
            )
        lines.append("")
    lines.extend([
        "## How to read results",
        "",
        "- **pending / run_error**: the trial has no completed hard verdict.",
        "- **fail / observed fails**: deterministic or acceptance checks failed.",
        "- **evidence_gap / insufficient_evidence**: required artifacts (often "
        "tool traces via `--events`) were missing. Common for manual "
        "`collection` without a Codex-style transcript; not proof the workflow "
        "failed.",
        "- **Semantic score**: each graded criterion is 0–2; sandbox total is "
        "the sum of scores over twice the number of scored criteria.",
        "- Hard verdicts still take precedence over semantic judge scores.",
        "",
    ])
    return "\n".join(lines)


def summarize_sandbox(
    sandbox: Path,
    *,
    write_improvements: Path | None = None,
) -> dict:
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
        judge_host = judge.get("host") or "unknown"
        judge_model = judge.get("model") or "unknown"
        if judge.get("source") == "external" and judge_model == "external":
            judge_model = "unknown"
        final = judge.get("verdict") or metadata.get("verdict")
        hosts.add(str(metadata.get("host") or "unknown"))
        models.add(str(metadata.get("model") or "unknown"))
        split = classify_checks(metadata)
        recover_performance(sandbox, path.parent, metadata)
        score = judge_score_summary(judge) if judge else {
            "criteria_total": 0,
            "criteria_scored": 0,
            "score_sum": 0,
            "score_max": 0,
            "scores": [],
        }
        row = {
            "suite": metadata.get("suite"),
            "case_id": metadata.get("case_id"),
            "trial": str(path.parent.relative_to(sandbox)),
            "hard_verdict": metadata.get("hard_verdict", metadata.get("verdict")),
            "final_verdict": final,
            "host": metadata.get("host"),
            "model": metadata.get("model"),
            "judge_host": judge_host if judge else "ungraded",
            "judge_model": judge_model if judge else "ungraded",
            "collection": metadata.get("collection"),
            "spex_ref": metadata.get("spex_ref"),
            "execution": metadata.get("execution", execution(None)),
            "performance": performance.trial_summary(path.parent, metadata),
            "earliest_non_pass": earliest_non_pass(metadata.get("turn_results") or []),
            **split,
            **score,
        }
        rows.append(row)
        counts[str(final)] = counts.get(str(final), 0) + 1
        classifications[split["classification"]] = (
            classifications.get(split["classification"], 0) + 1
        )
    improvements = derive_skill_improvements(rows)
    report = {
        "schema_version": 1,
        "sandbox": str(sandbox),
        "hosts": sorted(hosts),
        "models": sorted(models),
        "trials": rows,
        "execution": read_execution(sandbox),
        "counts": counts,
        "classifications": classifications,
        "scores": aggregate_scores(rows),
        "improvements": improvements,
        "cleanup_hint": cleanup_hint(sandbox),
    }
    write_json(sandbox / "manifest.json", {
        "schema_version": 1,
        "sandbox": str(sandbox),
        "hosts": report["hosts"],
        "models": report["models"],
        "execution": report["execution"],
        "trials": [
            {"suite": row["suite"], "case_id": row["case_id"], "path": row["trial"],
             "execution": row["execution"]}
            for row in rows
        ],
        "scores": report["scores"],
        "cleanup_hint": report["cleanup_hint"],
    })
    write_json(sandbox / "report.json", report)
    (sandbox / "report.md").write_text(render_summary_markdown(report), encoding="utf-8")
    result = {
        **report,
        "manifest": str(sandbox / "manifest.json"),
        "report": str(sandbox / "report.md"),
        "report_json": str(sandbox / "report.json"),
    }
    if write_improvements is not None:
        backlog = write_improvements_backlog(report, write_improvements)
        result["improvements_path"] = str(backlog)
    return result


def recover_performance(sandbox: Path, output: Path, metadata: dict) -> None:
    """Summarize available diagnostics for trials saved before performance collection."""
    repo = output / WORKSPACE_NAME / "repo"
    if not repo.is_dir() or repo.resolve() != repo:
        return
    data = performance.read_performance(output)
    if "workflow" in data or "prepare_ms" in data:
        return
    turns = dict(data["turns"])
    suite, case = str(metadata.get("suite") or ""), str(metadata.get("case_id") or "")
    session = metadata.get("session", "")
    handoff = sandbox / "_handoff"
    if (collection_mode(metadata) == "manual" and session
            and IDENTIFIER.fullmatch(suite) and IDENTIFIER.fullmatch(case)
            and handoff.resolve() == handoff):
        for item in metadata.get("turn_results", []):
            index = item.get("turn")
            if type(index) is not int or index < 1:
                continue
            events = handoff / f"{suite}-{case}-turn{index}.events.jsonl"
            try:
                if str(index) in turns or events.is_symlink() or not events.is_file():
                    continue
                if events.stat().st_size > performance.MAX_LOG_BYTES:
                    continue
                raw = events.read_text(encoding="utf-8")
                host = parse_events(raw, session)
                saved = read_json(output / f"turn-{index}.json")
                if host.reply != saved["artifacts"]["reply"]["value"].strip():
                    continue
                turns[str(index)] = {
                    "host": performance.host_metrics(raw, None, "historical"),
                    "collect_ms": None,
                    "acceptance_ms": None,
                }
            except (OSError, ValueError, KeyError, TypeError, TransportError):
                continue
    performance.update(output, repo=repo, turns=turns)


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encode(value) + b"\n")
    temporary.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_execution(sandbox: Path) -> dict:
    path = sandbox / "execution.json"
    if path.is_symlink():
        raise ValueError("Unexpected linked execution configuration")
    try:
        config = read_json(path)
    except FileNotFoundError:
        return execution(None)
    jobs = config.get("jobs") if isinstance(config, dict) else None
    if type(jobs) is not int or not 1 <= jobs <= 4 or config != execution(jobs):
        raise ValueError("Invalid sandbox execution configuration")
    return config


def configure_execution(sandbox: Path, jobs: int | None) -> dict:
    config = read_execution(sandbox)
    if config["jobs"] is None:
        # Publish a complete file before any other prepare can read it.
        with tempfile.NamedTemporaryFile(dir=sandbox) as temporary:
            temporary.write(encode(execution(jobs if jobs is not None else 1)))
            temporary.flush()
            try:
                os.link(temporary.name, sandbox / "execution.json")
            except FileExistsError:
                pass
        config = read_execution(sandbox)
    if jobs is not None and jobs != config["jobs"]:
        raise ValueError("Conflicting --jobs for this sandbox. Use a new sandbox.")
    return config


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
    started = time.monotonic()
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
            "execution": getattr(args, "execution", execution(None)),
            "invocation": args.invocation, "repeat": repeat, "session": "",
            "judge_model": getattr(args, "judge_model", ""),
            "turn_results": [], "verdict": "pending",
        })
    except BaseException:
        if output.exists():
            shutil.rmtree(output, ignore_errors=True)
        raise
    performance.update(output, prepare_ms=performance.elapsed_ms(started))
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


def store_turn(output: Path, trial: Trial, metadata: dict, host: HostTurn, *,
               host_duration_ms: int | None = None, host_source: str = "runner",
               collect_started: float | None = None) -> None:
    index = len(metadata["turn_results"])
    if collect_started is None:
        collect_started = time.monotonic()
    turn = metadata["case"]["turns"][index]
    previous = read_json(output / f"turn-{index}.json")
    acceptance_ms = None
    result = None

    def record_performance():
        performance.update(
            output, turn=index + 1, repo=trial.repo,
            host=performance.host_metrics(host.raw, host_duration_ms, host_source),
            collect_ms=performance.elapsed_ms(collect_started) - (acceptance_ms or 0),
            acceptance_ms=acceptance_ms,
        )

    try:
        verify_trial_workspace(trial)
        state = capture(trial)
        if turn.get("acceptance"):
            acceptance_started = time.monotonic()
            try:
                result = acceptance(trial, metadata["suite"], turn["acceptance"])
            finally:
                acceptance_ms = performance.elapsed_ms(acceptance_started)
    except (OSError, ValueError, TransportError):
        record_performance()
        raise
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
    metadata["verdict"] = trial_verdict(
        metadata["turn_results"],
        index + 1 == len(turns),
        collection=str(metadata.get("collection") or ""),
    )
    write_json(output / "trial.json", metadata)
    record_performance()


def trial_verdict(
    turn_results: list, final: bool, *, collection: str = "",
) -> str:
    """Aggregate check verdicts into a trial hard verdict.

    For manual collection without Codex-style ``--events``, pure tool-trace
    checks (``post-action`` / ``no-post-action``) that are only
    ``insufficient_evidence`` do not force a hard ``insufficient_evidence``
    verdict — they remain visible as evidence gaps in ``summary``.
    """
    checks = [check for turn in turn_results for check in turn.get("checks") or []]
    if any(check.get("verdict") == "fail" for check in checks):
        return "fail"
    if not final:
        return "pending"
    soft_trace = collection == "manual"
    for check in checks:
        if check.get("verdict") != "insufficient_evidence":
            continue
        if soft_trace and check.get("check_id") in TRACE_CHECK_IDS:
            continue
        return "insufficient_evidence"
    return "pass"


def score_trial(
    output: Path, metadata: dict, model: str, timeout: int,
    *, runtime: CodexRuntime | None = None,
) -> dict:
    record = {
        "host": "codex", "model": model,
        "prompt_version": PROMPT_VERSION, "prompt_hash": digest(PROMPT.encode()),
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
    started = time.monotonic()
    record = score_trial(output, metadata, model, timeout, runtime=runtime)
    metadata["hard_verdict"] = record["hard_verdict"]
    metadata["verdict"] = record["verdict"]
    write_json(output / "judge.json", record)
    performance.update(output, judge={"duration_ms": performance.elapsed_ms(started),
                                      "source": "runner", "import_ms": None})


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
    prompt_text = exported["prompt"]
    prompt_path.write_text(prompt_text, encoding="utf-8")
    return {
        "trial": str(output),
        "packet": str(packet_path),
        "prompt": str(prompt_path),
        "prompt_bytes": len(prompt_text.encode("utf-8")),
        "hard_verdict": hard,
        "criteria": len(exported["packet"]["criteria"]),
        "insufficient": len(exported["insufficient"]),
        "judge_hint": (
            "Open a separate judge session. Read only judge-prompt.txt; "
            "do not re-summarize trial evidence. Return grades JSON for "
            "import-grades."
        ),
    }


def import_judge(output: Path, grades: Path, model: str, *, host: str = "unknown",
                 duration_ms: int | None = None) -> dict:
    started = time.monotonic()
    metadata = read_json(output / "trial.json")
    packet, version, criteria = trial_packet(output, metadata)
    rubric = SUITES / metadata["suite"] / "rubrics.json"
    hard = metadata.get("hard_verdict", metadata["verdict"])
    record = {
        "host": host,
        "model": model or "unknown",
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
    performance.update(output, judge={"duration_ms": duration_ms,
                                      "source": "adapter" if duration_ms is not None else None,
                                      "import_ms": performance.elapsed_ms(started)})
    return {
        "trial": str(output),
        "verdict": record["verdict"],
        "hard_verdict": hard,
        "results": len(record["results"]),
        "error": record.get("error"),
        "judge": str(output / "judge.json"),
    }


def replay(run_id: str, model: str, timeout: int, *, jobs: int = 1,
           runtime: CodexRuntime | None = None) -> dict:
    if not saved_run_id(run_id):
        raise ValueError("Expected a saved run ID")
    output = RUNS.resolve() / run_id
    if output.is_symlink() or not output.is_dir():
        raise ValueError("Saved run does not exist")
    files = sorted(
        saved_trial_paths(output),
        key=lambda path: trial_order(path.relative_to(output)),
    )
    if not files:
        raise ValueError("No saved trials in run")
    def regrade(path):
        if path.resolve() != path:
            raise ValueError("Unexpected linked trial")
        metadata = read_json(path)
        hard = metadata.get("hard_verdict", metadata["verdict"])
        record = (
            {"verdict": hard, "skipped": True} if hard in ("pending", "run_error")
            else score_trial(path.parent, metadata, model, timeout, runtime=runtime)
        )
        return {"trial": str(path.parent.relative_to(output)), **record}

    results = ordered_map(regrade, files, jobs)
    directory = output / "rejudges" / uuid.uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    report = {
        "run": str(output), "model": model, "judgments": results, "execution": execution(jobs),
    }
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
    grades = ordered_map(
        lambda sample: grade(sample["packet"], args.judge_model, args.timeout, adapter=adapter),
        calibration["samples"], args.jobs,
    )
    report = evaluate(calibration, grades, args.judge_model, args.split)
    report["execution"] = execution(args.jobs)
    directory = RUNS / "calibrations"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.json"
    write_json(path, report)
    return {**report, "report": str(path)}


def compare_runs(args: argparse.Namespace) -> dict:
    ids = (args.baseline, args.candidate, args.baseline_rejudge, args.candidate_rejudge)
    if (not all(saved_run_id(value) for value in ids[:2])
            or any(value and not re.fullmatch(r"[a-f0-9]{32}", value) for value in ids[2:])):
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
        started = time.monotonic()
        try:
            host = codex_turn(
                trial, message, args.model, args.timeout, metadata["session"],
                trace_path=output / f"host-{index + 1}.jsonl", runtime=runtime,
            )
        except TransportError as error:
            performance.update(
                output, turn=index + 1, repo=trial.repo,
                host=performance.host_metrics(error.partial_events, performance.elapsed_ms(started),
                                              "runner", str(error)),
                collect_ms=None, acceptance_ms=None,
            )
            raise
        store_turn(output, trial, metadata, host, host_duration_ms=performance.elapsed_ms(started))
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
            "host": args.host, "spex_ref": args.spex_ref, "collection": "automatic",
            "execution": args.execution,
        }
        result.update(verdict="run_error", error=(
            str(error) if isinstance(error, TransportError) else "fixture_or_capture_error"
        ))
    judge_trial(
        output, result, getattr(args, "judge_model", ""), args.timeout,
        runtime=getattr(args, "codex_runtime", None),
    )
    result["duration_ms"] = round((time.monotonic() - started) * 1000)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "trial.json", result)
    performance.update(output, automatic_total_ms=result["duration_ms"])
    return result


def manual_result(output: Path, args: argparse.Namespace) -> dict:
    started = time.monotonic()
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
    store_turn(
        output, trial, metadata, host, host_duration_ms=getattr(args, "host_duration_ms", None),
        host_source="adapter", collect_started=started,
    )
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


def duration_argument(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("Expected a non-negative duration in milliseconds")
    return result


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
        "execution": metadata.get("execution", execution(None)),
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
        if name in ("run", "prepare"):
            command.add_argument("--jobs", type=worker_count, default=1 if name == "run" else None)
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
    collect.add_argument("--host-duration-ms", type=duration_argument)
    collect.add_argument("--judge-model", default=os.environ.get("SPEX_EVAL_JUDGE_MODEL", ""))
    export = sub.add_parser("export-packet")
    export.add_argument("trial", type=Path)
    imported = sub.add_parser("import-grades")
    imported.add_argument("trial", type=Path)
    imported.add_argument("--grades", type=Path, required=True)
    imported.add_argument("--host", type=host_name, default="unknown", help="Judge agent host")
    imported.add_argument("--model", type=unknownable, default="unknown", help="Judge model ID")
    imported.add_argument("--judge-duration-ms", type=duration_argument)
    summary = sub.add_parser("summary")
    summary.add_argument(
        "sandbox", type=Path,
        help="Sandbox directory under eval/spex/runs/YYYY-MM-DD-HH-MM-SS",
    )
    summary.add_argument(
        "--write-improvements",
        nargs="?",
        const=HERE / "IMPROVEMENTS.md",
        type=Path,
        default=None,
        help=(
            "Write prioritized Spex-skill backlog markdown "
            "(default path: eval/spex/IMPROVEMENTS.md)"
        ),
    )
    rejudge = sub.add_parser("judge")
    rejudge.add_argument("run_id")
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--split", choices=("frozen", "development"), default="frozen")
    for command in (rejudge, calibration):
        command.add_argument("--jobs", type=worker_count, default=1)
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
            return replay(
                args.run_id, args.judge_model, args.timeout, jobs=args.jobs, runtime=runtime,
            )
        return calibrate(args, runtime=runtime)
    if args.command == "export-packet":
        return export_judge(resolve_trial(args.trial))
    if args.command == "import-grades":
        return import_judge(resolve_trial(args.trial), args.grades, args.model, host=args.host,
                            duration_ms=args.judge_duration_ms)
    if args.command == "summary":
        return summarize_sandbox(
            args.sandbox,
            write_improvements=args.write_improvements,
        )
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
            args.execution = configure_execution(sandbox, args.jobs)
            trial = setup(cases[0], output, args, sandbox=sandbox)
        except BaseException:
            if allocated:
                cleanup_failed_case(sandbox, output, remove_sandbox=True)
            else:
                prune_empty_parents(output.parent, sandbox)
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
    args.execution = configure_execution(sandbox, args.jobs)

    def run_trial(item):
        case, repeat = item
        return automatic(
            case, case_dir(sandbox, case.suite, case.id, repeat), args, repeat,
            sandbox=sandbox,
        )

    items = ((case, repeat) for case in cases for repeat in range(1, args.repeat + 1))
    rows = ordered_map(run_trial, items, args.jobs)
    return {
        "run": str(sandbox), "sandbox": str(sandbox), "trials": rows,
        "execution": args.execution,
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
