# spex apply

Apply a specification to implement code step by step.

## Usage

```text
/spex apply [spec_name | --all]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Resolve Spec

If `$spec_name` is `--all`:

- Run `$spex_skill_dir/scripts/spex list --json --must-undone`
  to get all specs with undone tasks.
- Parse the output as a JSON array of objects, each containing
  `spec_name` and `spec_path`.
- For each entry, set `$spec_name` and `$spec_path` and execute
  Phases 2 through 9 (Phase 9 runs per spec when that spec's
  tasks are all done).
- After every spec has finished, **STOP**.

Otherwise, run:

```bash
$spex_skill_dir/scripts/spex list --json --must-undone "$spec_name"
```

Read the command output and parse it as a JSON array:

- If the array contains a single element, set `$spec_name` to its
  `spec_name` and `$spec_path` to its `spec_path`.
- If the array contains multiple elements, present a numbered list of
  `spec_name` values to the user and ask them to choose. Set
  `$spec_name` and `$spec_path` from the selected entry.
- If the script exits with an error, report the error and stop.

### Phase 2: Validate Branch

Run:

```bash
$spex_skill_dir/scripts/spex apply-helper precheck --name $spec_name
```

If the script exits with an error (non-zero), the error message is already
printed to stderr. Stop execution. On success, continue to the next phase.

### Phase 3: Build Prompt / Resume Gate

Run:

```bash
$spex_skill_dir/scripts/spex prompt apply-one-task --json --name $spec_name
```

Parse the JSON output from stdout:

- If the response contains `"all_done": true`, all tasks for this
  spec are completed — proceed directly to **Phase 9** (do not
  go through Phase 8). In `--all` mode, after Phase 9 continue
  with the next spec from Phase 2.
- If the command exits with a non-zero exit code, a real error
  occurred — report the stderr message and stop.
- Otherwise, save:
  - `$prompt` ← `"prompt"`
  - `$current_task_id` ← `"task_id"`
  - `$resume_phase` ← `"resume_phase"` (`implement` or `review`)
  - `$commit_title` ← `"commit_title"` (may be empty)

A step is incomplete until `completed_at` is set. If
`commit_title` is already set and `completed_at` is empty,
`resume_phase` is `review` (skip implement/commit).

**Route:**

- If `$resume_phase` is `review`: set
  `$commit_sha=$(git rev-parse --short HEAD)`, skip Phases 4–5,
  continue with Phase 6 in the main context.
- If `$resume_phase` is `implement`: launch a sub-agent for
  Phases 4–5 only (implement + first commit). Instruct it to
  follow Phases 4–5 of this command exactly. Pass `$prompt` as
  the Phase 4 implementation guide, plus `$current_task_id` and
  `$spec_name`. The implementation prompt must not create the
  commit by itself — the sub-agent runs Phase 5 (`apply-commit`)
  after implementation. On failure, report and retry **once**;
  if it still fails, stop. After it completes, continue with
  Phase 6 in the main context.

### Phase 4: Execute Task

Using `$prompt` as the implementation guide, implement the current
task. Follow the instructions in the rendered prompt precisely —
it contains the specification, completed steps context, the task
description, and implementation guidelines.

Deliver production code and its tests together. If the implementation
produces no file changes, report the issue and stop.

Do **not** create a git commit here — Phase 5 handles the commit.

### Phase 5: Commit (record commit_title only)

Run:

```bash
$spex_skill_dir/scripts/spex prompt apply-commit --name $spec_name
```

Save the output to `$commit_prompt`. Using `$commit_prompt` as the
guide, stage the relevant file changes and create a git commit:

- Do NOT stage any files under `$spex_root/`.
- Create the commit using a heredoc: `git commit -F- <<-EOF ... EOF`.
- If the commit fails (e.g., pre-commit hook), fix the issues and
  retry **once**; if it still fails, stop and report.

After the commit succeeds, run:

```bash
git log -1 --pretty="%h: %s"
```

Save the output to `$commit_title`. Also save the short SHA:

```bash
git rev-parse --short HEAD
```

Save to `$commit_sha`.

**Persist commit_title now — do NOT set `completed_at` yet**
(review/fix may still be pending; this enables interrupt resume):

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name edit \
  --id "$current_task_id" --commit-title "$commit_title"
```

### Phase 6: Review Loop

Load and follow `references/apply-review-loop.md` exactly.

### Phase 7: Mark Task Complete

Only after the review/fix loop finishes successfully. Refresh
`$commit_title` if needed, then set **`completed_at`** (the step
is not done until this runs):

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name edit \
  --id "$current_task_id" --completed-at now \
  --commit-title "$commit_title"
```

If the command fails, report the error and stop.

### Phase 8: Next Task

Go back to Phase 3 for the next undone task. Each iteration uses a
fresh sub-agent for Phases 4–5 when `resume_phase` is `implement`.

When Phase 3 reports `"all_done": true`, Phase 3 routes to Phase 9
(do not loop further for this spec).

### Phase 9: Post Action

Run for the **current** `$spec_name` (once per completed spec,
including each entry in `--all` mode):

```bash
$spex_skill_dir/scripts/spex apply-helper post-action --name $spec_name
```

Display the output to the user.

- In `--all` mode: continue with the next spec from Phase 2, or
  **STOP** if none remain.
- Otherwise: **STOP.** Do NOT start implementing additional steps
  or modifying project files beyond what was already committed.
