# Spex workflow evaluations

The runner evaluates Spex workflow boundaries, fixture behavior, and semantic
quality. Each trial starts from an independent Git fixture, installs Spex from
a pinned commit, and collects its own evidence. The judge works in a separate
tool-free session. A failed deterministic check takes precedence over an AI
score.

## Quick start

Use macOS, Git, the project Python environment, and an authenticated Codex
CLI. The acceptance harness uses the macOS sandbox to constrain code written
by the evaluated model, with system Git resolved through `xcrun`. The
automatic path requires a Codex CLI that supports named permissions profiles.
The profile permits writes to the trial repository, including its Git
metadata and a trial-local temporary directory. The runner supplies its
Python environment and shell temporary paths without login shell startup.
Before a `run`, `judge`, or `calibrate` batch, the runner probes a writable
Codex state directory, app-server startup, and authentication once, then
reuses that home for trial execution and judging. Override the state
directory with `SPEX_EVAL_CODEX_HOME` when needed. Classified startup failures
such as `state_dir_unwritable`, `app_server_init`, or `authentication` are
reported once for the batch. Run these examples from the repository root and
substitute model IDs available to your account.

```sh
.venv/bin/python eval/spex/run.py list --tag smoke
.venv/bin/python eval/spex/run.py run --tag smoke \
  --model gpt-6.1-sol --judge-model gpt-6.1-sol
```

Filter with `--suite python-cli`, `--suite docs`, or `--case CASE`. Use
`--spex-ref REF` to pin another Git revision. `--timeout` bounds each turn
and `--repeat` requests independent repetitions. Set `SPEX_EVAL_JUDGE_MODEL`
to supply a default judge. Specify the same judge for both sides of a
comparison.

To use natural language, ask a host to load
[spex-eval](../../.skills/spex-eval/SKILL.md) and run a request such as
“Run Spex smoke on python-cli using gpt-6.1-sol for execution and judging.”
The repository keeps the skill in `.skills/`. For automatic discovery,
install it through the host's skill mechanism. A host can also read the
file directly from this checkout.

## Current-host trials

Prepare one trial for the host that will execute Spex. Host identifiers are
lowercase labels such as `codex`, `qoder`, `cursor`, `claude-code`, or
`other`. Omit `--model` or `--host-version` when they are unknown; the runner
records `unknown`.

```sh
.venv/bin/python eval/spex/run.py prepare --suite docs --case analyze-incident \
  --host qoder
```

Open an independent session in the returned `workspace` with the returned
environment and paste the exact `next_input`. Keep that same session for every
later turn of the trial. Ensure the host uses the pinned Spex skill path and
limits writes to that workspace. Use `--invocation native` only when the host
has the pinned skill registered for native `/spex` invocation. For a GUI host,
apply the same environment to the session that launches tools. When the host
cannot create the session automatically, use the returned paths and
`next_input` for a manual handoff (`handoff` is `manual`).

Save the final reply to a text file outside the workspace, then collect it
using a stable session ID for that trial. Use the same session for subsequent
turns, and proceed only while collection returns a next input.

```sh
.venv/bin/python eval/spex/run.py collect "$trial" --session "$session" --reply "$reply"
```

Use `--events FILE` only for a compatible Codex-style JSONL transcript whose
session ID and final reply agree with the collected turn. Without compatible
events, checks that require tool traces can report insufficient evidence.
Collection records deterministic checks only. After the trial finishes, export
the semantic evidence packet, grade it in a separate current-host session, then
import the JSON results. The prepared temporary workspace remains available
after collection for inspection. Remove it when finished.

```sh
.venv/bin/python eval/spex/run.py export-packet "$trial"
.venv/bin/python eval/spex/run.py import-grades "$trial" --grades "$grades" \
  --model gpt-6.1-sol
```

`export-packet` writes `judge-packet.json` and `judge-prompt.txt` beside the
trial evidence. Criteria that lack required artifacts, including missing tool
traces, are already marked insufficient and are not sent to the judge.
`import-grades` reuses the same score and evidence-reference checks as the
automatic judge.

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

Generated evidence lives in the Git-ignored `eval/spex/runs/`. A run ID is
the basename of its run directory. Inspect `trial.json` for per-turn checks,
`turn-N.json` for referenced artifacts, and `judge.json` for semantic grades.
Reports under `runs/comparisons/` include Markdown and JSON with pair
alignment, sample counts, per-check changes, and evidence-linked hypotheses
when supported. Treat missing evidence and transport or judge errors
separately from observed workflow failures.

To add a suite, follow the manifests under `suites/python-cli/` and
`suites/docs/`. A case declares its fixture, ordered turns, checks, and
acceptance selector. Define semantic criteria in the suite's
`rubrics.json`, including each criterion's turn, required evidence,
threshold, and three anchored scores. Keep acceptance scripts and rubrics
outside the evaluated workspace. Include fixture and check regressions
before using a new case in a comparison.
