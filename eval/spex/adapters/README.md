# Host adapters for Spex-eval

The runner never opens product sessions. Every host only needs to map onto
the portable interface documented in [`../README.md`](../README.md):

1. `prepare` / `prepare --sandbox` JSON
2. Reply files under `<sandbox>/_handoff/`
3. `collect` → `export-packet` → judge → `import-grades` → `summary`

## Shared checklist

| Step | Requirement |
| --- | --- |
| Isolate | One tested session per trial; separate session for the judge |
| Schedule | Respect `execution.jobs` from `prepare`. By default finish every trial, including grading, before starting the next one |
| Env | Export every key in prepare `environment` (especially `PATH`, `HOME`, `SPEX_CONFIG_FILE`) before invoking Spex |
| Skill | Follow the pinned `skill` path; write only under `workspace` |
| Input | Send `next_input` exactly; keep the same session for later turns |
| Output | Write `_handoff/<suite>-<case>-turnN.txt` |
| Events | Optional Codex-style JSONL via `collect --events`; without it, manual collection softens pure `post-action` / `no-post-action` hard verdicts |
| Timing | Pass `collect --host-duration-ms` and `import-grades --judge-duration-ms` when the adapter measures the respective session turn |
| Collect | `collect --session ID --reply <file> [--events …]` |

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
- Manual Codex handoff still uses `_handoff/` + `collect` like any other host.

## Pure manual (any IDE)

- Paste `next_input` into a session whose cwd/env match prepare JSON.
- Save the final assistant reply under `_handoff/` and run `collect`.
- Skip `--events` unless you can produce a compatible transcript.
