# spex apply-one-step

Apply a single step from a specification's todo list.

## Usage

```text
/spex apply-one-step [spec_name]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Resolve Spec

Run:

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

- If the response contains `"all_done": true`, all tasks are
  completed — report completion to the user, then run post-action
  (covers the case where the last step finished but Phase 8 was
  interrupted) and **STOP**:

  ```bash
  $spex_skill_dir/scripts/spex apply-helper post-action --name $spec_name
  ```

  Display the output to the user. Do not implement further steps.
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

- If `$resume_phase` is `review`: skip Phases 4–5 and continue with
  Phase 6. Do not set `$commit_sha` from `HEAD` here — Phase 6
  **6-entry** resolves it (prefer the review file's `commit_sha`).
- If `$resume_phase` is `implement`: continue with Phase 4.

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

If the review loop **STOP**s (e.g. open majors remain at round 3),
end this invocation without Phase 7 or Phase 8. The step stays
incomplete (`completed_at` unset) so a later `/spex apply-one-step`
can resume via Phase 3 → Phase 6.

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

### Phase 8: Summary and Conditional Post Action

Count remaining undone tasks in `$spec_path/todo.json` (items
with empty/`null` `completed_at`). Save as `$remaining`.

Display a summary:

- The completed step name and `$commit_title`
- `$remaining` (number of undone tasks left)

**Only if `$remaining` is 0**, run post-action (spec fully done):

```bash
$spex_skill_dir/scripts/spex apply-helper post-action --name $spec_name
```

Display the output to the user. If `$remaining` > 0, skip
`post-action` — unfinished work remains.

**This command implements exactly one step. STOP here.**
Do NOT loop back to Phase 3 or implement additional steps.
The user must invoke `/spex apply-one-step` again to continue.
