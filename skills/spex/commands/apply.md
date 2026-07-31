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

### Phase 3: Build Prompt

Run:

```bash
$spex_skill_dir/scripts/spex prompt apply-one-task --json --name $spec_name
```

Parse the JSON output from stdout:

- If the response contains `"all_done": true`, all tasks are
  completed — proceed to Phase 8.
- If the command exits with a non-zero exit code, a real error
  occurred — report the stderr message and stop.
- Otherwise, save `$prompt` from the `"prompt"` field and
  `$current_task_id` from the `"task_id"` field.

**Sub-agent boundary.** Launch a sub-agent to execute Phases 4
through 5 only (implement + first commit). The sub-agent receives
`$prompt`, `$current_task_id`, and `$spec_name` as context. If the
sub-agent fails, report the error to the user and retry. After it
completes, continue with Phase 6 in the main context.

### Phase 4: Execute Task

Using `$prompt` as the implementation guide, implement the current
task. Follow the instructions in the rendered prompt precisely —
it contains the specification, completed steps context, the task
description, and implementation guidelines.

Deliver production code and its tests together. If the implementation
produces no file changes, report the issue and stop.

### Phase 5: Commit

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

#### 6a. Initialize review file (first round only)

Before the first review of this step, run:

```bash
$spex_skill_dir/scripts/spex review-helper --name $spec_name \
  init --step "$current_task_id" --commit "$commit_sha"
```

Stdout is JSON (`review_file`, `step_id`, `commit_sha`, `round`).
Confirm success (exit code 0), then continue.

#### 6b. Review sub-agent

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
`review-helper` — it must not modify source code.

#### 6c. Check status

Run:

```bash
$spex_skill_dir/scripts/spex review-helper --name $spec_name \
  status --step "$current_task_id" --json
```

Parse the JSON:

- If `"done": true` (no open major findings), refresh `$commit_title`
  with `git log -1 --pretty="%h: %s"` and proceed to Phase 7.
- If `"open_major"` > 0 and `"round"` >= 3, stop the loop, report
  the remaining open major findings to the user, and stop (do not
  mark the task complete).
- Otherwise continue to 6d.

#### 6d. Fix sub-agent (amend)

Run (alone — do not pipe through ad-hoc scripts):

```bash
$spex_skill_dir/scripts/spex prompt apply-fix --json \
  --name $spec_name --commit "$commit_sha"
```

Parse the JSON object from stdout. Save `$fix_prompt` from the
`"prompt"` field. Pass it directly to a **fix sub-agent** as
its instructions.

Amend constraints (the fix sub-agent must enforce these):

- `HEAD` must still be the commit under review.
- The commit must not have been pushed to a remote.
- Do not amend someone else's commit.
- Do NOT stage any files under `$spex_root/`.
- Use `git commit --amend` to fold fixes into the original commit.
- Mark each fixed finding complete with
  `review-helper edit --completed-at now`.

If amend is unsafe (already pushed / wrong HEAD), report the error
and stop.

After the fix sub-agent succeeds:

```bash
git rev-parse --short HEAD
```

Update `$commit_sha`. Then bump the review round:

```bash
$spex_skill_dir/scripts/spex review-helper --name $spec_name \
  bump-round --step "$current_task_id"
```

Go back to **6b** (fresh review sub-agent).

### Phase 7: Mark Task Complete

Run:

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name edit \
  --id "$current_task_id" --completed-at now \
  --commit-title "$commit_title"
```

If the command fails, report the error and stop.

### Phase 8: Loop

Go back to Phase 3. Each iteration launches a fresh sub-agent for
Phases 4–5, keeping token usage independent between steps.

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
