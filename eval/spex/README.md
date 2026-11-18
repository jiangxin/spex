# Spex workflow evaluations

The runner evaluates Spex workflow boundaries, fixture behavior, and semantic
quality. Each trial starts from an independent Git fixture, installs Spex from
a pinned commit, and collects its own evidence. The judge works in a separate
tool-free session. A failed deterministic check takes precedence over an AI
score.

Each trial installs the committed `skills/spex` tree from the selected
`--spex-ref` (default `HEAD`) into the trial workspace. It uses a trial-local
`HOME` and `SPEX_CONFIG_FILE` to isolate host installs and configuration.
The trial's `PATH` starts with the pinned skill's CLI directory, so a bare
`spex` command in the prepared environment resolves to that copy.
Commit skill edits before using them in a trial. Step review is enabled for
`python-cli` and disabled for `batch-import` and `docs`.

## Quick start

The default path evaluates Spex from the current host. Use macOS, Git, and
system Python 3.9 or newer. Python 3.11+ is recommended for full TOML
support. Run commands from the repository root.

```sh
python3 eval/spex/run.py list --tag smoke
python3 eval/spex/run.py prepare --suite docs --case analyze-incident \
  --host qoder
```

For a whole batch in one sandbox with a ready dispatch queue:

```sh
python3 eval/spex/run.py prepare --all --host qoder \
  --spex-ref HEAD --jobs 4 --init
```

`--init` requires `--all` and initializes the queue once every case is
prepared. The first `prepare` or `run` creates a sandbox at
`eval/spex/runs/YYYY-MM-DD-HH-MM-SS` (with `-2`, `-3`, … on name clash). That
directory is git-ignored via `/eval/spex/runs/` and is itself `git init`'d so
git commands inside the sandbox do not resolve to the Spex monorepo. Case
evidence and workspaces live under `suite/case/` (and `suite/case/<repeat>/`
for automated repeats):

```text
eval/spex/runs/2026-11-10-15-11-12/
  .spex.toml              # sandbox-local Spex config (isolates host trees)
  .spex/
  manifest.json
  report.md
  report.json
  _handoff/
  docs/analyze-incident/
    trial.json
    workspace/home/
    workspace/repo/
```

Pass `--sandbox PATH` on later `prepare` calls in the same batch. Filter with
`--suite python-cli`, `--suite docs`, or `--case CASE`. Use `--spex-ref REF`
to pin another Git revision. Omit `--model` or `--host-version` when they are
unknown; the runner records `unknown`.

To use natural language, ask a host to load
[spex-eval](../../.agents/skills/spex-eval/SKILL.md). The skill defaults to all
cases in all suites against HEAD on the current host. Narrow the scope with
natural language such as “Run Spex smoke on python-cli” or explicit filters.
Filters match by intersection.

| Scope | Runner command after `python3 eval/spex/run.py` |
| --- | --- |
| All suites and cases | `list` |
| All docs cases | `list --suite docs` |
| One case | `list --suite docs --case analyze-incident` |
| All smoke cases | `list --tag smoke` |

For current-host runs, add `--all` to prepare every listed case into one
sandbox in parallel against the same pinned commit. The JSON reports a
`prepared` handoff per case and per-case `errors`; with `--init`, the payload
also reports `queue_init`. Each
`prepared` and `errors` entry carries the case ID as both `id` and `case`;
`list` reports `id`. Retry individual failures with
`prepare --case CASE --sandbox PATH`.

`queue_init.status` is `initialized` for a new queue, `existing` when
`queue.json` is already present, and `skipped` with `reason`
`prepare_errors` (a case failed) or `batch_mismatch` (the selected IDs differ
from `batch-index.json`) when the batch must be retried first. A retry with
`prepare --case` does not initialize the queue, so run `manual.py init` with
every selected ID afterward.

`prepare` already writes `_handoff/env-<suite>-<case>.sh` for every case and
returns it as `env_script`. Source that file in the trial session; never
rebuild the exports or write an env script by hand.

## Current-host trials

The runner defaults to a four-worker ceiling. Each worker runs a whole
trial through grading, with ordered turns and one session per trial. For
current-host trials, dispatch in parallel when the host can open
independent sessions and resume them across turns. Otherwise prepare a
new batch with `--jobs 1` and use serial manual handoffs when needed.
An existing sandbox retains the saved ceiling. Its coordinator can dispatch
fewer trials when the host supports less concurrency.

Pass `--jobs N` (1–4) to configure the limit for a new `prepare` batch
or for `run`, `judge`, or `calibrate`. The guarded queue enforces the
limit returned by `prepare`, and the runner enforces it in automatic
execution. Later `prepare --sandbox` calls inherit the first setting.

Reports record the configured mode and worker limit. Historical runs
without that setting display `unknown`. Performance summaries group
repeated samples by execution configuration, and comparisons report
configuration changes.

Host identifiers are lowercase labels such as `codex`, `qoder`, `cursor`,
`claude-code`, or `other`. Suites, acceptance checks, rubrics, and the
`prepare` → `collect` → `export-packet` → `import-grades` path are host
agnostic. The default skill flow is `list` → `prepare` → execute in the
current host → `collect` → semantic review → `summary`. Codex-only automation
remains under `run`, `judge`, and `calibrate`. Treat `list` / `prepare` /
`collect` / `export-packet` / `import-grades` / `summary` as the
**deterministic** pipeline (always invoke `eval/spex/run.py`); only the
trial Spex session and semantic judge scores are model-dependent. Hard
checks from `collect` take precedence over AI grades.

The runner does not open host sessions. The portable interface is:

1. `prepare` / `prepare --sandbox` / `prepare --all` JSON (`workspace`,
   `environment`, `env_script`, `next_input`, `trial`, `sandbox`).
2. Reply files under `<sandbox>/_handoff/<suite>-<case>-turnN.txt`.
3. `collect` / `export-packet` / `import-grades` / `summary`.

### Host adapter checklist

| Step | Any host |
| --- | --- |
| Isolate | One session (or equivalent) per trial; separate session for judge |
| Env | Source the `env_script` written by `prepare` (`_handoff/env-<suite>-<case>.sh`) or returned by `dispatch`; never rebuild the exports by hand. Verify the prepared cwd and pinned CLI before dispatch. Use `manual.py exec` for per-call setup in shells. Unset inherited `SPEX_TRACE_FILE` so CLI logs stay in the trial's `.spex/eval-logs`. |
| Skill | Use the pinned `skill` path from prepare; limit writes to `workspace` |
| Input | Dispatch each turn with `manual.py dispatch`, send its `next_input` exactly, and keep the same session for later turns |
| Output | Write the final reply under `_handoff/`; optional `--events` only if the host can emit a compatible Codex-style JSONL |
| Collect | `collect --session ID --reply <handoff-file> [--events …]` |

For guarded current-host batches, `prepare` publishes each handoff to
`batch-index.json`. Use `python3 eval/spex/manual.py --sandbox PATH` for
these commands.

| Command | Result |
| --- | --- |
| `init SUITE/CASE ...` | Initialize the queue from all selected and published cases; `prepare --all --init` does this in the same call |
| `dispatch SUITE/CASE --session ID` | Claim a pending slot and start the next turn in one call; the authoritative dispatch entry |
| `claim SUITE/CASE` | Low-level slot claim behind `dispatch`; it does not start a turn |
| `exec SUITE/CASE -- COMMAND ...` | Run a shell command with the prepared cwd and environment |
| `start SUITE/CASE TURN --session ID` | Low-level turn start behind `dispatch`: bind the session and timer, then return the exact input and reply path |
| `wait --any --timeout SECONDS` | Block until a running turn has a readable, nonblank UTF-8 reply; exit 1 on timeout |
| `advance` | Stop, collect, and export running turns with published replies |
| `stop SUITE/CASE TURN [--reply-file PATH]` | Finish the current timer and atomically publish a staged reply first when supplied |
| `collect SUITE/CASE TURN` | Collect the saved reply and timing sidecars, then return the next input |
| `complete SUITE/CASE` | Read the saved outcome after grade import and release the slot; `complete --all` closes out a batch |
| `fail SUITE/CASE --reason launch_failed\|exited\|timeout` | Record a host failure on a claimed, pending trial and release its slot while preserving collected evidence |
| `status --require-terminal` | Exit 1 until every queued case has a terminal verdict |

`dispatch` returns `case`, `turn`, `session`, `trial`, `workspace`, `skill`,
`env_script`, `reply`, and `next_input`. Dispatch a running case again to
start its next turn. Add `--turn N` to assert the expected next turn; a
mismatch fails without touching the queue. A failed dispatch also leaves the
queue unchanged: an invalid or conflicting session, an already-started turn,
a missing env script, or a full slot set (the error lists the occupying
`SUITE/CASE` IDs with `jobs=N`) all exit nonzero. `claim` and `start` remain
the low-level pair behind `dispatch`.

### Coordinator rules

The [spex-eval skill](../../.agents/skills/spex-eval/SKILL.md) holds the full
SOP. These rules prevent the recurring coordinator failures:

- Every command must be cwd-independent: prefix it with `cd <repo-root> && …`
  or use absolute paths. Never rely on the shell working directory inherited
  from an earlier call.
- Dispatch only through `manual.py dispatch`, one call per turn; never copy
  `_dispatch.py` or any other helper from a previous sandbox.
- Slot order is `advance → export-packet → judge → import-grades → complete
  → claim`. Slots are released only by `complete`, or by `fail` for a
  recorded host failure, so a collected but ungraded trial still holds its
  slot.
- Read the schema of an unfamiliar host MCP tool before calling it; do not
  guess argument names.

The guarded path collects each turn before dispatching the next one. Direct
`collect` and `collect_handoff.py` remain available for existing handoffs and
debugging. The batch stays partial if any selected preparation or trial is
unresolved.

Each collect reads the Spex command log since the previous turn's checkpoint
and saves workspace snapshots. Required checks report insufficient evidence if
the available observations cannot establish the required behavior.

Open an independent session in the returned `workspace` with the returned
environment and paste the exact `next_input`. Keep that same session for every
later turn of the trial. Use `--invocation native` only when the host has the
pinned skill registered for native `/spex` invocation. When the host cannot
create the session automatically, use the returned paths and `next_input` for
a manual handoff (`handoff` is `manual`).

Save the final reply under the sandbox `_handoff/` directory (not system
`/tmp`), then collect it using a stable session ID for that trial. Use the
same session for subsequent turns, and proceed only while collection returns a
next input.

```sh
python3 eval/spex/run.py collect "$trial" --session "$session" --reply "$reply"
```

For manual timing, run `eval/spex/host_turn_timer.py start` immediately
before sending a turn and `stop` after its final reply, with the same
`--sandbox`, `--suite`, `--case`, and `--turn` for both calls.
`collect_handoff.py` reads the resulting `.host-wall-clock.json` or the
legacy `.host-duration-ms` beside the reply. Direct `collect` accepts
`--host-started-at`, `--host-ended-at`, and `--host-duration-ms`.
Timing diagnostics compare the host window with the saved evidence for that turn.

A compatible Codex-style JSONL transcript supplied through `--events FILE`
adds host observations. Its reply must match the handoff for the transcript
to be used. Portable positive observations can be supplied through
`--events-format normalized`.

```sh
python3 eval/spex/run.py export-packet "$trial"
python3 eval/spex/run.py import-grades "$trial" --grades "$grades" \
  --host codex --model gpt-6.1-sol
python3 eval/spex/run.py summary "$sandbox"
```

After agents have written `_handoff/<suite>-<case>-turnN.txt` for a whole
sandbox, batch-collect and summarize with:

```sh
python3 eval/spex/collect_handoff.py "$sandbox"
```

`export-packet` writes `judge-packet.json` and `judge-prompt.txt` beside the
trial evidence and returns `prompt_bytes` plus a `judge_hint`. Open a
**separate** judge session, read **only** `judge-prompt.txt` (do not
re-summarize workspace evidence), then feed the grades JSON to
`import-grades`. Criteria that lack required artifacts, including missing
tool traces, are already marked insufficient and are not sent to the judge.
`import-grades --grades -` reads the same JSON from stdin.
`import-grades` reuses the same score and evidence-reference checks as the
automatic judge. `summary` writes `manifest.json`, `report.json`, and
`report.md` at the sandbox root and returns a `cleanup_hint`; delete the
timestamp directory manually when finished. Both reports list the trial and
judge Agent hosts and model IDs for each case. Use `import-grades --host`
and `--model` for the judge's identity. Missing identities appear as
`unknown`, and trials without a judge record show `ungraded`.
The **Score summary** has one row per trial with four columns:
`Case | Verdict | Score | Criteria`. The verdict cell shows the hard
verdict in parentheses when it differs from the final verdict. The score
cell states how many rubric criteria were graded, and the criteria cell
lists each criterion's score (`ungraded` when none was judged). An
asterisk beside full marks on a non-passing trial links the score
coverage to the verdict reason below the table. Hard failures take
precedence.

### Batch close-out

`prepare` records the whole batch in `batch-index.json`, so saved judge
grades can be imported and the slots released in two calls instead of one per
case. Judges write each verdict to `_handoff/grades-<suite>-<case>.json`.
`--grades-dir` defaults to `<sandbox>/_handoff` and resolves a relative path
against the sandbox.

```sh
python3 eval/spex/run.py import-grades --all --sandbox "$sandbox" \
  --grades-dir _handoff --host qoder --model gpt-6.1-sol
python3 eval/spex/manual.py --sandbox "$sandbox" complete --all
```

`import-grades --all` visits every key in `batch-index.json` order, imports
each saved grade, skips `already_graded` (judge output exists), `no_packet`
(no judge prompt), and `no_grades` (no grades file), and exits 1 when any case
fails. A `--judge-duration-ms` value applies to every import in batch mode.
`complete --all` completes each running case that holds a terminal verdict,
skips `not_graded` and `not_running`, releases the slots, and exits 1 on
per-case errors. Keep `import-grades TRIAL --grades FILE` and
`complete SUITE/CASE` as single-case fallbacks. The terminal gate remains
`manual.py --sandbox PATH status --require-terminal`.

**Execution diagnostics** reports observed issues under two headings.
**Observed issues** assigns each one a stable `I001…` id and lists its
case and trial scope, stage and kind, whether a retry recovered it, its
message, and links to the saved evidence. **Proposed improvements**
reuse the same ids, so `report.md`, `report.json`, and the
`--write-improvements` backlog (optional path; default
`eval/spex/IMPROVEMENTS.md`) all point at the same item. Issues are
derived from trial evidence and merged with adapter records kept under
`<sandbox>/_issues/`. Most ids in a normal batch are derived: a hard
`run_error` trial, every failed acceptance check (`check_failure`, P0),
non-trace evidence gaps (`evidence_gap`, P1), trace gaps (`trace_gap`,
P2), and unrecovered host, script, or judge issues (`script_exit`,
`host_error`, `judge_error`, `judge_attempt`,
`implausible_host_duration`, `command_failures`, `subagent_*`). Ids are
assigned after the merge, so they are positional within one summary run
and can shift when a rerun derives a different set. A successful retry
of the same helper operation in the same collected turn keeps the failed
exit visible but marks it recovered and excludes it from the proposed
improvements. The JSON report keeps verdicts and scores as separate
fields and includes the diagnostics under each trial.

Adapters record observations that are not visible in trial evidence,
such as host capacity refusals or session startup failures, with
`record-issue` before summarizing:

```sh
python3 eval/spex/run.py record-issue "$sandbox" --suite docs \
  --case analyze-incident --stage host --kind capacity \
  --message "host refused a new session" --trial docs/analyze-incident \
  --turn 2 --unrecovered
```

Each record is a JSON file under `<sandbox>/_issues/` named
`<time_ns>-<uuid>.json` with `suite`, `case_id`, `case`, `trial`,
`stage` (one of `prepare`, `host`, `collect`, `judge`, `script`,
`unknown`), `kind`, `message`, `turn`, and `recovered` (`true`, `false`,
or `null`). Records larger than 64 KiB are ignored when the summary
reads `_issues/`, and a symlinked `_issues/` directory is ignored too.
The summary reads every accepted record and merges it with observed
issues; use `--recovered` or `--unrecovered` only when you know whether
a retry fixed the condition.

`record-issue` enforces these constraints, so a rejected record fails the
command instead of being saved:

- `--suite`, `--case`, and `--kind` must match `[a-z0-9][a-z0-9_-]{0,63}`
  (lowercase letters, digits, `_`, and `-`, never leading with a separator).
- `--message` is stripped and must be 1-500 characters.
- `--turn`, when given, must be at least 1.
- `--trial` is optional (default `null`), must stay sandbox-relative with
  no `..`, and must not contain a `workspace` path part.

Host adapter notes for Cursor / Codex / pure manual live under
[`adapters/README.md`](adapters/README.md).

## Performance diagnostics

Each trial records timing and activity in `performance.json`. The batch
report's **Performance** table has five columns:
`Case | Host turns | Duration (s) | Source | Detail`. Duration sums
measured host turns when all are available; otherwise it uses the full
automatic trial duration when available or shows `unknown`, and the
source column records which one was used. The detail column links
`performance.json` and names any interrupted Spex steps. Repeated
comparable samples show coverage, median, and max by duration source and
configured execution.

The **Execution timeline** section shows the case boundaries, host turns,
Spex skill start and end markers, and recorded Spex CLI commands. It emits
one eight-column table per case under its own `### <suite>/<case>
(<trial>)` heading, after a single section header and intro paragraph:
`Event | Started | Ended | Logged | Duration (s) | Elapsed (s) | Exit | Argv`.
The Argv column joins the command's process arguments and truncates them
at 80 characters. Elapsed time starts at the first host dispatch and can
include waits between turns. A legacy debug log can supply a command's
log timestamp without establishing its wall-clock start or end. JSON
timeline entries also carry `is_spex_skill` and, for skill turns,
`skill_input`; token usage, subagent starts, and review rounds stay in
`performance.json`.

- For manual collection, pass `collect --host-duration-ms N` if the host
  measured elapsed time from sending input through receiving the final
  reply. Pass `import-grades --judge-duration-ms N` for separately measured
  judge time. Both accept non-negative integer milliseconds.
- Automatic runs record each host attempt, including partial traces on
  timeout. Preparation, collection, acceptance, and grading have separate
  measurements. The existing trial `duration_ms` covers the full automatic
  run, including grading.
- Spex debug anchors provide step and review timings. Fix and check spans
  can overlap. Existing runs can recover available debug anchors and
  verified manual handoff traces during summary.
- A host turn, a Spex review round, and a model request are different
  counters. Codex JSONL provides turn-level usage and tool activity.
  Request-level counts and separately attributed subagent usage are
  unknown with this trace format. Missing measurements do not affect grades.

## Automated Codex CLI

Use `run` only for explicit Codex CLI automation. It requires an authenticated
Codex CLI that supports named permissions profiles. The profile permits writes
to the trial repository, including its Git metadata and a trial-local
temporary directory. The runner supplies its Python environment and shell
temporary paths without login shell startup. Before a `run`, `judge`, or
`calibrate` batch, the runner probes a writable Codex state directory,
app-server startup, and authentication once, then reuses that home for trial
execution and judging. Override the state directory with
`SPEX_EVAL_CODEX_HOME` when needed. Classified startup failures such as
`state_dir_unwritable`, `app_server_init`, or `authentication` are reported
once for the batch. The acceptance harness uses the macOS sandbox to constrain
code written by the evaluated model, with system Git resolved through
`xcrun`.

```sh
python3 eval/spex/run.py run --tag smoke \
  --model gpt-6.1-sol --judge-model gpt-6.1-sol
```

`--timeout` bounds each turn and `--repeat` requests independent repetitions.
Set `SPEX_EVAL_JUDGE_MODEL` to supply a default judge. Specify the same judge
for both sides of a comparison.

## Calibrate, replay, and compare

Use the sandbox directory name as the run ID for saved evaluations.

```sh
python3 eval/spex/run.py calibrate --judge-model gpt-6.1-sol
python3 eval/spex/run.py judge RUN_ID --judge-model gpt-6.1-sol
python3 eval/spex/run.py compare BASELINE_ID CANDIDATE_ID \
  --judge-model gpt-6.1-sol
```

Calibrate against the frozen set before using results for decisions. The
calibration requires at least 90 percent agreement, no critical misses, and
no invalid citations. Use `--split development` while iterating on the judge.
Replay reads saved evidence and preserves the original grade. To compare
replayed grades, provide `--baseline-rejudge ID` and
`--candidate-rejudge ID` as appropriate.

Compare the same suites and cases while holding the host, fixture, and judge
configuration constant. Change the target model or Spex commit to measure
that difference. Use multiple repetitions to see whether it recurs.

## Read results and extend the suites

Generated evidence lives in the Git-ignored `eval/spex/runs/` timestamp
sandboxes. Inspect `suite/case/trial.json` for per-turn checks,
`turn-N.json` for referenced artifacts, and `judge.json` for semantic grades.
Batch outcomes are in the sandbox `report.md`. Comparison reports under
`runs/comparisons/` still use their own directories with Markdown and JSON for
pair alignment, sample counts, per-check changes, and evidence-linked
hypotheses when supported. Treat missing evidence and transport or judge
errors separately from observed workflow failures.

To add a suite, follow the manifests under `suites/python-cli/` and
`suites/docs/`. A case declares its fixture, ordered turns, checks, and
acceptance selector. Define semantic criteria in the suite's
`rubrics.json`, including each criterion's turn, required evidence,
threshold, and three anchored scores. Keep acceptance scripts and rubrics
outside the evaluated workspace. Include fixture and check regressions
before using a new case in a comparison.

### Extended batch import cases

The `batch-import` suite uses a standalone CSV-to-SQLite importer. It checks
checkpoint compatibility, transactional progress, CLI resume, and input
identity across four ordered Git commits.

- `apply-all` starts with four pending tasks.
- `apply-resume` starts with a real checkpoint compatibility commit and
  three pending tasks. The initial completion record and commit must survive.

List these cases with `python3 eval/spex/run.py list --suite batch-import`.
For Codex CLI automation, run both with the same target and judge:

```sh
python3 eval/spex/run.py run --suite batch-import \
  --model gpt-6.1-sol --judge-model gpt-6.1-sol
```

Use `--tag smoke` to select the short regression cases. For a formal
comparison, repeat the same extended cases three times per target and
hold the Spex ref and judge constant. The acceptance artifact records
individual milestone checks and failures. It executes Git snapshots with
in-memory SQLite in the runner's read-only acceptance sandbox.
