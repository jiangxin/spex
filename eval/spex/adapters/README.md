# Host adapters for Spex-eval

The runner never opens product sessions. Every host only needs to map onto
the portable interface documented in [`../README.md`](../README.md):

1. `prepare` / `prepare --sandbox` publishes the batch handoffs.
2. `manual.py` initializes the queue, claims cases and guards turn collection.
3. `export-packet` → judge → `import-grades` → queue completion → `summary`.

## Shared checklist

| Step | Requirement |
| --- | --- |
| Isolate | One tested session per trial; separate session for the judge |
| Schedule | Treat `execution.jobs` as the worker ceiling and hold each claim through grading or terminal failure |
| Env | Apply the prepared environment, including `SPEX_LOG_DIR`, and unset inherited `SPEX_TRACE_FILE`. Use `manual.py exec` for shell commands. |
| Skill | Follow the pinned `skill` path and write under `workspace` |
| Input | Start each turn, send its exact `next_input` and preserve the session |
| Output | Stage the full reply and publish with `manual.py stop SUITE/CASE TURN --reply-file PATH` or atomically rename it from the same directory to the reply path returned by `start` |
| Events | Finish optional supplementary Codex-style JSONL beside the reply with suffix `.events.jsonl` before publishing the reply |
| Timing | Stop the current turn timer once its final reply is ready |
| Collect | Use `manual.py collect` before starting the next turn |
| Host failure | Record a launch failure, host exit or timeout with `manual.py fail` so the next case can claim the slot |
| Complete | Import grades and complete each case; require terminal status before summarizing |

## Prepare a batch with structured arguments

Run this example from the repository root. Set the filters, host, and
worker ceiling for the batch. Save the report outside version control.

```bash
python3 - > prepare-batch.json <<'PY'
import json
import subprocess
import sys
from pathlib import Path

runner = [sys.executable, "eval/spex/run.py"]
if len(sys.argv) > 1:
    previous = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    selected = previous["selected"]
    pending = previous["failures"]
    prepared = previous["prepared"]
    sandbox = previous["sandbox"]
    options = previous["prepare_options"]
else:
    filters = ["--suite", "docs"]
    ref = "HEAD"
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"],
        text=True,
    ).strip()
    options = ["--host", "other", "--spex-ref", commit, "--jobs", "1"]
    selected = json.loads(subprocess.check_output(
        [*runner, "list", *filters], text=True,
    ))["cases"]
    if not selected:
        raise SystemExit(f"No cases matched {filters!r}")
    pending, prepared, sandbox = selected, [], None

failures = []
for case in pending:
    suite, case_id = case["suite"], case["id"]
    command = [*runner, "prepare", "--suite", suite, "--case", case_id, *options]
    if sandbox:
        command.extend(["--sandbox", sandbox])
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        failures.append({
            "suite": suite, "id": case_id, "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr,
        })
        continue
    handoff = json.loads(result.stdout)
    sandbox = handoff["sandbox"]
    prepared.append({"suite": suite, "id": case_id, "handoff": handoff})

report = {"sandbox": sandbox, "prepare_options": options, "selected": selected,
          "prepared": prepared, "failures": failures}
if not failures:
    keys = [f"{case['suite']}/{case['id']}" for case in selected]
    result = subprocess.run(
        [sys.executable, "eval/spex/manual.py", "--sandbox", sandbox, "init", *keys],
        capture_output=True, text=True,
    )
    report["queue_init"] = {"exit_code": result.returncode,
                            "stdout": result.stdout, "stderr": result.stderr}

print(json.dumps(report, indent=2))
sys.exit(1 if failures else result.returncode)
PY
```

Inspect `failures` even when the report has no sandbox. The runner can
send error JSON to stdout. After correcting the cause, rerun the example
with the opening line
`python3 - prepare-batch.json > prepare-retry.json <<'PY'`. Use a new
output path for each retry. The example keeps successful handoffs and
reuses the saved options and sandbox. Dispatch cases from the `prepared`
handoffs once `queue_init.exit_code` is zero. If you deliberately select
a smaller batch, report its coverage relative to the original request.

## Schedule current-host trials

Coordinate trials from the current Agent session. Use parallel dispatch
when the host can open independent trial sessions and resume each one
across turns. Otherwise prepare a new batch with `--jobs 1` and run
one trial at a time, using manual handoffs if the host cannot open
sessions directly. When continuing an existing sandbox, retain its saved
ceiling and claim only as many trials as the host can run.

Before dispatch, verify the prepared workspace, pinned skill and CLI, and
environment. If the host cannot apply cwd and environment when opening a
session, run shell commands via
`manual.py --sandbox PATH exec SUITE/CASE -- COMMAND ...` and resolve
file operations in the prepared workspace. Collect each turn before
resuming its session to send the next input. Keep grading in a separate
session.

### Account for host capacity

Within each shared session pool, count all active sessions, including the
coordinator if the host counts it. Reserve room for nested implementation,
review, and separate grading sessions before claiming another trial. Budget
independent pools separately. In a four-session pool with one coordinator
and one reserved session for nested work or grading, at most two trial
sessions can be open, even with `execution.jobs` set to four.

If the host refuses a launch due to capacity, pause new claims. Wait for a
session to finish or another observable change that frees a slot. Continue
at a lower concurrency when needed.

- If the refused operation did not start and the session can continue
  safely, retry only that operation. If `manual.py start` already ran,
  keep the bound session and timer. Send the input only if it was the
  refused operation and did not start. After the final reply, stop the
  timer and collect the turn once.
- If the trial cannot continue safely, record the terminal failure with
  `manual.py --sandbox PATH fail SUITE/CASE --reason REASON`. Use
  `launch_failed`, `exited`, or `timeout` according to what occurred.
  This releases the claim and preserves the original trial and evidence.
  Prepare the same suite and case in a new sandbox with the saved Spex
  commit, host, model, and `--invocation` mode. Initialize its queue and run
  it as an independent trial.

Report the phase of the capacity refusal, configured worker limit, and
observed concurrency. Link the original and rerun trial directories and
give each outcome when a separate rerun was needed.

## Cursor (manual / Task)

- Prefer one Task (or chat) per trial workspace; do not share state across cases.
- Apply `environment` to every shell tool call in that session.
- Pass `--model <id>` on `prepare` when the Cursor model is known; otherwise
  leave `unknown` and say so in the final summary.
- Judge: open a **separate** session, read only `judge-prompt.txt` from
  `export-packet` (do not summarize evidence yourself), write grades JSON,
  then `import-grades`.

## Codex CLI

- Use `eval/spex/run.py run` for automated trials when the requester asks
  for Codex automation (`run` / `judge` / `calibrate` remain Codex-only).
- Manual Codex uses the same guarded handoff as any other current host.

## Pure manual (any IDE)

- Paste the input returned by `manual.py start` into the prepared session.
- Stage the final reply, then run `manual.py stop SUITE/CASE TURN --reply-file PATH`
  to publish it and stop the timer. Run `manual.py collect` for that turn.
- Supply an events sidecar only when a compatible transcript is available.
