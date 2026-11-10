# Spex workflow evaluations

The runner evaluates Spex workflow boundaries, fixture behavior, and semantic
quality. Each trial starts from an independent Git fixture, installs Spex from
a pinned commit, and collects its own evidence. The judge works in a separate
tool-free session. A failed deterministic check takes precedence over an AI
score.

## Quick start

The default path evaluates Spex from the current host. Use macOS, Git, and
the project Python environment. Run commands from the repository root.

```sh
.venv/bin/python eval/spex/run.py list --tag smoke
.venv/bin/python eval/spex/run.py prepare --suite docs --case analyze-incident \
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
[spex-eval](../../.agents/skills/spex-eval/SKILL.md) and run a request such as
“Run Spex smoke on python-cli.” The repository keeps the skill in
`.agents/skills/spex-eval/`. For automatic discovery, install it through the
host's skill mechanism. A host can also read the file directly from this
checkout.

## Current-host trials

Host identifiers are lowercase labels such as `codex`, `qoder`, `cursor`,
`claude-code`, or `other`. Suites, acceptance checks, rubrics, and the
`prepare` → `collect` → `export-packet` → `import-grades` path are host
agnostic. The default skill flow is `list` → `prepare` → execute in the
current host → `collect` → semantic review → `summary`. Codex-only automation
remains under `run`, `judge`, and `calibrate`.

The runner does not open host sessions. The portable interface is:

1. `prepare` / `prepare --sandbox` JSON (`workspace`, `environment`,
   `next_input`, `trial`, `sandbox`).
2. Reply files under `<sandbox>/_handoff/<suite>-<case>-turnN.txt`.
3. `collect` / `export-packet` / `import-grades` / `summary`.

### Host adapter checklist

| Step | Any host |
| --- | --- |
| Isolate | One session (or equivalent) per trial; separate session for judge |
| Env | Apply `environment` from prepare (includes `PATH` with the eval runner's Python first) to tools/shell in that session |
| Skill | Use the pinned `skill` path from prepare; limit writes to `workspace` |
| Input | Send `next_input` exactly; keep the same session for later turns |
| Output | Write the final reply under `_handoff/`; optional `--events` only if the host can emit a compatible Codex-style JSONL |
| Collect | `collect --session ID --reply <handoff-file> [--events …]` |

Without `--events`, checks such as `post-action` may be
`insufficient_evidence`. `summary` classifies those as **evidence gaps**,
distinct from **observed fails**. For **manual** `collection`, those pure
trace gaps no longer force a hard trial verdict of
`insufficient_evidence` when every other check passed (acceptance
included); supply `--events` when you need hard proof of post-action.

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
.venv/bin/python eval/spex/run.py collect "$trial" --session "$session" --reply "$reply"
```

Use `--events FILE` only for a compatible Codex-style JSONL transcript whose
session ID and final reply agree with the collected turn. Without compatible
events, checks that require tool traces can report insufficient evidence.
Collection records deterministic checks only. After the trial finishes, export
the semantic evidence packet, grade it in a separate current-host session, then
import the JSON results. Workspaces stay on disk for inspection; the runner
does not delete the sandbox.

```sh
.venv/bin/python eval/spex/run.py export-packet "$trial"
.venv/bin/python eval/spex/run.py import-grades "$trial" --grades "$grades" \
  --model gpt-6.1-sol
.venv/bin/python eval/spex/run.py summary "$sandbox"
```

`export-packet` writes `judge-packet.json` and `judge-prompt.txt` beside the
trial evidence. Criteria that lack required artifacts, including missing tool
traces, are already marked insufficient and are not sent to the judge.
`import-grades` reuses the same score and evidence-reference checks as the
automatic judge. `summary` writes `manifest.json`, `report.json`, and
`report.md` at the sandbox root and returns a `cleanup_hint`; delete the
timestamp directory manually when finished.

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
.venv/bin/python eval/spex/run.py run --tag smoke \
  --model gpt-6.1-sol --judge-model gpt-6.1-sol
```

`--timeout` bounds each turn and `--repeat` requests independent repetitions.
Set `SPEX_EVAL_JUDGE_MODEL` to supply a default judge. Specify the same judge
for both sides of a comparison.

## Calibrate, replay, and compare

```sh
.venv/bin/python eval/spex/run.py calibrate --judge-model gpt-6.1-sol
.venv/bin/python eval/spex/run.py judge RUN_ID --judge-model gpt-6.1-sol
.venv/bin/python eval/spex/run.py compare BASELINE_ID CANDIDATE_ID \
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
