"""Offline checks for automated and manually collected Spex eval turns."""

import io
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval" / "spex"))
try:
    import collect_handoff
    import manual
    import run
    import transport
    import workspace
finally:
    sys.path.pop(0)


@pytest.fixture
def runner(tmp_path, monkeypatch):
    suite = tmp_path / "suites" / "example"
    fixture = suite / "fixtures" / "example"
    fixture.mkdir(parents=True)
    (fixture / "app.py").write_text("pass\n", encoding="utf-8")
    (suite / "cases.json").write_text(json.dumps([{
        "id": "clarify", "fixture": "example", "tags": ["smoke"], "turns": [
            {"input": "/spex create Add a setting", "checks": ["no-code-change"]},
            {"input": "Use a boolean setting", "checks": ["no-code-change"]},
        ],
    }]), encoding="utf-8")
    monkeypatch.setattr(run, "SUITES", suite.parent)
    monkeypatch.setattr(run, "RUNS", tmp_path / "runs")
    return run.parser()


def test_trace_identifies_workflow_commands_and_transport_errors():
    trace = "\n".join(json.dumps(event) for event in (
        {"type": "thread.started", "thread_id": "example-1"},
        {"type": "item.completed", "item": {"type": "command_execution", "exit_code": 1,
         "command": "/bin/zsh -lc '/fixture/scripts/spex review-helper --name case status'"}},
        {"type": "item.completed", "item": {"type": "command_execution", "exit_code": 0,
         "command": "/bin/zsh -lc '/fixture/scripts/spex apply-helper post-action --name case'"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Done"}},
        {"type": "turn.completed"},
    ))
    result = transport.parse_events(trace, "example-1")
    assert result.reply == "Done"
    assert result.events == [
        {"action": "apply.review-command", "exit_code": 1, "stage": "status", "spec": "case"},
        {"action": "apply.post-action", "exit_code": 0, "spec": "case"},
    ]
    with pytest.raises(transport.TransportError, match="session_mismatch"):
        transport.parse_events(trace, "wrong-session")
    with pytest.raises(transport.TransportError, match="rate_limit"):
        transport.parse_events('{"type":"turn.failed","error":{"message":"429 rate limit"}}')


@pytest.mark.parametrize(("output", "skipped"), [
    ('{"prompt":"","skipped":true}', True),
    ('{"prompt":"Review this commit"}', None),
    ("", None),
])
def test_review_prompt_command_records_only_observed_skips(output, skipped):
    event = transport.command_event({
        "command": "./scripts/spex prompt apply-review --json spec --mode full --commit abc1234",
        "exit_code": 0,
        "aggregated_output": output,
    })
    assert event["action"] == "apply.review-command"
    assert event["mode"] == "full"
    assert event.get("skipped") is skipped


@pytest.mark.parametrize("options,limit", [([], 1), (["--jobs", "2"], 2)])
def test_run_schedules_whole_trials_and_reports_in_order(runner, monkeypatch, options, limit):
    active = set()
    events = []
    peak = 0
    lock = threading.Lock()
    first_wave = threading.Barrier(limit, timeout=5)
    second_finished = threading.Event()

    def setup(case, output, args, repeat, **kwargs):
        nonlocal peak
        output.mkdir(parents=True)
        run.write_json(output / "trial.json", {
            "case": case.definition, "suite": case.suite, "case_id": case.id,
            "session": "", "turn_results": [], "verdict": "pending", "repeat": repeat,
            "execution": args.execution,
        })
        with lock:
            active.add(repeat)
            events.append(("start", repeat))
            peak = max(peak, len(active))
        return SimpleNamespace(skill=output, repeat=repeat)

    def host(trial, message, *args, **kwargs):
        return trial.repeat, message

    def collect(output, trial, metadata, host, **kwargs):
        repeat, message = host
        with lock:
            events.append(("first" if message.startswith("$spex") else "second", repeat))
        metadata["turn_results"].append({})
        if len(metadata["turn_results"]) == 2:
            metadata["verdict"] = "pass"

    def judge(output, metadata, *args, **kwargs):
        repeat = metadata["repeat"]
        if repeat <= limit:
            first_wave.wait()
        if repeat == 1 and limit == 2:
            assert second_finished.wait(timeout=5)
        with lock:
            events.append(("judged", repeat))
            active.remove(repeat)
        if repeat == 2:
            second_finished.set()

    monkeypatch.setattr(run, "prepare_codex_runtime",
                        lambda *a, **kw: SimpleNamespace(version="fake", home="fake"))
    monkeypatch.setattr(run, "verify_trial_workspace", lambda _: None)
    monkeypatch.setattr(run, "setup", setup)
    monkeypatch.setattr(run, "codex_turn", host)
    monkeypatch.setattr(run, "store_turn", collect)
    monkeypatch.setattr(run, "judge_trial", judge)
    result = run.execute(runner.parse_args([
        "run", "--model", "fake", "--judge-model", "fake", "--repeat", "3", *options,
    ]))
    assert peak == limit
    assert [row["repeat"] for row in result["trials"]] == [1, 2, 3]
    assert events.index(("judged", 1 if limit == 1 else 2)) < events.index(
        ("start", 2) if limit == 1 else ("judged", 1)
    )
    for repeat in range(1, 4):
        assert [stage for stage, number in events if number == repeat] == [
            "start", "first", "second", "judged",
        ]
    report = run.summarize_sandbox(Path(result["sandbox"]))
    assert report["execution"] == result["execution"] == run.execution(limit)
    assert all(row["execution"] == run.execution(limit) for row in report["trials"])
    assert run.read_json(Path(report["manifest"]))["execution"] == run.execution(limit)


@pytest.mark.slow
def test_prepare_inherits_worker_limit_and_rejects_conflicts(runner):
    path = run.SUITES / "example" / "cases.json"
    case, = run.read_json(path)
    run.write_json(path, [case, {**case, "id": "second"}])
    command = ["prepare", "--host", "cursor"]
    first = run.execute(runner.parse_args([*command, "--case", "clarify", "--jobs", "2"]))
    existing = [*command, "--sandbox", first["sandbox"]]
    inherited = run.execute(runner.parse_args([*existing, "--case", "second"]))
    assert first["execution"] == inherited["execution"] == run.execution(2)
    with pytest.raises(ValueError, match="Use a new sandbox"):
        run.execute(runner.parse_args([*existing, "--case", "clarify", "--jobs", "1"]))
    assert Path(first["trial"], "trial.json").is_file()


def test_worker_limit_validation(runner):
    for command in (["prepare", "--host", "cursor"], ["run", "--model", "fake"],
                    ["judge", "fake"], ["calibrate"]):
        for count in ("0", "5"):
            with pytest.raises(SystemExit):
                runner.parse_args([*command, "--jobs", count])


def test_failed_setup_keeps_execution_metadata(runner, monkeypatch):
    def fail_setup(*args, **kwargs):
        raise ValueError("bad fixture")

    monkeypatch.setattr(run, "setup", fail_setup)
    monkeypatch.setattr(run, "prepare_codex_runtime",
                        lambda *a, **kw: SimpleNamespace(version="fake", home="fake"))
    result = run.execute(runner.parse_args(["run", "--model", "fake", "--jobs", "2"]))
    report = run.summarize_sandbox(Path(result["sandbox"]))
    assert report["counts"] == {"run_error": 1}
    assert report["trials"][0]["execution"] == run.execution(2)


def test_automatic_batch_resolves_ref_once(runner, monkeypatch):
    resolved = iter(["a" * 40, "b" * 40])
    monkeypatch.setattr(run, "resolve_spex_ref", lambda *_: next(resolved))
    monkeypatch.setattr(run, "prepare_codex_runtime",
                        lambda *a, **kw: SimpleNamespace(version="fake", home="fake"))
    monkeypatch.setattr(run, "automatic", lambda *args, **kwargs: args[2].spex_ref)

    result = run.execute(runner.parse_args(["run", "--model", "fake", "--repeat", "2"]))

    assert result["trials"] == ["a" * 40, "a" * 40]
    assert next(resolved) == "b" * 40


def test_startup_probes_classify_state_app_server_and_auth(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        with pytest.raises(transport.TransportError, match="state_dir_unwritable"):
            transport.ensure_state_home(blocked / "nested")
    finally:
        blocked.chmod(0o700)

    home = transport.ensure_state_home(tmp_path / "codex-home")
    calls = []

    def launch(command, **kwargs):
        calls.append(command)
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "fake 1.0\n", "")
        return subprocess.CompletedProcess(
            command, 1, "", "Failed to initialize app-server: Operation not permitted",
        )

    monkeypatch.setattr(transport.subprocess, "run", launch)
    runtime = transport.CodexRuntime(str(tmp_path / "codex"), home, "fake 1.0")
    with pytest.raises(transport.TransportError, match="app_server_init"):
        transport.probe_app_server(runtime)
    assert any("--ephemeral" in command for command in calls)

    def auth_launch(command, **kwargs):
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "fake 1.0\n", "")
        return subprocess.CompletedProcess(command, 1, "", "401 unauthorized not logged in")

    monkeypatch.setattr(transport.subprocess, "run", auth_launch)
    with pytest.raises(transport.TransportError, match="authentication"):
        transport.probe_app_server(runtime)
    assert transport.failure_reason("cannot open goals_1.sqlite: Operation not permitted") == (
        "state_dir_unwritable"
    )


@pytest.mark.slow
def test_run_reports_startup_failure_once(runner, tmp_path, monkeypatch):
    fake = tmp_path / "fake-codex"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        "    print('fake 1.0'); raise SystemExit(0)\n"
        "print('Failed to initialize app-server: Operation not permitted', file=sys.stderr)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("SPEX_EVAL_CODEX", str(fake))
    with pytest.raises(transport.TransportError, match="app_server_init"):
        run.execute(runner.parse_args(["run", "--model", "example", "--tag", "smoke"]))
    assert not any(path.name != ".codex-home" for path in run.RUNS.glob("*"))


@pytest.mark.parametrize("mode,reason", [
    ("nonzero", "rate_limit"), ("malformed", "invalid_jsonl"), ("timeout", "timeout"),
])
def test_failed_host_turn_preserves_sanitized_evidence(tmp_path, monkeypatch, mode, reason):
    raw = (
        '{"type":"thread.started","thread_id":"PRIVATE-VALUE"}\n'
        '{"type":"item.completed","item":{"type":"command_execution",'
        '"command":"PRIVATE-VALUE","exit_code":2}}\n'
        'PRIVATE-VALUE\n'
    )

    def launch(*args, **kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired("codex", 1, output=raw.encode())
        return subprocess.CompletedProcess(args, mode == "nonzero", raw, "429 PRIVATE-VALUE")

    monkeypatch.setattr(transport.subprocess, "run", launch)
    trace = tmp_path / "host-1.jsonl"
    with pytest.raises(transport.TransportError, match=reason):
        transport.codex_turn(workspace.Trial(tmp_path, "ref"), "run", "model", 1, trace_path=trace)
    saved = trace.read_text(encoding="utf-8")
    assert "PRIVATE-VALUE" not in saved
    records = [json.loads(line) for line in saved.splitlines()]
    assert records[:3] == [
        {"type": "thread.started"},
        {"type": "item.completed", "action": "command", "exit_code": 2},
        {"type": "invalid_jsonl"},
    ]
    if mode != "malformed":
        assert records[-1] == {"type": "transport_error", "reason": reason}


@pytest.mark.slow
@pytest.mark.parametrize("reply,verdict,turns", [
    ("What type?", "pass", 2), ("Implementation finished.", "insufficient_evidence", 2),
    ("Acceptance failure", "run_error", 1),
])
def test_automatic_turns_use_fake_cli(runner, tmp_path, monkeypatch, reply, verdict, turns):
    fake = tmp_path / "fake-codex"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "if '--version' in sys.argv:\n"
        "    print('fake 1.0'); raise SystemExit(0)\n"
        "assert '-a' in sys.argv and 'never' in sys.argv\n"
        "prompt = sys.stdin.read()\n"
        "if '--ephemeral' in sys.argv:\n"
        "    reply = 'OK'\n"
        "else:\n"
        "    assert 'allow_login_shell=false' in sys.argv\n"
        "    assert os.environ['HOME'].endswith('/home')\n"
        "    assert os.environ['TMPPREFIX'] == os.environ['TMPDIR'] + '/zsh'\n"
        "    assert os.environ['SPEX_CONFIG_FILE'].endswith('/repo/.spex.toml')\n"
        "    assert os.environ['CODEX_HOME']\n"
        "    if 'resume' in sys.argv:\n"
        "        assert sys.argv[sys.argv.index('resume') + 1] == 'example-1'\n"
        "        assert prompt == 'Use a boolean setting'\n"
        "        reply = 'Done'\n"
        "    else:\n"
        "        assert prompt.startswith('$spex\\n/spex create')\n"
        f"        reply = {reply!r}\n"
        "for event in [\n"
        "    {'type': 'thread.started', 'thread_id': 'example-1'},\n"
        "    {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': reply}},\n"
        "    {'type': 'turn.completed'},\n"
        "]: print(json.dumps(event))\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("SPEX_EVAL_CODEX", str(fake))
    if verdict == "run_error":
        manifest = run.SUITES / "example" / "cases.json"
        cases = json.loads(manifest.read_text(encoding="utf-8"))
        cases[0]["turns"][0]["acceptance"] = "expected"
        manifest.write_text(json.dumps(cases), encoding="utf-8")

        def fail_acceptance(*args):
            raise transport.TransportError("acceptance_error")

        monkeypatch.setattr(run, "acceptance", fail_acceptance)
    result = run.execute(runner.parse_args(["run", "--model", "example", "--tag", "smoke"]))
    row = result["trials"][0]
    output = Path(result["run"]) / "example" / "clarify" / "1"
    assert row["verdict"] == verdict
    assert (output / f"host-{turns}.jsonl").is_file()
    if verdict == "run_error":
        assert row["error"] == "acceptance_error"
        assert row["turn_results"] == []
    else:
        assert len(row["turn_results"]) == turns
        assert (output / f"turn-{turns}.json").is_file()
    assert Path(row["trial_directory"]).is_dir()
    assert Path(result["sandbox"]).is_dir()
    assert "Please delete the sandbox manually" in result["cleanup_hint"]


def test_codex_home_override_takes_precedence(tmp_path, monkeypatch):
    override = tmp_path / "authenticated-home"
    preferred = tmp_path / "batch-home"
    monkeypatch.setenv("SPEX_EVAL_CODEX_HOME", str(override))

    assert transport.resolve_codex_home(preferred) == override.resolve()
    assert not preferred.exists()


def test_classify_checks_splits_fails_and_evidence_gaps():
    mixed = run.classify_checks({
        "collection": "manual",
        "turn_results": [{
            "turn": 1,
            "checks": [
                {"check_id": "one-step", "verdict": "fail"},
                {"check_id": "post-action", "verdict": "insufficient_evidence"},
            ],
        }],
    })
    assert mixed["classification"] == "mixed"
    assert mixed["observed_fails"] == ["turn1:one-step=fail"]
    assert mixed["evidence_gaps"] == ["turn1:post-action=insufficient_evidence"]
    gap_only = run.classify_checks({
        "collection": "manual",
        "turn_results": [{
            "turn": 2,
            "checks": [{"check_id": "post-action", "verdict": "insufficient_evidence"}],
        }],
    })
    assert gap_only["classification"] == "evidence_gap"


def test_required_trace_gaps_force_hard_insufficient_verdict():
    turns = [{
        "turn": 1,
        "checks": [
            {"check_id": "one-step", "verdict": "pass"},
            {"check_id": "post-action", "verdict": "insufficient_evidence"},
            {"check_id": "edit-guide", "verdict": "pass"},
        ],
    }]
    assert run.trial_verdict(turns, True) == "insufficient_evidence"


def test_cleanup_failed_case_removes_fresh_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path / "runs")
    sandbox = run.resolve_sandbox(None)
    output = workspace.case_dir(sandbox, "example", "clarify")
    output.mkdir(parents=True)
    (output / "workspace").mkdir()
    run.cleanup_failed_case(sandbox, output, remove_sandbox=True)
    assert not output.exists()
    assert not sandbox.exists()


def test_cleanup_failed_case_keeps_shared_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path / "runs")
    sandbox = run.resolve_sandbox(None)
    keep = workspace.case_dir(sandbox, "example", "clarify")
    keep.mkdir(parents=True)
    run.write_json(keep / "trial.json", {"suite": "example", "case_id": "clarify"})
    failed = workspace.case_dir(sandbox, "example", "follow-up")
    failed.mkdir(parents=True)
    run.cleanup_failed_case(sandbox, failed, remove_sandbox=False)
    assert not failed.exists()
    assert sandbox.exists()
    assert (keep / "trial.json").is_file()


def test_main_prints_json_error_on_failure(runner, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv",
        ["run.py", "prepare", "--suite", "missing", "--host", "cursor"],
    )
    assert run.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert "error" in payload
    assert "cleanup_hint" in payload


def test_summary_writes_manifest_and_reports(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path / "runs")
    sandbox = run.resolve_sandbox(None)
    out = workspace.case_dir(sandbox, "example", "clarify")
    out.mkdir(parents=True)
    run.write_json(out / "trial.json", {
        "suite": "example", "case_id": "clarify", "verdict": "fail",
        "hard_verdict": "pass",
        "host": "cursor", "model": "unknown", "collection": "manual",
        "turn_results": [{
            "turn": 1,
            "checks": [
                {"check_id": "no-code-change", "verdict": "pass"},
                {"check_id": "post-action", "verdict": "insufficient_evidence"},
            ],
        }],
    })
    run.write_json(out / "judge.json", {
        "source": "external",
        "model": "external",
        "verdict": "fail",
        "hard_verdict": "pass",
        "results": [
            {
                "criterion_id": "scope-correct",
                "score": 1,
                "verdict": "fail",
                "reason": "The reply omitted the scope of the change.",
                "evidence_refs": ["turn-1:state"],
            }
        ],
    })
    backlog = tmp_path / "IMPROVEMENTS.md"
    result = run.execute(runner.parse_args([
        "summary", str(sandbox), "--write-improvements", str(backlog),
    ]))
    assert result["counts"] == {"fail": 1}
    assert result["execution"] == run.execution(None)
    assert result["classifications"] == {"evidence_gap": 1}
    assert result["trials"][0]["classification"] == "evidence_gap"
    assert result["trials"][0]["hard_verdict"] == "pass"
    assert result["trials"][0]["judge_host"] == "unknown"
    assert result["trials"][0]["judge_model"] == "unknown"
    assert result["scores"]["score_sum"] == 1
    assert result["scores"]["score_max"] == 2
    assert result["scores"]["score_ratio"] == 0.5
    assert [item["category"] for item in result["improvements"]] == [
        "functionality", "efficiency",
    ]
    assert Path(result["report"]).is_file()
    assert Path(result["report_json"]).is_file()
    assert Path(result["manifest"]).is_file()
    assert result["improvements_path"] == str(backlog)
    assert backlog.is_file()
    backlog_text = backlog.read_text(encoding="utf-8")
    assert "# Spex-eval improvement backlog" in backlog_text
    assert "### P2" in backlog_text
    report = Path(result["report"]).read_text(encoding="utf-8")
    assert "example/clarify" in report
    assert "evidence_gap" in report
    assert "## Score summary" in report
    assert "Semantic score total: 1/2" in report
    assert "## Spex skill improvements" in report
    assert "### P2" in report
    assert "Please delete the sandbox manually" in result["cleanup_hint"]


def test_summary_reports_trial_and_judge_identities(runner, monkeypatch):
    sandbox = run.resolve_sandbox(None)
    automatic = workspace.case_dir(sandbox, "example", "automatic")
    manual = workspace.case_dir(sandbox, "example", "manual")
    trials = [
        (automatic, "codex", "trial-one"),
        (manual, "cursor", "trial-two"),
    ]
    for directory, host, model in trials:
        directory.mkdir(parents=True)
        run.write_json(directory / "trial.json", {
            "suite": "example", "case_id": directory.name, "verdict": "pass",
            "host": host, "model": model,
        })

    rubric = run.SUITES / "example" / "rubrics.json"
    run.write_json(rubric, {})
    monkeypatch.setattr(run, "rubric_for", lambda *_: (1, []))
    monkeypatch.setattr(run, "packet_for", lambda *_: {"evidence": {}})
    monkeypatch.setattr(run, "grade", lambda *_, **__: {"results": []})
    metadata = run.read_json(automatic / "trial.json")
    run.judge_trial(automatic, metadata, "judge-one", 30)
    run.write_json(manual / "judge.json", {
        "host": "qoder", "model": "judge-two", "source": "external",
    })

    result = run.summarize_sandbox(sandbox)
    rows = run.read_json(Path(result["report_json"]))["trials"]
    assert [
        (row["host"], row["model"], row["judge_host"], row["judge_model"]) for row in rows
    ] == [
        ("codex", "trial-one", "codex", "judge-one"),
        ("cursor", "trial-two", "qoder", "judge-two"),
    ]
    report = Path(result["report"]).read_text(encoding="utf-8")
    assert "| example/automatic | codex | trial-one | codex | judge-one |" in report
    assert "| example/manual | cursor | trial-two | qoder | judge-two |" in report


def test_summary_does_not_classify_unfinished_trials_as_passes(runner):
    sandbox = run.resolve_sandbox(None)
    for verdict in ("pending", "run_error"):
        directory = workspace.case_dir(sandbox, "example", verdict.replace("_", "-"))
        directory.mkdir(parents=True)
        run.write_json(directory / "trial.json", {
            "suite": "example", "case_id": directory.name, "verdict": verdict,
        })

    result = run.summarize_sandbox(sandbox)

    assert result["classifications"] == {"pending": 1, "run_error": 1}


def test_summary_improvements_prioritize_acceptance_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path / "runs")
    sandbox = run.resolve_sandbox(None)
    out = workspace.case_dir(sandbox, "python-cli", "create")
    out.mkdir(parents=True)
    run.write_json(out / "trial.json", {
        "suite": "python-cli", "case_id": "create", "verdict": "fail",
        "host": "cursor", "model": "unknown", "collection": "manual",
        "turn_results": [{
            "turn": 1,
            "checks": [
                {"check_id": "new-plan", "verdict": "fail", "phase": "acceptance"},
                {"check_id": "post-action", "verdict": "insufficient_evidence"},
            ],
        }],
    })
    result = run.summarize_sandbox(sandbox)
    assert result["improvements"][0]["priority"] == "P0"
    assert result["improvements"][0]["category"] == "functionality"
    assert "new-plan" in result["improvements"][0]["summary"]
    assert result["trials"][0]["judge_host"] == "ungraded"
    assert result["trials"][0]["judge_model"] == "ungraded"
    report = Path(result["report"]).read_text(encoding="utf-8")
    assert "### P0" in report
    assert "functionality" in report


@pytest.mark.slow
def test_prepare_uses_timestamp_sandbox_and_keeps_workspace(runner):
    info = run.execute(runner.parse_args([
        "prepare", "--case", "clarify", "--host", "cursor", "--invocation", "native",
    ]))
    sandbox = Path(info["sandbox"])
    trial = Path(info["trial"])
    assert workspace.SANDBOX_NAME.fullmatch(sandbox.name)
    assert trial == sandbox / "example" / "clarify"
    assert Path(info["workspace"]).is_relative_to(sandbox / "example" / "clarify" / "workspace")
    assert (trial / "workspace" / "repo").is_dir()
    assert (trial / "trial.json").is_file()
    assert "Please delete the sandbox manually" in info["cleanup_hint"]


@pytest.mark.slow
def test_prepare_reuses_sandbox_across_cases(runner):
    suite = run.SUITES / "example"
    cases = run.read_json(suite / "cases.json")
    cases.append({
        "id": "follow-up", "fixture": "example", "tags": ["smoke"], "turns": [
            {"input": "/spex create Add another setting", "checks": ["no-code-change"]},
        ],
    })
    (suite / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    first = run.execute(runner.parse_args([
        "prepare", "--case", "clarify", "--host", "cursor", "--invocation", "native",
    ]))
    second = run.execute(runner.parse_args([
        "prepare", "--case", "follow-up", "--host", "cursor", "--invocation", "native",
        "--sandbox", first["sandbox"],
    ]))
    assert first["sandbox"] == second["sandbox"]
    assert Path(second["trial"]) == Path(first["sandbox"]) / "example" / "follow-up"


def manual_action(sandbox, *arguments):
    return manual.dispatch(manual.parser().parse_args([
        "--sandbox", str(sandbox), *arguments,
    ]), sandbox)


@pytest.mark.slow
def test_guarded_manual_dispatch_and_terminal_verdict(runner, monkeypatch):
    info = run.execute(runner.parse_args([
        "prepare", "--case", "clarify", "--host", "cursor",
    ]))
    sandbox = Path(info["sandbox"])
    key = "example/clarify"
    with pytest.raises(ValueError, match="exact selected"):
        manual_action(sandbox, "init", key, "example/not-prepared")
    assert manual_action(sandbox, "init", key)[0]["terminal"] is False
    assert manual_action(sandbox, "status", "--require-terminal")[1] == 1
    with ThreadPoolExecutor(2) as pool:
        claims = [pool.submit(manual_action, sandbox, "claim", key) for _ in range(2)]
    assert sum(future.exception() is None for future in claims) == 1
    with pytest.raises(ValueError, match="still pending"):
        manual_action(sandbox, "complete", key)
    with pytest.raises(ValueError, match="Start this turn"):
        manual_action(sandbox, "stop", key, "1")
    with pytest.raises(ValueError, match="pending turn is 1"):
        manual_action(sandbox, "start", key, "2", "--session", "trial-1")

    with monkeypatch.context() as worker:
        worker.setenv("PATH", "/a/different/worker/path")
        start, _ = manual_action(sandbox, "start", key, "1", "--session", "trial-1")
    assert start["next_input"] == info["next_input"]
    assert start["environment"] == info["environment"]
    commands = []
    with monkeypatch.context() as worker:
        worker.setenv("PATH", "/a/different/worker/path")
        worker.setattr(manual.os, "chdir", commands.append)
        worker.setattr(manual.os, "execve", lambda *arguments: commands.append(arguments))
        args = manual.parser().parse_args([
            "--sandbox", str(sandbox), "exec", key, "--", "python3", "-V",
        ])
        assert manual.run_command(args, sandbox) == 0
    assert commands[0] == Path(info["workspace"])
    executable, argv, environment = commands[1]
    assert Path(executable).parent == Path(info["environment"]["PATH"].split(":")[0])
    assert argv == ["python3", "-V"]
    assert environment["SPEX_CONFIG_FILE"] == info["environment"]["SPEX_CONFIG_FILE"]

    Path(start["reply"]).write_text("What type?", encoding="utf-8")
    with pytest.raises(ValueError, match="already started"):
        manual_action(sandbox, "start", key, "1", "--session", "trial-1")
    with pytest.raises(ValueError, match="Stop the current turn timer"):
        manual_action(sandbox, "collect", key, "1")
    manual_action(sandbox, "stop", key, "1")
    manual_action(sandbox, "stop", key, "1")  # Retried stop leaves the timing intact.
    first, _ = manual_action(sandbox, "collect", key, "1")
    assert first["next_input"] == "Use a boolean setting"
    assert manual_action(sandbox, "collect", key, "1")[0] == first
    with pytest.raises(ValueError, match="same valid session ID"):
        manual_action(sandbox, "start", key, "2", "--session", "wrong-session")
    second, _ = manual_action(sandbox, "start", key, "2", "--session", "trial-1")
    Path(second["reply"]).write_text("Done", encoding="utf-8")
    manual_action(sandbox, "stop", key, "2")
    final, _ = manual_action(sandbox, "collect", key, "2")
    assert final["verdict"] == "pass"
    with pytest.raises(ValueError, match="Import semantic grades"):
        manual_action(sandbox, "complete", key)
    trial = Path(info["trial"]) / "trial.json"
    metadata = run.read_json(trial)
    run.write_json(trial, {**metadata, "hard_verdict": "pass", "verdict": "fail"})
    assert manual_action(sandbox, "complete", key)[0]["verdict"] == "fail"
    assert manual_action(sandbox, "status", "--require-terminal")[1] == 0


@pytest.mark.slow
def test_guarded_manual_host_failure_releases_slot_and_preserves_evidence(runner):
    manifest = run.SUITES / "example" / "cases.json"
    original = run.read_json(manifest)[0]
    manifest.write_text(json.dumps([
        {**original, "id": name} for name in ("alpha", "bravo")
    ]), encoding="utf-8")
    first, second = "example/alpha", "example/bravo"
    info = run.execute(runner.parse_args([
        "prepare", "--case", "alpha", "--host", "cursor", "--jobs", "1",
    ]))
    sandbox = Path(info["sandbox"])
    run.execute(runner.parse_args([
        "prepare", "--case", "bravo", "--host", "cursor", "--sandbox", str(sandbox),
    ]))
    manual_action(sandbox, "init", first, second)
    with pytest.raises(ValueError, match="must be claimed"):
        manual_action(sandbox, "fail", first, "--reason", "launch_failed")
    manual_action(sandbox, "claim", first)
    start, _ = manual_action(sandbox, "start", first, "1", "--session", "trial-alpha")
    Path(start["reply"]).write_text("What type?", encoding="utf-8")
    manual_action(sandbox, "stop", first, "1")
    manual_action(sandbox, "collect", first, "1")
    manifest_path = Path(info["trial"]) / "trial.json"
    before = run.read_json(manifest_path)
    manual_action(sandbox, "start", first, "2", "--session", "trial-alpha")
    with pytest.raises(ValueError, match="slots are occupied"):
        manual_action(sandbox, "claim", second)

    failed, _ = manual_action(sandbox, "fail", first, "--reason", "timeout")
    assert failed == {"case": first, "status": "completed", "verdict": "run_error"}
    after = run.read_json(manifest_path)
    assert after == {**before, "verdict": "run_error", "error": "manual_host_timeout"}
    assert Path(start["reply"]).read_text(encoding="utf-8") == "What type?"
    assert manual_action(sandbox, "status", "--require-terminal")[1] == 1
    manual_action(sandbox, "claim", second)
    manual_action(sandbox, "fail", second, "--reason", "launch_failed")
    status, code = manual_action(sandbox, "status", "--require-terminal")
    assert code == 0 and status["terminal"]
    assert {row["verdict"] for row in status["cases"].values()} == {"run_error"}


@pytest.mark.slow
def test_parallel_prepares_publish_every_case_and_can_republish(runner):
    manifest = run.SUITES / "example" / "cases.json"
    original = run.read_json(manifest)[0]
    manifest.write_text(json.dumps([
        {**original, "id": name} for name in ("alpha", "bravo", "charlie")
    ]), encoding="utf-8")

    def prepare(case, sandbox=None):
        extra = [] if sandbox is None else ["--sandbox", str(sandbox)]
        return run.execute(runner.parse_args([
            "prepare", "--case", case, "--host", "cursor", *extra,
        ]))

    first = prepare("alpha")
    sandbox = Path(first["sandbox"])
    with ThreadPoolExecutor(2) as pool:
        both = [pool.submit(prepare, case, sandbox) for case in ("bravo", "charlie")]
        for future in both:
            assert future.result()["sandbox"] == str(sandbox)
    index = sandbox / "batch-index.json"
    entries = run.read_json(index)
    assert set(entries) == {"example/alpha", "example/bravo", "example/charlie"}
    # Simulate an interruption after publishing the workspace and before its entry.
    entries.pop("example/alpha")
    run.write_json(index, entries)
    assert prepare("alpha", sandbox) == first
    assert len(run.read_json(index)) == 3


@pytest.mark.slow
def test_manual_collection_requires_same_session(runner, tmp_path):
    info = run.execute(runner.parse_args([
        "prepare", "--case", "clarify", "--model", "example", "--host", "codex",
        "--host-version", "1", "--invocation", "native",
    ]))
    assert info["next_input"] == "/spex create Add a setting"
    assert info["handoff"] == "manual"
    reply = tmp_path / "reply.txt"
    reply.write_text("What type?", encoding="utf-8")
    argv = ["collect", info["trial"], "--reply", str(reply), "--session"]
    next_turn = run.execute(runner.parse_args([*argv, "example-2"]))
    assert next_turn["next_input"] == "Use a boolean setting"
    with pytest.raises(ValueError, match="same valid session"):
        run.execute(runner.parse_args([*argv, "wrong-session"]))
    reply.write_text("Done", encoding="utf-8")
    result = run.execute(runner.parse_args([*argv, "example-2"]))
    assert result["verdict"] == "pass"
    assert result["next_input"] is None
    turn = run.read_json(Path(info["trial"]) / "turn-2.json")
    assert "events" not in turn["artifacts"]


@pytest.mark.slow
def test_prepare_accepts_current_hosts_and_unknown_labels(runner):
    for host in ("qoder", "cursor", "other", "codex"):
        info = run.execute(runner.parse_args([
            "prepare", "--case", "clarify", "--host", host, "--invocation", "native",
        ]))
        metadata = run.read_json(Path(info["trial"]) / "trial.json")
        assert info["host"] == host
        assert info["host_version"] == "unknown"
        assert info["model"] == "unknown"
        assert info["handoff"] == "manual"
        assert info["workspace"].endswith("/repo")
        assert info["next_input"] == "/spex create Add a setting"
        assert (Path(info["skill"]) / "SKILL.md").is_file()
        assert metadata["collection"] == "manual"
        assert metadata["host"] == host
    with pytest.raises(SystemExit):
        runner.parse_args(["prepare", "--case", "clarify", "--host", "Qoder"])


@pytest.mark.slow
@pytest.mark.parametrize("from_stdin", [False, True])
def test_export_packet_and_import_external_grades(runner, tmp_path, monkeypatch, from_stdin):
    (run.SUITES / "example" / "rubrics.json").write_text(json.dumps({
        "version": 1,
        "cases": {
            "clarify": [{
                "id": "coverage", "turn": 1, "requires": ["state"], "threshold": 2,
                "anchors": ["Missing", "Partial", "Complete"],
            }, {
                "id": "trace", "turn": 1, "requires": ["events"], "threshold": 1,
                "anchors": ["Missing", "Partial", "Complete"],
            }],
        },
    }), encoding="utf-8")
    info = run.execute(runner.parse_args([
        "prepare", "--case", "clarify", "--host", "qoder", "--invocation", "native",
    ]))
    reply = tmp_path / "reply.txt"
    reply.write_text("What type?", encoding="utf-8")
    argv = ["collect", info["trial"], "--reply", str(reply), "--session", "host-1"]
    assert run.execute(runner.parse_args(argv))["verdict"] == "pending"
    reply.write_text("Done", encoding="utf-8")
    assert run.execute(runner.parse_args(argv))["verdict"] == "pass"

    exported = run.execute(runner.parse_args(["export-packet", info["trial"]]))
    assert exported["criteria"] == 1
    assert exported["insufficient"] == 1
    packet = run.read_json(Path(exported["packet"]))
    assert packet["insufficient"][0]["criterion_id"] == "trace"
    assert "Grade the supplied criteria" in Path(exported["prompt"]).read_text(encoding="utf-8")

    raw = json.dumps([{
        "criterion_id": "coverage", "score": 2, "verdict": "pass",
        "reason": "The first-turn state covers the clarification outcome.",
        "evidence_refs": ["turn-1:state"],
    }])
    grades = tmp_path / "grades.json"
    if from_stdin:
        monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    else:
        grades.write_text(raw, encoding="utf-8")
    imported = run.execute(runner.parse_args([
        "import-grades", info["trial"], "--grades", "-" if from_stdin else str(grades),
        "--host", "codex", "--model", "host-judge",
    ]))
    assert imported["hard_verdict"] == "pass"
    assert imported["verdict"] == "insufficient_evidence"
    judgment = run.read_json(Path(info["trial"]) / "judge.json")
    assert judgment["source"] == "external"
    assert judgment["host"] == "codex"
    assert judgment["model"] == "host-judge"
    assert {row["criterion_id"] for row in judgment["results"]} == {"coverage", "trace"}


@pytest.mark.slow
def test_manual_collection_continues_without_first_turn_trace(runner, tmp_path):
    manifest = run.SUITES / "example" / "cases.json"
    cases = run.read_json(manifest)
    cases[0]["turns"][0]["checks"].append("no-post-action")
    cases[0]["turns"][1]["input"] = "/spex apply-one-step example"
    manifest.write_text(json.dumps(cases), encoding="utf-8")

    info = run.execute(runner.parse_args([
        "prepare", "--case", "clarify", "--model", "example", "--host", "cursor",
        "--host-version", "1", "--invocation", "native",
    ]))
    reply = tmp_path / "reply.txt"
    reply.write_text("First step complete.", encoding="utf-8")
    args = runner.parse_args([
        "collect", info["trial"], "--reply", str(reply), "--session", "example-2",
    ])
    next_turn = run.execute(args)
    assert next_turn["verdict"] == "pending"
    assert next_turn["next_input"] == "/spex apply-one-step example"
    assert run.execute(args)["verdict"] == "insufficient_evidence"
    results = run.read_json(Path(info["trial"]) / "trial.json")["turn_results"]
    assert len(results) == 2
    assert results[0]["checks"][1]["verdict"] == "insufficient_evidence"
    assert results[1]["checks"][0]["verdict"] == "pass"
    metrics = run.read_json(Path(info["trial"]) / "performance.json")
    assert metrics["turns"]["1"]["host"]["trace"] == "missing"
    assert metrics["turns"]["1"]["host"]["duration_ms"] is None


@pytest.mark.slow
@pytest.mark.parametrize("first_session", [None, "real-codex-session"])
def test_collect_handoff_batch_runs_summary(runner, tmp_path, first_session):
    info = run.execute(runner.parse_args([
        "prepare", "--case", "clarify", "--model", "example", "--host", "codex",
        "--host-version", "1", "--invocation", "native",
    ]))
    sandbox = Path(info["sandbox"])
    handoff = sandbox / "_handoff"
    handoff.mkdir(exist_ok=True)
    (handoff / "example-clarify-turn1.txt").write_text("What type?\n", encoding="utf-8")
    second_reply = handoff / "example-clarify-turn2.txt"
    second_reply.write_text("Done\n", encoding="utf-8")
    collect_handoff.host_duration_sidecar(second_reply).write_text("1250\n")
    if first_session:
        run.execute(runner.parse_args([
            "collect", info["trial"], "--session", first_session,
            "--reply", str(handoff / "example-clarify-turn1.txt"),
        ]))
    else:
        with pytest.raises(ValueError, match="with later replies"):
            collect_handoff.collect_sandbox(sandbox, do_summary=True)
        second_reply.unlink()
        first = collect_handoff.collect_sandbox(sandbox)
        assert len(first["missing"]) == 1
        second_reply.write_text("Done\n", encoding="utf-8")
    payload = collect_handoff.collect_sandbox(sandbox, do_summary=True)
    assert payload["missing"] == []
    assert len(payload["collected"]) == 1
    assert payload["collected"][0]["verdict"] == "pass"
    assert Path(payload["report"]).is_file()
    assert "Score summary" in Path(payload["report"]).read_text(encoding="utf-8")
    metadata = run.read_json(Path(info["trial"]) / "trial.json")
    assert metadata["session"] == (first_session or "codex-example-clarify")
    timings = run.read_json(Path(info["trial"]) / "performance.json")["turns"]
    assert timings["2"]["host"]["duration_ms"] == 1250


@pytest.mark.parametrize(("filters", "count"), [
    (("--suite", "example clarify", "--case", "", "--tag", "smoke"), 0),
    (("--suite", "example"), 2),
])
def test_prepare_reports_rejected_filters(runner, filters, count):
    manifest = run.SUITES / "example" / "cases.json"
    cases = run.read_json(manifest)
    run.write_json(manifest, [cases[0], {**cases[0], "id": "follow-up"}])
    args = runner.parse_args(["prepare", "--host", "codex", *filters])
    with pytest.raises(ValueError) as error:
        run.execute(args)
    assert str(error.value) == (
        f"Expected exactly one case for prepare, found {count} "
        f"with --suite {args.suite!r}, --case {args.case!r}, --tag {args.tag!r}"
    )
    assert not run.RUNS.exists()


@pytest.mark.slow
def test_collect_handoff_reports_missing_reply(runner, tmp_path):
    info = run.execute(runner.parse_args([
        "prepare", "--case", "clarify", "--model", "example", "--host", "cursor",
        "--host-version", "1",
    ]))
    sandbox = Path(info["sandbox"])
    payload = collect_handoff.collect_sandbox(sandbox, do_summary=False)
    assert len(payload["missing"]) == 1
    assert payload["missing"][0]["status"] == "missing_handoff"
    assert "turn1" in payload["missing"][0]["missing"]


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "darwin", reason="Requires the macOS acceptance sandbox")
@pytest.mark.parametrize(("suite", "case_id", "selector"), [
    ("python-cli", "create", "new-plan"),
    ("docs", "analyze-incident", "analyze-incident"),
])
def test_macos_acceptance_launches_real_fixture(tmp_path, suite, case_id, selector):
    case = workspace.select_cases(run.SUITES, suite=suite, case_id=case_id)[0]
    trial = workspace.prepare_trial(REPO, case, parent=tmp_path / "case")
    result = run.acceptance(trial, suite, selector)
    assert result["passed"] is False
    assert result["checks"]


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "darwin", reason="Requires the macOS acceptance sandbox")
def test_macos_acceptance_denies_sibling_trial_reads(runner, tmp_path):
    case = workspace.select_cases(run.SUITES)[0]
    trial = workspace.prepare_trial(REPO, case, parent=tmp_path / "case")
    canary = tmp_path / "other-trial" / "evidence.json"
    canary.parent.mkdir()
    canary.write_text("fixture canary", encoding="utf-8")
    (run.SUITES / "example" / "acceptance.py").write_text(
        "import json\nfrom pathlib import Path\n"
        "try:\n"
        f"    Path({str(canary)!r}).read_text()\n"
        "except PermissionError:\n"
        "    print(json.dumps({'passed': True}))\n"
        "else:\n"
        "    print(json.dumps({'passed': False}))\n"
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    assert run.acceptance(trial, "example", "canary") == {"passed": True}


@pytest.mark.slow
def test_host_turn_timer_uses_wall_clock_across_processes(tmp_path):
    timer = REPO / "eval" / "spex" / "host_turn_timer.py"
    args = ["--sandbox", str(tmp_path), "--suite", "docs", "--case", "guide", "--turn", "1"]
    started = subprocess.run(
        [sys.executable, str(timer), "start", *args], capture_output=True, text=True, check=True,
    )
    pending = Path(json.loads(started.stdout)["pending"])
    payload = json.loads(pending.read_text())
    payload.update(started_at="2020-01-01T00:00:00+00:00", monotonic=1e30)
    pending.write_text(json.dumps(payload))
    stopped = subprocess.run(
        [sys.executable, str(timer), "stop", *args], capture_output=True, text=True, check=True,
    )
    measured = json.loads(stopped.stdout)
    reply = collect_handoff.handoff_reply(tmp_path, "docs", "guide", 1)
    timing = collect_handoff.read_host_wall_clock(reply)
    assert timing["host_duration_ms"] == measured["duration_ms"] > 1
    assert timing["host_started_at"] == payload["started_at"]
    assert timing["host_ended_at"] == measured["ended_at"]
    assert not pending.exists()
    collect_handoff.host_wall_clock_sidecar(reply).write_text("invalid")
    fallback = collect_handoff.read_host_wall_clock(reply)
    assert fallback["host_duration_ms"] == measured["duration_ms"]


@pytest.mark.slow
def test_collect_retry_uses_saved_timing_evidence(runner, monkeypatch):
    info = run.execute(runner.parse_args(["prepare", "--case", "clarify", "--host", "codex"]))
    output = Path(info["trial"])
    metadata_path = output / "trial.json"
    metadata = run.read_json(metadata_path)
    trial = workspace.Trial(Path(metadata["trial_directory"]), metadata["spex_ref"])
    log = trial.repo / ".spex" / "debug.log"
    log.parent.mkdir(exist_ok=True)
    log.write_text(
        "===== BEGIN 2026-11-17T09:00:21+08:00 =====\n"
        "argv: spex list\n===== END exit=0 duration_ms=9000 =====\n",
    )
    host = transport.HostTurn("same-session", "What type?", None, "")
    timing = {
        "host_started_at": "2026-11-17T09:00:11+08:00",
        "host_ended_at": "2026-11-17T09:00:21+08:00",
    }
    original_write = run.write_json
    with monkeypatch.context() as patch:
        def interrupted(path, value):
            if path == metadata_path:
                raise OSError("interrupted before trial metadata update")
            original_write(path, value)

        patch.setattr(run, "write_json", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            run.store_turn(output, trial, run.read_json(metadata_path), host, **timing)
    saved = run.read_json(output / "turn-1.json")
    assert saved["artifacts"]["spex-trace"]["value"]["events"]
    with log.open("a") as stream:
        stream.write(
            "===== BEGIN 2026-11-17T09:10:00+08:00 =====\n"
            "argv: spex list\n===== END exit=0 duration_ms=10 =====\n",
        )
    run.store_turn(output, trial, run.read_json(metadata_path), host, **timing)
    metrics = run.read_json(output / "performance.json")["turns"]["1"]["host"]
    assert metrics["duration_ms"] == 10000
    assert not {"missing_turn_timing_evidence", "implausible_host_duration"} & set(metrics["gaps"])
    assert run.read_json(output / "turn-1.json") == saved


def test_summary_explains_partially_graded_hard_failure(runner):
    sandbox = run.resolve_sandbox(None)
    out = workspace.case_dir(sandbox, "example", "partial-score")
    out.mkdir(parents=True)
    run.write_json(out / "trial.json", {
        "suite": "example", "case_id": "partial-score", "verdict": "fail",
        "turn_results": [{"turn": 1, "checks": [
            {"check_id": "no-post-action", "verdict": "fail"},
        ]}],
    })
    run.write_json(out / "judge.json", {
        "verdict": "pass",
        "results": [
            {"criterion_id": "goal", "score": 2, "verdict": "pass"},
            {"criterion_id": "later", "score": None, "verdict": "insufficient_evidence"},
        ],
    })
    result = run.summarize_sandbox(sandbox)
    row = run.read_json(Path(result["report_json"]))["trials"][0]
    assert row["final_verdict"] == row["hard_verdict"] == "fail"
    assert (row["score_sum"], row["score_max"], row["criteria_scored"], row["criteria_total"]) == (
        2, 2, 1, 2,
    )
    markdown = Path(result["report"]).read_text(encoding="utf-8")
    assert "| Case | Verdict | Score | Criteria |" in markdown
    assert (
        r"| example/partial-score | fail | 2/2 (1/2 criteria) \* | goal=2, later=ungraded |"
    ) in markdown
    assert "`example/partial-score` had 1/2 criteria graded" in markdown
    assert "`turn1:no-post-action=fail`" in markdown


@pytest.mark.parametrize("gaps", [None, "prefix implausible_host_duration suffix"])
def test_summary_tolerates_malformed_host_gaps(runner, gaps):
    sandbox = run.resolve_sandbox(None)
    out = workspace.case_dir(sandbox, "example", "malformed-timing")
    out.mkdir(parents=True)
    run.write_json(out / "trial.json", {
        "suite": "example", "case_id": "malformed-timing", "verdict": "pass",
    })
    run.write_json(out / "performance.json", {
        "schema_version": 1, "turns": {"1": {"host": {"gaps": gaps}}},
    })

    result = run.summarize_sandbox(sandbox)
    row = run.read_json(Path(result["report_json"]))["trials"][0]
    assert "unreadable_performance_file" in row["performance"]["gaps"]
    assert row["issues"] == []


def test_summary_distinguishes_recovered_exits_from_open_issues(runner):
    sandbox = run.resolve_sandbox(None)
    out = workspace.case_dir(sandbox, "example", "retry")
    out.mkdir(parents=True)
    run.write_json(out / "trial.json", {
        "suite": "example", "case_id": "retry", "verdict": "pass",
        "turn_results": [{"turn": 1, "checks": []}, {"turn": 2, "checks": []}],
    })

    def save_trace(turn, calls):
        log = []
        for args, code in calls:
            log.extend([
                "===== BEGIN 2026-11-16T12:13:14+00:00 =====",
                f"argv: spex {args}",
                f"===== END exit={code} duration_ms=1 =====",
            ])
        events = run.native_trace.parse(log, "specs/demo/debug.log", set())
        assert len(events) == len(calls)
        run.write_json(out / f"turn-{turn}.json", {
            "artifacts": {"spex-trace": {"value": {"events": events}}},
        })

    save_trace(1, [
        ("todo-helper --name demo edit --id step-1", 1),
        ("todo-helper --name demo edit --id step-1", 0),
        ("todo-helper --name demo append", 2),
        ("todo-helper --name demo edit --id step-2", 3),
        ("todo-helper --name demo edit --id step-3", 0),
        ("todo-helper --name demo show", 0),
        ("todo-helper --todo-file path/one.json edit --id step-1", 4),
        ("todo-helper --todo-file path/two.json edit --id step-1", 0),
        ("todo-helper --todo-file=path/two.json edit --id step-1", 5),
        ("todo-helper --todo-file path/two.json edit --id step-1", 0),
    ])
    save_trace(2, [("todo-helper --name demo append", 0)])
    result = run.summarize_sandbox(sandbox)
    row = run.read_json(Path(result["report_json"]))["trials"][0]
    assert [(i["command"], i["recovered"]) for i in row["issues"]] == [
        ("todo-helper edit", True), ("todo-helper append", False),
        ("todo-helper edit", False), ("todo-helper edit", False), ("todo-helper edit", True),
    ]
    markdown = Path(result["report"]).read_text(encoding="utf-8")
    assert "todo-helper edit exited with code 1 (recovered by retry)" in markdown
    assert "example/retry/turn-1.json" in markdown
    assert [item["summary"] for item in result["improvements"]] == [
        "example/retry: Turn 1: todo-helper append exited with code 2",
        "example/retry: Turn 1: todo-helper edit exited with code 3",
        "example/retry: Turn 1: todo-helper edit exited with code 4",
    ]
