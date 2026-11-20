"""Offline tests for Spex workflow evidence and gates."""

import json
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "spex"))
try:
    import evidence
    import native_trace
    from transport import command_event
    from workspace import Trial, initialize_repo
finally:
    sys.path.pop(0)


def state(*tasks):
    return {
        "head": "base", "status": "", "index": "base", "files": {"cli.py": "base"},
        "specs": {"eval-spec": {"todo.json": list(tasks)}},
    }


@pytest.mark.parametrize(("args", "facts"), [
    (["-d", "todo_helper", "edit", "example", "--details", "--help"],
     ("todo-helper", "edit", "example", False)),
    (["todo-helper", "transaction", "start", "--todo-file=plans/todo.json"],
     ("todo-helper", "transaction", "plans/todo.json", False)),
    (["todo-helper", "edit", "example", "--name", "other"],
     ("todo-helper", "edit", None, False)),
    (["todo-helper", "show", "--", "--help"], ("todo-helper", "show", "--help", False)),
    (["review-helper", "--help"], ("review-helper", None, None, True)),
    (["prompt", "create-todo", "example"], ("prompt", "create-todo", "example", False)),
])
def test_trace_command_facts(args, facts):
    assert native_trace.command_facts({"argv": ["/installed/bin/spex", *args]}) == facts


@pytest.mark.parametrize("flag", ["--done", "--undone", "--wrap", "--no-wrap"])
def test_trace_todo_switch_does_not_consume_target(flag):
    event = {"argv": ["spex", "todo-helper", "show", flag, "example"]}
    assert native_trace.command_facts(event) == ("todo-helper", "show", "example", False)


@pytest.mark.parametrize(("legacy_count", "span_count", "expected"), [
    (1, 1, {0}), (2, 1, set()), (1, 2, set()), (1, 0, set()),
])
def test_review_help_requires_unique_legacy_correlation(legacy_count, span_count, expected):
    legacy = {"action": "apply.review-command", "command": "review-helper",
              "at": "2026-01-01T00:00:00Z", "duration_ms": 12, "exit_code": 0}
    span = {**legacy, "argv": ["spex", "review-helper", "--help"]}
    assert native_trace.review_help_events({
        "events": [legacy] * legacy_count, "timing_events": [span] * span_count,
    }) == expected


def test_review_help_preserves_commands_with_help_values_or_subcommands():
    events = [{"action": "apply.review-command", "argv": ["spex", "review-helper", *args]}
              for args in (["-h"], ["status", "--help"], ["append", "--title", "--help"])]
    assert native_trace.review_help_events({"events": events}) == {0}


def task(task_id, completed_at="", **extra):
    return {"id": task_id, "completed_at": completed_at, **extra}


def cli_log(argv, code=0):
    return (
        "===== BEGIN 2026-11-11T10:00:00+08:00 =====\n"
        f"argv: spex {argv}\n"
        f"===== END exit={code} duration_ms=10 =====\n"
    )


@pytest.mark.parametrize(
    ("path", "edits", "verdict"),
    [
        ("rebuild", ("remove_undone", "append"), "pass"),
        ("targeted", ("insert", "move", "remove"), "pass"),
        ("targeted", ("insert-options", "move-options", "remove"), "pass"),
        ("targeted", ("remove-undone", "append"), "fail"),
        ("targeted", ("remove-undone:1", "insert", "move", "remove"), "fail"),
        ("rebuild", ("append", "remove-undone"), "fail"),
        ("rebuild", ("remove-undone", "append@other-spec"), "fail"),
        ("rebuild", ("remove-undone", "append:1"), "fail"),
        ("rebuild", ("remove-undone", "append", "rollback", "start"), "fail"),
        ("targeted", ("insert", "move", "remove", "commit"), "fail"),
        ("targeted", ("insert", "move", "remove", "post-action", "edit"), "pass"),
    ],
)
def test_modify_native_path(tmp_path, path, edits, verdict):
    source = native_trace.CENTRAL_DEBUG_LOG
    commands = {
        action: f"todo_helper transaction {action} eval-spec"
        for action in ("start", "commit", "rollback")
    }
    commands["post-action"] = "create-helper post-action --event-type=modify --name eval-spec"
    commands["insert-options"] = (
        "todo-helper insert --before 2 --skip-commit=auto eval-spec "
        "--step-name Punctuation --details-from-stdin"
    )
    commands["move-options"] = "todo-helper move --from 3 --to=4 eval-spec"
    lines = []
    for edit in ("start", *edits, "post-action", "commit"):
        verb, _, code = edit.partition(":")
        verb, _, spec = verb.partition("@")
        lines.extend(cli_log(
            commands.get(verb, f"todo-helper {verb} {spec or 'eval-spec'}"),
            int(code) if code else 0,
        ).splitlines())
    gaps = set()
    events = native_trace.parse(lines, source, gaps)
    assert events[0]["transaction_action"] == "start"
    assert events[-1]["transaction_action"] == "commit"
    assert events[-2]["event_type"] == "modify"
    assert events[0]["spec"] == events[-1]["spec"] == events[-2]["spec"] == "eval-spec"
    assert not gaps
    before = evidence.persist_turn(tmp_path, 0, state(task(1)))
    after = evidence.persist_turn(
        tmp_path, 1, state(task(2)), native={"gaps": [], "events": events},
    )
    result = evidence.check_gate(f"modify-{path}-path", before, after)
    assert result["verdict"] == verdict
    assert "turn-1:spex-trace" in result["evidence_refs"]


@pytest.mark.parametrize(
    ("argv", "spec", "action"),
    [
        ("todo-helper transaction --name=eval-spec commit", "eval-spec", "commit"),
        ("todo-helper transaction rollback --todo-file /tmp/todo.json", None, "rollback"),
        ("todo-helper move --from 3 --to 4", None, None),
        ("todo-helper insert --details=eval-spec --before 2 --step-name Example", None, None),
        ("todo-helper edit --details --name --id=1 eval-spec", "eval-spec", None),
    ],
)
def test_native_todo_selector(argv, spec, action):
    event, = native_trace.parse(cli_log(argv).splitlines(), native_trace.CENTRAL_DEBUG_LOG, set())
    assert event["spec"] == spec
    assert event.get("transaction_action") == action


@pytest.mark.parametrize(("path", "edits"), [
    ("rebuild", ("remove-undone", "append")),
    ("targeted", ("insert", "move", "remove")),
])
@pytest.mark.parametrize(("finalizers", "code", "verdict"), [
    (["eval-spec"], 0, "pass"),
    ([""], 0, "pass"),
    (["", ""], 0, "insufficient_evidence"),
    (["other-spec"], 0, "fail"),
    (["eval-spec"], 1, "fail"),
])
def test_modify_finalize_path(tmp_path, path, edits, finalizers, code, verdict):
    log = cli_log("todo-helper transaction start eval-spec")
    log += "".join(cli_log(f"todo-helper {edit} eval-spec") for edit in edits)
    log += "".join(cli_log(f"create-helper finalize-modify {spec}".strip(), code)
                   for spec in finalizers)
    gaps = set()
    events = native_trace.parse(log.splitlines(), native_trace.CENTRAL_DEBUG_LOG, gaps)
    assert events[-1]["spec"] == (finalizers[-1] or None)
    before = evidence.persist_turn(tmp_path, 0, state(task(1)))
    after = evidence.persist_turn(
        tmp_path, 1, state(task(2)), native={"gaps": sorted(gaps), "events": events},
    )
    assert evidence.check_gate(f"modify-{path}-path", before, after)["verdict"] == verdict


@pytest.mark.parametrize(
    ("path", "argv", "structured", "verdict"),
    [
        ("rebuild", ["append", "eval-spec", "--step-name", "Add --repeat option"], True, "pass"),
        ("targeted", ["insert", "--before", "2", "--step-name", "Add punctuation's flag",
                      "eval-spec"], True, "pass"),
        ("rebuild", ["append", "eval-spec", "--step-name", "Add --repeat option"], False,
         "insufficient_evidence"),
    ],
)
def test_collected_modify_path_preserves_argv(tmp_path, path, argv, structured, verdict):
    baseline = native_trace.snapshot(tmp_path)
    (tmp_path / ".spex/specs/eval-spec").mkdir(parents=True)
    log = tmp_path / ".spex" / native_trace.CENTRAL_DEBUG_LOG
    log.parent.mkdir()
    extra_edits = (["todo-helper remove-undone eval-spec"] if path == "rebuild" else [])
    if path == "targeted":
        extra_edits.extend(["todo-helper move eval-spec --from 2 --to 3",
                            "todo-helper remove eval-spec --id 4"])
    words = ["todo-helper", *argv]
    log.write_text("".join(map(cli_log, [
        "todo-helper transaction start eval-spec",
        *extra_edits,
        " ".join(words),
        "create-helper post-action --name eval-spec --event-type modify",
        "todo-helper transaction commit eval-spec",
    ])))
    if structured:
        logged_at = "2026-11-11T10:00:00+08:00"
        stamp = native_trace.stamp_bounds(logged_at)[0]
        span = {
            "schema_version": 1,
            "name": "todo_helper",
            "start_time_unix_nano": stamp - 10_000_000,
            "end_time_unix_nano": stamp,
            "attributes": {"process.command_args": ["spex", *words], "process.exit.code": 0},
            "spex": {"duration_ms": 10, "debug_logged_at": logged_at},
        }
        log.with_name("trace.jsonl").write_text(json.dumps(span) + "\n")
    _, trace = native_trace.window(tmp_path, baseline)
    event = next(item for item in trace["events"] if item.get("subcommand") == argv[0])
    assert event["spec"] == ("eval-spec" if structured else None)
    assert "_todo_locator" not in json.dumps(trace)
    assert "process.command_args" not in json.dumps(trace)
    before = evidence.persist_turn(tmp_path, 0, state(task(1)))
    after = evidence.persist_turn(tmp_path, 1, state(task(2)), native=trace)
    assert evidence.check_gate(f"modify-{path}-path", before, after)["verdict"] == verdict


@pytest.mark.parametrize(
    ("missing", "verdict"),
    [
        ("artifact", "insufficient_evidence"),
        ("truncated", "insufficient_evidence"),
        ("ambiguous-order", "insufficient_evidence"),
        ("unbound-spec", "insufficient_evidence"),
        ("ordered-logs", "pass"),
    ],
)
def test_modify_path_requires_native_evidence(tmp_path, missing, verdict):
    before = evidence.persist_turn(tmp_path, 0, state(task(1)))
    gaps, events = [], []
    if missing == "truncated":
        gaps.append("incomplete_cli_log")
    if missing in {"ambiguous-order", "ordered-logs"}:
        stamp = "T10:00:02" if missing == "ordered-logs" else "T10:00:00"
        events += native_trace.parse(
            cli_log("todo-helper transaction start eval-spec").splitlines(),
            native_trace.CENTRAL_DEBUG_LOG, set(),
        ) + native_trace.parse(
            (
                cli_log("todo-helper remove-undone eval-spec")
                + cli_log("todo-helper append eval-spec")
                + cli_log("create-helper post-action --name eval-spec --event-type modify")
                + cli_log("todo-helper transaction commit eval-spec")
            ).replace("T10:00:00", stamp).splitlines(),
            "specs/eval-spec/debug.log", set(),
        )
    if missing == "unbound-spec":
        events += native_trace.parse(
            cli_log("todo-helper remove-undone --todo-file todo.json").splitlines(),
            native_trace.CENTRAL_DEBUG_LOG, set(),
        )
    trace = None if missing == "artifact" else {"gaps": gaps, "events": events}
    after = evidence.persist_turn(tmp_path, 1, state(task(2)), native=trace)
    result = evidence.check_gate("modify-rebuild-path", before, after)
    assert result["verdict"] == verdict


def test_integer_task_ids_count_toward_progress(tmp_path):
    before = evidence.persist_turn(tmp_path, 0, state(task("step-1", "done"), task("step-2")))
    after = evidence.persist_turn(tmp_path, 1, state(task(1, "done"), task(2, "later")))
    changed = evidence.persist_turn(tmp_path, 2, state(task(1, "changed"), task(2)))
    assert evidence.check_gate("one-step", before, after)["verdict"] == "pass"
    assert evidence.check_gate("no-progress", before, after)["verdict"] == "fail"
    assert evidence.check_gate("completed-preserved", before, changed)["verdict"] == "fail"
    assert evidence.completed(state(task(True, "done"))) == {}


def test_native_trace_excludes_setup_and_acceptance_between_turns(tmp_path):
    repo = tmp_path / "repo"
    log = repo / ".spex/specs/eval-spec/debug.log"
    log.parent.mkdir(parents=True)
    post = cli_log("apply-helper post-action eval-spec")
    log.write_text(post)
    checkpoint = native_trace.snapshot(repo)
    out = tmp_path / "evidence"
    before = evidence.persist_turn(out, 0, state(task("step-1")))
    with log.open("a") as stream:
        stream.write(cli_log("todo-helper edit eval-spec"))
    _, first = native_trace.window(repo, checkpoint)
    turn1 = evidence.persist_turn(out, 1, state(task("step-1", "done")), native=first)
    assert evidence.check_gate("no-post-action", before, turn1)["verdict"] == "pass"
    assert evidence.check_gate("post-action", before, turn1)["verdict"] == "fail"
    with log.open("a") as stream:
        stream.write(post)  # Acceptance output belongs to neither trial turn.
    checkpoint = native_trace.snapshot(repo)
    with log.open("a") as stream:
        stream.write(post)
    _, second = native_trace.window(repo, checkpoint)
    turn2 = evidence.persist_turn(out, 2, state(task("step-1", "done")), native=second)
    check = evidence.check_gate("post-action", turn1, turn2)
    assert check["verdict"] == "pass"
    assert "turn-2:spex-trace" in check["evidence_refs"]
    log.write_text(post)
    _, replaced = native_trace.window(repo, checkpoint)
    turn3 = evidence.persist_turn(out, 3, state(task("step-1", "done")), native=replaced)
    assert evidence.check_gate("post-action", turn2, turn3)["verdict"] == "insufficient_evidence"


def test_native_trace_links_central_commands_to_spec_anchors(tmp_path):
    central = tmp_path / ".spex/eval-logs/debug.log"
    central.parent.mkdir(parents=True)
    for name in ("first-spec", "second-spec", "legacy"):
        (tmp_path / ".spex/specs" / name).mkdir(parents=True)
    baseline = native_trace.snapshot(tmp_path)
    central.write_text(
        cli_log("apply-helper post-action --name first")
        + cli_log("apply-helper post-action second-spec")
        + cli_log("review-helper status second --step 1")
    )
    for name in ("first-spec", "second-spec"):
        (tmp_path / ".spex/specs" / name / "debug.log").write_text(
            "===== APPLY post-action ok =====\n"
            "===== APPLY review begin step=1 mode=full commit=1234567 =====\n"
            "===== APPLY review end step=1 mode=full commit=1234567 duration_ms=9 =====\n"
        )
    (tmp_path / ".spex/specs/legacy/debug.log").write_text(
        "===== APPLY post-action ok =====\n" + cli_log("apply-helper post-action --name legacy")
    )
    checkpoint, trace = native_trace.window(tmp_path, baseline)
    assert trace["gaps"] == []
    post = [event for event in trace["events"] if event["action"] == "apply.post-action"]
    assert {event["spec"]: event.get("success_anchor_log") for event in post} == {
        "first-spec": "specs/first-spec/debug.log",
        "second-spec": "specs/second-spec/debug.log",
        "legacy": None,
    }
    assert len(post) == 3 and all(event["success_anchor"] == 0 for event in post)
    assert {event["spec"] for event in trace["events"] if event["action"] == "apply.review"
            and event["exit_code"] == 0} == {"first-spec", "second-spec"}
    assert [event["spec"] for event in trace["events"]
            if event["action"] == "apply.review-command"] == ["second-spec"]
    with central.open("a") as stream:
        stream.write(cli_log("apply-helper post-action --name first"))
        stream.write(cli_log("apply-helper post-action --name spec"))
    _, next_turn = native_trace.window(tmp_path, checkpoint)
    assert all("success_anchor" not in event for event in next_turn["events"])
    assert "ambiguous_trace_spec" in next_turn["gaps"]
    assert [event["spec"] for event in next_turn["events"]] == ["first-spec", None]


def test_native_trace_reports_ambiguous_cross_file_pairing(tmp_path):
    central = tmp_path / ".spex/eval-logs/debug.log"
    central.parent.mkdir(parents=True)
    anchor = tmp_path / ".spex/specs/example/debug.log"
    anchor.parent.mkdir(parents=True)
    baseline = native_trace.snapshot(tmp_path)
    central.write_text(cli_log("apply-helper post-action --name example") * 2)
    anchor.write_text("===== APPLY post-action ok =====\n")
    _, trace = native_trace.window(tmp_path, baseline)
    assert trace["gaps"] == ["ambiguous_post_action_anchor"]
    assert all("success_anchor" not in event for event in trace["events"])


@pytest.mark.parametrize("step", ["step-1", 1])
def test_native_review_failure_stop_requires_no_later_workflow(tmp_path, step):
    pending = state(task(step))
    before = evidence.persist_turn(tmp_path, 0, pending)
    log = "specs/eval-spec/debug.log"
    failure = cli_log(f"review-helper --name eval-spec status --step {step} --json", 1)
    later = cli_log("prompt apply-one-task eval-spec")
    for turn, contents, verdict in ((1, failure, "pass"), (2, failure + later, "fail")):
        gaps = set()
        events = native_trace.parse(contents.splitlines(), log, gaps)
        after = evidence.persist_turn(
            tmp_path, turn, pending, native={"events": events, "gaps": sorted(gaps)},
        )
        assert evidence.check_gate("review-failure-stop", before, after)["verdict"] == verdict


@pytest.mark.parametrize("wrong_spec", [False, True])
def test_review_failure_stop_checks_spec_identity_and_pending_order(tmp_path, wrong_spec):
    pending = state(task("step-1"), task("step-2"))
    pending["specs"]["other-spec"] = {"todo.json": [task("step-1", "done")]}
    before = evidence.persist_turn(tmp_path, 0, pending)
    changed = json.loads(json.dumps(pending))
    changed["specs"]["eval-spec"]["todo.json"].reverse()
    selector = "other-spec" if wrong_spec else "eval-spec"
    log = cli_log(f"review-helper --name {selector} status --step step-1", 1)
    gaps = set()
    events = native_trace.parse(log.splitlines(), "debug.log", gaps)
    for turn, snapshot, expected in [
        (1, pending, "fail" if wrong_spec else "pass"), (2, changed, "fail"),
    ]:
        after = evidence.persist_turn(
            tmp_path, turn, snapshot, native={"events": events, "gaps": sorted(gaps)},
        )
        assert evidence.check_gate("review-failure-stop", before, after)["verdict"] == expected


@pytest.mark.parametrize(("variant", "verdict"), [
    ("direct", "pass"),
    ("legacy", "pass"),
    ("ambiguous", "fail"),
    ("unbound-before-failure", "insufficient_evidence"),
    ("continuation", "fail"),
])
def test_review_failure_stop_excludes_only_confirmed_help(tmp_path, variant, verdict):
    pending = state(task("step-1"))
    gaps = set()
    log = cli_log("review-helper status eval-spec --step 1", 1)
    log += cli_log("review-helper --help").replace("10:00:00", "10:00:01")
    events = native_trace.parse(log.splitlines(), "eval-logs/debug.log", gaps)
    help_event = events[-1]
    argv = ["spex", "review-helper", "--help"]
    spans = [{**help_event, "argv": argv}]
    if variant == "direct":
        help_event["argv"] = argv
    elif variant == "ambiguous":
        spans.append(dict(spans[0]))
    elif variant == "unbound-before-failure":
        events.insert(0, {**help_event, "at": "2026-11-11T09:59:59+08:00", "sequence": -1})
    elif variant == "continuation":
        events.append({**events[0], "sequence": help_event["sequence"] + 1, "exit_code": 0})
    before = evidence.persist_turn(tmp_path, 0, pending)
    after = evidence.persist_turn(tmp_path, 1, pending, native={
        "events": events, "gaps": sorted(gaps), "timing_events": spans,
    })
    assert evidence.check_gate("review-failure-stop", before, after)["verdict"] == verdict


def test_native_prompt_skip_requires_logged_output_and_success():
    log = cli_log("prompt apply-review --name eval-spec --commit abc1234")
    log = log.replace(
        "===== END", "----- stdout -----\n"
        "[truncated prompt stdout, total=120B; task_id=step-1; skipped=True]\n===== END",
    )
    events = native_trace.parse(log.splitlines(), "specs/eval-spec/debug.log", set())
    assert events[0]["action"] == "apply.review-command"
    assert events[0]["skipped"] is True
    assert events[0]["step"] == "step-1"
    assert events[0]["commit"] == "abc1234"


@pytest.mark.parametrize(("fix", "expected"), [(False, "92590d9"), (True, "63d5bac")])
@pytest.mark.parametrize("step", ["step-1", 1])
def test_native_resume_follows_the_reviewed_commit(tmp_path, fix, expected, step):
    old = state(task(step, commit_title="92590d9: Prefix"))
    old["head"] = "92590d94072433285b225f79e51fec80de172381"
    before = evidence.persist_turn(tmp_path, 0, old)
    lines = [
        f"===== APPLY review {edge} step={step} round=1 mode=full commit=92590d9 ====="
        for edge in ("begin", "end")
    ]
    if fix:
        lines.append(f"===== APPLY fix end step={step} base=92590d9 new=63d5bac =====")
    gaps = set()
    events = native_trace.parse(lines, "specs/eval-spec/debug.log", gaps)
    after = evidence.persist_turn(
        tmp_path, 1, state(task(step, "done", commit_title=f"{expected}: Prefix")),
        native={"events": events, "gaps": sorted(gaps)},
    )
    assert evidence.check_gate("resumed-review", before, after)["verdict"] == "pass"


def test_optional_observations_fill_gaps_without_proving_absence(tmp_path):
    before = evidence.persist_turn(tmp_path, 0, state(task("step-1")))
    after = evidence.persist_turn(
        tmp_path, 1, state(task("step-1", "done")),
        native={"events": [], "gaps": ["missing_spex_commands"]},
        supplemental=[{"action": "apply.post-action", "spec": "eval-spec",
                       "exit_code": 0, "source": "observed"}],
    )
    assert evidence.check_gate("post-action", before, after)["verdict"] == "pass"
    assert evidence.check_gate("no-post-action", before, after)["verdict"] == "fail"
    unsupported = evidence.persist_turn(
        tmp_path, 2, state(task("step-1", "done")),
        native={"events": [], "gaps": ["missing_spex_commands"]}, supplemental=[],
    )
    assert evidence.check_gate("no-post-action", before, unsupported)["verdict"] == (
        "insufficient_evidence"
    )


@pytest.mark.parametrize(("command", "gaps", "required", "forbidden"), [
    ("/fixture/scripts/spex apply-helper post-action --name eval-spec",
     ["missing_spex_commands"], "pass", "fail"),
    ("/fixture/scripts/spex apply-helper post-action eval-spec",
     [], "insufficient_evidence", "fail"),
    ("/fixture/scripts/spex apply-helper post-action --name other-spec",
     ["missing_spex_commands"], "insufficient_evidence", "insufficient_evidence"),
    ("/fixture/scripts/spex apply-helper post-action --name eval-spec || true",
     ["missing_spex_commands"], "insufficient_evidence", "insufficient_evidence"),
])
def test_host_transcript_supplements_native_post_action(
    tmp_path, command, gaps, required, forbidden,
):
    before = evidence.persist_turn(tmp_path, 0, state(task("step-1")))
    after = evidence.persist_turn(
        tmp_path, 1, state(task("step-1", "done")),
        native={"events": [], "gaps": gaps},
        events=[command_event({"command": command, "exit_code": 0})],
    )
    required_check = evidence.check_gate("post-action", before, after)
    assert required_check["verdict"] == required
    if forbidden == "fail":
        assert "turn-1:events" in required_check["evidence_refs"]
    assert evidence.check_gate("no-post-action", before, after)["verdict"] == forbidden


def test_early_write_and_evidence_integrity(tmp_path):
    before = evidence.persist_turn(tmp_path, 0, state())
    changed = state()
    changed["files"]["cli.py"] = "written"
    changed["specs"]["eval-spec"]["spec.md"] = "created early"
    after = evidence.persist_turn(tmp_path, 1, changed, user_input="/spex create")
    for check in ("no-code-change", "no-spec-write"):
        result = evidence.check_gate(check, before, after)
        assert result["verdict"] == "fail"
        assert result["evidence_refs"] == ["turn-0:state", "turn-1:state"]
    assert json.loads((tmp_path / "turn-1.json").read_bytes()) == after
    artifact = after["artifacts"]["state"]
    assert artifact["sha256"] == evidence.digest(evidence.encode(changed))
    with pytest.raises(FileExistsError):
        evidence.persist_turn(tmp_path, 1, state())


def test_one_step_rejects_two_completions_and_rewritten_tasks(tmp_path):
    preserved = task("step-1", "first", details="keep")
    before = evidence.persist_turn(tmp_path, 0, state(preserved, task("step-2"), task("step-3")))
    after = evidence.persist_turn(tmp_path, 1, state(preserved, task("step-2", "second")))
    overstep = evidence.persist_turn(
        tmp_path, 2, state(preserved, task("step-2", "second"), task("step-3", "third"))
    )
    rewritten = evidence.persist_turn(tmp_path, 3, state(dict(preserved, details="changed")))
    assert evidence.check_gate("one-step", before, after)["verdict"] == "pass"
    assert evidence.check_gate("one-step", before, overstep)["verdict"] == "fail"
    assert evidence.check_gate("completed-preserved", before, rewritten)["verdict"] == "fail"


@pytest.mark.parametrize(
    "selector", [
        '"eval-spec" --step "step-1"',
        '--step "step-1" "eval-spec"',
        '--ids=r1-f1 --evidence-from-stdin --step "step-1" "eval-spec"',
        '--workdir "other-spec" --spex-root "root-spec" --step "step-1" "eval-spec"',
    ],
)
@pytest.mark.parametrize(
    ("start", "amend_base", "final", "verdict"),
    [
        ("92590d9", None, "92590d9", "pass"),
        ("92590d9", "92590d9", "63d5bac", "pass"),
        ("92590d9", None, "63d5bac", "fail"),
        ("92590d9", "7777777", "63d5bac", "fail"),
        ("7777777", "92590d9", "63d5bac", "fail"),
        ("92590d9", "92590d9", "7777777", "fail"),
    ],
)
def test_resumed_review_binds_final_commit_to_seed(
    tmp_path, start, amend_base, final, verdict, selector,
):
    original = state(task("step-1", commit_title="92590d9: Prefix"))
    original["head"] = "92590d94072433285b225f79e51fec80de172381"
    before = evidence.persist_turn(tmp_path, 0, original)

    def event(command):
        normalized = command_event({
            "command": f"/bin/zsh -c {shlex.quote(command)}", "exit_code": 0,
        })
        assert normalized["action"] == "apply.review-command"
        return {**normalized, "action": "apply.review"}  # Legacy saved events.

    events = [
        event(f"./scripts/spex prompt apply-review --name eval-spec --mode full --commit {start}"),
    ]
    if amend_base:
        events.append(event(
            f'./scripts/spex review-helper complete-batch {selector} '
            f'--base-commit "{amend_base}" --new-commit "63d5bac" --evidence-from-stdin '
            "<<'EOF'\n{}\nEOF"
        ))
    after = evidence.persist_turn(
        tmp_path, 1, state(task("step-1", "done", commit_title=f"{final}: Prefix")), events=events,
    )
    assert evidence.check_gate("resumed-review", before, after)["verdict"] == verdict


def test_review_failure_requires_stop_and_trace(tmp_path):
    pending = state(task("step-1"))
    before = evidence.persist_turn(tmp_path, 0, pending)
    absent = evidence.persist_turn(tmp_path, 1, pending)
    failure = [{"action": "apply.review", "exit_code": 1}]
    stopped = evidence.persist_turn(tmp_path, 2, pending, events=failure)
    continued = evidence.persist_turn(
        tmp_path, 3, state(task("step-1", "done")), events=failure
    )
    post = evidence.persist_turn(
        tmp_path, 4, pending, events=[*failure, {"action": "apply.post-action", "exit_code": 0}]
    )
    reviewed_again = evidence.persist_turn(
        tmp_path, 5, pending, events=[*failure, {"action": "apply.review", "exit_code": 0}]
    )
    unclassified = evidence.persist_turn(tmp_path, 6, pending, events=[*failure, {}])
    unknown_result = evidence.persist_turn(
        tmp_path, 7, pending, events=[{"action": "apply.review"}]
    )
    head_probe = command_event({
        "command": "/bin/zsh -c 'git rev-parse --short HEAD'", "exit_code": 0,
    })
    after_probe = evidence.persist_turn(tmp_path, 8, pending, events=[*failure, head_probe])
    compound = command_event({
        "command": "/bin/zsh -c 'git rev-parse --short HEAD && echo unknown'", "exit_code": 0,
    })
    after_compound = evidence.persist_turn(tmp_path, 9, pending, events=[*failure, compound])
    check = "review-failure-stop"
    assert evidence.check_gate(check, before, absent)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate(check, before, stopped)["verdict"] == "pass"
    assert evidence.check_gate(check, before, continued)["verdict"] == "fail"
    assert evidence.check_gate(check, before, post)["verdict"] == "fail"
    assert evidence.check_gate(check, before, reviewed_again)["verdict"] == "fail"
    assert evidence.check_gate(check, before, unclassified)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate(check, before, unknown_result)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate(check, before, after_probe)["verdict"] == "pass"
    assert evidence.check_gate(check, before, after_compound)["verdict"] == "insufficient_evidence"
    assert evidence.check_gate("post-action", before, post)["verdict"] == "pass"


@pytest.mark.slow
def test_capture_detects_worktree_and_index_changes(tmp_path):
    trial = Trial(tmp_path, "unused")
    trial.repo.mkdir()
    script = trial.repo / "cli.py"
    script.write_text("print(1)", encoding="utf-8")
    initialize_repo(trial)
    before = evidence.capture(trial)
    script.write_text("print(2)", encoding="utf-8")
    changed = evidence.capture(trial)
    assert changed["head"] == before["head"]
    assert changed["index"] == before["index"]
    assert changed["files"] != before["files"]
    evidence.git(trial.repo, "add", "cli.py", env=trial.env)
    assert evidence.capture(trial)["index"] != before["index"]


def test_native_timing_prefers_precise_spans_and_keeps_legacy_only_folders(tmp_path):
    baseline = native_trace.snapshot(tmp_path)
    root = tmp_path / ".spex"
    spec = root / "specs" / "eval-spec"
    spec.mkdir(parents=True)
    shared = root / "eval-logs"
    shared.mkdir()
    (root / "debug.log").write_text(cli_log("list"))
    (shared / "debug.log").write_text(cli_log("list"))
    (spec / "debug.log").write_text(cli_log("list"))
    (shared / "trace.jsonl").write_text(json.dumps({
        "schema_version": 1, "start_time_unix_nano": 1, "end_time_unix_nano": 9,
    }) + "\n")
    checkpoint, evidence = native_trace.window(tmp_path, baseline)
    assert len(evidence["events"]) == 3
    assert [event["log"] for event in evidence["timing_events"]] == [
        "eval-logs/trace.jsonl", "debug.log", "eval-logs/debug.log", "specs/eval-spec/debug.log",
    ]
    assert evidence["timing_events"][0]["end_ns"] == 9
    _, after = native_trace.window(tmp_path, checkpoint)
    assert "timing_events" not in after and after["events"] == []


def test_native_checkpoint_tracks_new_and_legacy_logs_independently(tmp_path):
    import performance

    root = tmp_path / ".spex"
    paths = [
        root / location / "example" / layout
        for location in ("specs", "archives")
        for layout in (".", "logs")
    ]
    for folder in paths:
        folder.mkdir(parents=True)
        (folder / "debug.log").write_text(cli_log("list"))
        (folder / "trace.jsonl").write_text("")
    baseline = native_trace.snapshot(tmp_path)
    workflow_baseline = performance.workflow_metrics(tmp_path)
    for index, folder in enumerate(paths, start=1):
        with (folder / "debug.log").open("a") as handle:
            handle.write(cli_log("show"))
        with (folder / "trace.jsonl").open("a") as handle:
            handle.write(json.dumps({
                "schema_version": 1, "start_time_unix_nano": index, "end_time_unix_nano": index,
            }) + "\n")

    checkpoint, evidence = native_trace.window(tmp_path, baseline)
    assert len(checkpoint) == 8 and checkpoint.keys() == baseline.keys()
    assert {event["log"] for event in evidence["events"]} == {
        (folder / "debug.log").relative_to(root).as_posix() for folder in paths
    }
    assert {event["spec"] for event in evidence["events"]} == {"example"}
    assert {
        event["start_ns"] for event in evidence["timing_events"]
        if event["log"].endswith("/trace.jsonl")
    } == {1, 2, 3, 4}
    workflow = performance.workflow_metrics(tmp_path, workflow_baseline, new_turn=True)
    assert len(workflow["logs"]) == 4
    assert all(log["turn_offsets"] == [len(cli_log("list"))] for log in workflow["logs"])
    _, repeated = native_trace.window(tmp_path, checkpoint)
    assert repeated["events"] == [] and "timing_events" not in repeated


@pytest.mark.parametrize("flush_delay", [0, 1_000_000_000])
@pytest.mark.parametrize("extra_args", [[], ["--details", "first line\nsecond line"]])
def test_native_timing_deduplicates_matching_commands_without_hiding_legacy(
    tmp_path, flush_delay, extra_args,
):
    baseline = native_trace.snapshot(tmp_path)
    spec = tmp_path / ".spex/specs/eval-spec"
    spec.mkdir(parents=True)
    args = ["apply-helper", "--name", "eval-spec", "post-action", *extra_args]
    command = " ".join(args)
    other_spec = command.replace("eval-spec", "other-spec")
    (spec / "debug.log").write_text(
        cli_log(other_spec, 2) + cli_log(command, 2) + cli_log(command, 2) + cli_log("list"),
    )
    stamp = native_trace.stamp_bounds("2026-11-11T10:00:00+08:00")[0]
    span = {
        "schema_version": 1,
        "name": "apply_helper",
        "start_time_unix_nano": stamp - flush_delay,
        "end_time_unix_nano": stamp + 10_000_000 - flush_delay,
        "attributes": {"process.command_args": ["spex", *args], "process.exit.code": 2},
        "spex": {"duration_ms": 10},
    }
    if flush_delay:
        span["spex"]["debug_logged_at"] = "2026-11-11T10:00:00+08:00"
    (spec / "trace.jsonl").write_text(
        json.dumps(span) + "\n" + json.dumps({**span, "schema_version": True}) + "\n{",
    )

    _, captured = native_trace.window(tmp_path, baseline)
    assert len(captured["events"]) == 4
    timing = captured["timing_events"]
    assert [event["command"] for event in timing] == ["apply-helper"] * 3 + ["list"]
    assert timing[0]["subcommand"] == "post-action"
    assert timing[0]["spec"] == "eval-spec"
    assert timing[0]["end_ns"] == span["end_time_unix_nano"]
    assert timing[0]["exit_code"] == timing[1]["exit_code"] == 2
    assert timing[1]["spec"] is None and "end_ns" not in timing[1]
    assert timing[2]["spec"] == "eval-spec" and "end_ns" not in timing[2]
    assert all("_argv_fingerprint" not in event for event in [*timing, *captured["events"]])
    assert {"incomplete_cli_log", "unreadable_trace_jsonl"} <= set(captured["gaps"])
