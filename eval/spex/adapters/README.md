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
| Output | Save the final reply to the path published by `manual.py start` |
| Events | Optional supplementary Codex-style JSONL beside the reply with suffix `.events.jsonl` |
| Timing | Stop the current turn timer once its final reply is ready |
| Collect | Use `manual.py collect` before starting the next turn |
| Host failure | Record a launch failure, host exit or timeout with `manual.py fail` so the next case can claim the slot |
| Complete | Import grades and complete each case; require terminal status before summarizing |

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
- Stop the timer, save the reply and run `manual.py collect`.
- Supply an events sidecar only when a compatible transcript is available.
