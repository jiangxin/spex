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

The first `prepare` or `run` creates a sandbox at
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
`prepared` handoff and an `env_script` path per case plus per-case `errors`.
Retry individual failures with `prepare --case CASE --sandbox PATH`.

## Current-host trials

The runner defaults to a four-worker ceiling. Each worker runs a whole
trial through grading, with ordered turns and one session per trial. For
current-host trials, dispatch in parallel when the host can open
independent sessions and resume them across turns. Otherwise prepare a
new batch with `--jobs 1` and use serial manual handoffs when needed.
An existing sandbox retains the saved ceiling. Its coordinator can claim
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
| Env | Verify the prepared cwd, environment, and pinned CLI before dispatch. Use `manual.py exec` for per-call setup in shells. Unset inherited `SPEX_TRACE_FILE` so CLI logs stay in the trial's `.spex/eval-logs`. |
| Skill | Use the pinned `skill` path from prepare; limit writes to `workspace` |
| Input | Send `next_input` exactly; keep the same session for later turns |
| Output | Write the final reply under `_handoff/`; optional `--events` only if the host can emit a compatible Codex-style JSONL |
| Collect | `collect --session ID --reply <handoff-file> [--events …]` |

For guarded current-host batches, `prepare` publishes each handoff to
`batch-index.json`. Use `python3 eval/spex/manual.py --sandbox PATH` for
these commands.

| Command | Result |
| --- | --- |
| `init SUITE/CASE ...` | Initialize the queue from all selected and published cases |
| `claim SUITE/CASE` | Reserve a trial slot through grading |
| `exec SUITE/CASE -- COMMAND ...` | Run a shell command with the prepared cwd and environment |
| `start SUITE/CASE TURN --session ID` | Bind the session and timer, then return the exact input and reply path |
| `wait --any --timeout SECONDS` | Block until a running turn has a readable, nonblank UTF-8 reply; exit 1 on timeout |
| `advance` | Stop, collect, and export running turns with published replies |
| `stop SUITE/CASE TURN [--reply-file PATH]` | Finish the current timer and atomically publish a staged reply first when supplied |
| `collect SUITE/CASE TURN` | Collect the saved reply and timing sidecars, then return the next input |
| `complete SUITE/CASE` | Read the saved outcome after grade import and release the slot |
| `fail SUITE/CASE --reason launch_failed\|exited\|timeout` | Record a host failure on a claimed, pending trial and release its slot while preserving collected evidence |
| `status --require-terminal` | Exit 1 until every queued case has a terminal verdict |

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
The **Score summary** shows one verdict per trial, with the hard verdict
in parentheses when it differs. Scores show how many rubric criteria
were graded. An asterisk beside full marks on a non-passing trial links
the score coverage to the verdict reason. Hard failures take precedence.

**Execution diagnostics** links observed Spex helper exits, implausible
host timing, and judge failures to their saved evidence. A successful
retry of the same helper operation in the same collected turn keeps the
failed exit visible but excludes it from **Spex skill improvements**.
The JSON report keeps the verdicts and scores as separate fields and
includes the diagnostics under each trial. Pass `--write-improvements` (optional path;
default `eval/spex/IMPROVEMENTS.md`) to also write a backlog markdown
file from the same items.

Host adapter notes for Cursor / Codex / pure manual live under
[`adapters/README.md`](adapters/README.md).

## Performance diagnostics

Each trial records timing and activity in `performance.json`. The batch
report links to the details and summarizes case duration, the slowest Spex
step, full and delta reviews, observed subagent starts, and parent-session
token usage. Case duration sums measured host turns when all are available.
Otherwise it uses the full automatic trial duration when available or shows
`unknown`. JSON reports include the selected duration in milliseconds and
seconds and its source. Repeated comparable samples show coverage, median,
and max by duration source and configured execution.

The execution timeline shows the case boundaries, host turns and recorded
Spex CLI commands with their available timestamps, durations and exit codes.
Elapsed time starts at the first host dispatch and can include waits between
turns. A legacy debug log can supply a command's log timestamp without
establishing its wall-clock start or end.

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
