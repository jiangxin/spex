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
| Schedule | Claim cases against `execution.jobs` (four by default for a new batch) and hold the slot through grading |
| Env | Apply the prepared environment, including `SPEX_LOG_DIR`, and unset inherited `SPEX_TRACE_FILE`. Use `manual.py exec` for shell commands. |
| Skill | Follow the pinned `skill` path and write under `workspace` |
| Input | Start each turn, send its exact `next_input` and preserve the session |
| Output | Save the final reply to the path published by `manual.py start` |
| Events | Optional supplementary Codex-style JSONL beside the reply with suffix `.events.jsonl` |
| Timing | Stop the current turn timer once its final reply is ready |
| Collect | Use `manual.py collect` before starting the next turn |
| Host failure | Record a launch failure, host exit or timeout with `manual.py fail` so the next case can claim the slot |
| Complete | Import grades and complete each case; require terminal status before summarizing |

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
