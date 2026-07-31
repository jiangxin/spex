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
  Phases 2 through 8.
- After completing all specs, proceed to Phase 9.

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

- If the response contains `"all_done": true`, all tasks are
  completed — proceed to Phase 8.
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
  Phases 4–5 only (implement + first commit). Pass `$prompt`,
  `$current_task_id`, and `$spec_name`. On failure, report and
  retry. After it completes, continue with Phase 6 in the main
  context.

### Phase 4: Execute Task

Using `$prompt` as the implementation guide, implement the current
task. Follow the instructions in the rendered prompt precisely —
it contains the specification, completed steps context, the task
description, and implementation guidelines.

Deliver production code and its tests together. If the implementation
produces no file changes, report the issue and stop.

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
  retry.

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

The main agent orchestrates this phase. Launch a fresh **review
sub-agent** and (when needed) a fresh **fix sub-agent** each
round. Maximum **3** review rounds.

**Orchestration rules (required):**

- Run each `review-helper` / `prompt` command as its **own** shell
  invocation. Do not chain init + prompt + python one-liners.
- Parse JSON from **stdout** yourself (tool output). Status/info
  lines on stderr (e.g. template sync) must be ignored.
- Shell variables such as `$commit_sha` are not Python names — never
  reference them inside `python3 -c` unless you expand them in the
  shell string first.

#### 6-entry. Resume / continue gate

Ensure `$commit_sha` is set (`git rev-parse --short HEAD` if
needed). Then:

```bash
$spex_skill_dir/scripts/spex review-helper --name $spec_name \
  status --step "$current_task_id" --json
```

- If `"needs_fix": true`: open findings remain — go to **6c**
  (fix loop). Do not start a new review first.
- Otherwise: go to **6a** (start or continue review).

#### 6a. Review sub-agent

Do **not** run `review-helper init`. The review file is created
lazily on the first `append`. If the review finds nothing, do not
create any `review-step-*.json` file.

Run (alone — do not pipe through ad-hoc scripts):

```bash
$spex_skill_dir/scripts/spex prompt apply-review --json \
  --name $spec_name --commit "$commit_sha"
```

Parse the JSON object from stdout. Save `$review_prompt` from the
`"prompt"` field (and optionally `"review_round"` /
`"review_file"`). Pass `$review_prompt` directly to a **review
sub-agent** as its instructions — do not rewrite it via shell
helpers. The review sub-agent must only record findings via
`review-helper append` (with `--commit`) — it must not modify
source code, and must not call `init`.

#### 6b. Check status (after a review pass)

Run:

```bash
$spex_skill_dir/scripts/spex review-helper --name $spec_name \
  status --step "$current_task_id" --json
```

Parse the JSON. Decision table (do not skip steps):

1. If `"needs_fix": false` (no open findings — including when no
   review file was created because the review found nothing):
   refresh `$commit_title` with `git log -1 --pretty="%h: %s"` and
   proceed to Phase 7.
2. If `"open_major"` > 0 and `"round"` >= 3: stop the loop, report
   remaining open major findings, and stop (do not mark the task
   complete).
3. If `"open_major"` == 0 and `"round"` >= 3: refresh
   `$commit_title` and proceed to Phase 7 (remaining open minors
   may stay unfinished).
4. **Otherwise** (`needs_fix` is true and round < 3): you **MUST**
   continue to 6c and launch the fix loop. Never proceed to
   Phase 7 while open findings remain in rounds 1–2 — this includes
   minor-only reviews. A review file always exists when
   `needs_fix` is true.

#### 6c. Fix loop — one finding at a time

Only enter this phase when 6b reported `needs_fix: true` (a
review file already exists). Fix findings **serially**. Never
batch-fix or batch-mark multiple findings in one sub-agent pass
(that produces identical `completed_at` timestamps). **Amend after
every single finding.**

**6c-i. Pick next open finding**

```bash
$spex_skill_dir/scripts/spex review-helper --name $spec_name \
  next --step "$current_task_id"
```

Parse JSON from stdout:

- If `"id"` is `null` / empty: all findings for this round are
  marked complete — go to **6c-iii** (bump-round → re-review).
- Otherwise set `$finding_id` from `"id"` and continue to 6c-ii.

**6c-ii. Fix + amend one finding**

```bash
$spex_skill_dir/scripts/spex prompt apply-fix --json \
  --name $spec_name --commit "$commit_sha" \
  --finding-id "$finding_id"
```

Parse `"prompt"` into `$fix_prompt`. Launch a **fresh fix
sub-agent** with `$fix_prompt`. That sub-agent must:

- Fix **only** `$finding_id`
- Call `review-helper edit --id $finding_id --completed-at now`
  after that single fix (not before, not for other ids)
- **Amend immediately** after marking that finding complete
- **Not** mark other findings complete

Amend constraints:

- `HEAD` must still be `$commit_sha` / the step commit under review.
- The commit must not have been pushed to a remote.
- Do not amend someone else's commit.
- Do NOT stage any files under `$spex_root/`.

After the fix sub-agent returns:

1. Verify `$finding_id` has a non-empty `completed_at`. If not,
   relaunch once; if it still fails, stop and report.
2. Refresh the SHA after this amend:

```bash
git rev-parse --short HEAD
```

   Save to `$commit_sha` (required — the next finding amends this
   new HEAD).

3. Go back to **6c-i** for the next open finding.

**6c-iii. Bump round and re-review**

When `next` reports no open findings, bump round and sync
`commit_sha` (findings preserved):

```bash
$spex_skill_dir/scripts/spex review-helper --name $spec_name \
  bump-round --step "$current_task_id" --commit "$commit_sha"
```

Confirm stdout JSON shows the new `round` and `commit_sha`. Then
go back to **6a** (fresh review sub-agent on the latest amended
commit).

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

### Phase 8: Loop

Go back to Phase 3. Each iteration uses a fresh sub-agent for
Phases 4–5 when `resume_phase` is `implement`.

Stop looping when Phase 3 reports `"all_done": true`.

If running in `--all` mode (Phase 1), after completing all steps
for the current spec, move to the next spec and repeat from
Phase 2.

### Phase 9: Post Action

Run:

```bash
$spex_skill_dir/scripts/spex apply-helper post-action --name $spec_name
```

Display the output to the user.

**STOP.** All specs and steps in this run are complete. Do NOT start
implementing additional steps or modifying project files beyond what
was already committed.
