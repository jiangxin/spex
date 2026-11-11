"""Offline checks for automated and manually collected Spex eval turns."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval" / "spex"))
try:
    import collect_handoff
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
        {"action": "apply.review", "exit_code": 1}, {"action": "apply.post-action", "exit_code": 0},
    ]
    with pytest.raises(transport.TransportError, match="session_mismatch"):
        transport.parse_events(trace, "wrong-session")
    with pytest.raises(transport.TransportError, match="rate_limit"):
        transport.parse_events('{"type":"turn.failed","error":{"message":"429 rate limit"}}')


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
    ("What type?", "pass", 2), ("Implementation finished.", "fail", 1),
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


def test_manual_trace_gaps_do_not_force_hard_insufficient_verdict():
    turns = [{
        "turn": 1,
        "checks": [
            {"check_id": "one-step", "verdict": "pass"},
            {"check_id": "post-action", "verdict": "insufficient_evidence"},
            {"check_id": "edit-guide", "verdict": "pass"},
        ],
    }]
    assert run.trial_verdict(turns, True, collection="manual") == "pass"
    assert run.trial_verdict(turns, True, collection="automatic") == (
        "insufficient_evidence"
    )
    assert run.trial_verdict(turns, True, collection="") == "insufficient_evidence"


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
        "suite": "example", "case_id": "clarify", "verdict": "pass",
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
        "verdict": "pass",
        "hard_verdict": "pass",
        "results": [
            {
                "criterion_id": "scope-correct",
                "score": 2,
                "verdict": "pass",
                "reason": "ok",
                "evidence_refs": ["turn-1:state"],
            }
        ],
    })
    backlog = tmp_path / "IMPROVEMENTS.md"
    result = run.execute(runner.parse_args([
        "summary", str(sandbox), "--write-improvements", str(backlog),
    ]))
    assert result["counts"] == {"pass": 1}
    assert result["classifications"] == {"evidence_gap": 1}
    assert result["trials"][0]["classification"] == "evidence_gap"
    assert result["trials"][0]["judge_host"] == "unknown"
    assert result["trials"][0]["judge_model"] == "unknown"
    assert result["scores"]["score_sum"] == 2
    assert result["scores"]["score_max"] == 2
    assert result["scores"]["score_ratio"] == 1.0
    assert result["improvements"]
    assert result["improvements"][0]["category"] == "efficiency"
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
    assert "Semantic score total: 2/2" in report
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
def test_export_packet_and_import_external_grades(runner, tmp_path):
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

    grades = tmp_path / "grades.json"
    grades.write_text(json.dumps([{
        "criterion_id": "coverage", "score": 2, "verdict": "pass",
        "reason": "The first-turn state covers the clarification outcome.",
        "evidence_refs": ["turn-1:state"],
    }]), encoding="utf-8")
    imported = run.execute(runner.parse_args([
        "import-grades", info["trial"], "--grades", str(grades),
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
    assert run.execute(args)["verdict"] == "pass"
    results = run.read_json(Path(info["trial"]) / "trial.json")["turn_results"]
    assert len(results) == 2
    assert results[0]["checks"][1]["verdict"] == "insufficient_evidence"
    assert results[1]["checks"][0]["verdict"] == "pass"
    metrics = run.read_json(Path(info["trial"]) / "performance.json")
    assert metrics["turns"]["1"]["host"]["trace"] == "missing"
    assert metrics["turns"]["1"]["host"]["duration_ms"] is None


@pytest.mark.slow
def test_collect_handoff_batch_runs_summary(runner, tmp_path):
    info = run.execute(runner.parse_args([
        "prepare", "--case", "clarify", "--model", "example", "--host", "cursor",
        "--host-version", "1", "--invocation", "native",
    ]))
    sandbox = Path(info["sandbox"])
    handoff = sandbox / "_handoff"
    handoff.mkdir(exist_ok=True)
    (handoff / "example-clarify-turn1.txt").write_text("What type?\n", encoding="utf-8")
    (handoff / "example-clarify-turn2.txt").write_text("Done\n", encoding="utf-8")
    payload = collect_handoff.collect_sandbox(sandbox, do_summary=True)
    assert payload["missing"] == []
    assert len(payload["collected"]) == 1
    assert payload["collected"][0]["verdict"] == "pass"
    assert Path(payload["report"]).is_file()
    assert "Score summary" in Path(payload["report"]).read_text(encoding="utf-8")


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
