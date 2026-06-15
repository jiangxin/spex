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

- Run `$spex_skill_dir/scripts/spex list --json --all-projects --must-undone`
  to get all specs with undone tasks.
- Parse the output as a JSON array of objects, each containing
  `spec_name` and `spec_path`.
- For each entry, set `$spec_name` and `$spec_path` and execute
  Phases 2 through 7.
- After completing all specs, proceed to Phase 8.

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
  completed — proceed to Phase 7.
- If the command exits with a non-zero exit code, a real error
  occurred — report the stderr message and stop.
- Otherwise, save `$prompt` from the `"prompt"` field and
  `$current_task_id` from the `"task_id"` field.

**Sub-agent boundary.** Launch a sub-agent to execute Phases 4
through 6. The sub-agent receives `$prompt`, `$current_task_id`,
and `$spec_name` as context. If the sub-agent fails, report
the error to the user and retry. After it completes, continue
with Phase 7 in the main context.

### Phase 4: Execute Task

Using `$prompt` as the implementation guide, implement the current
task. Follow the instructions in the rendered prompt precisely —
it contains the specification, completed steps context, the task
description, and implementation guidelines.

If the implementation produces no file changes, report the issue
and stop.

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

Save the output to `$commit_title`.

### Phase 6: Mark Task Complete

Run:

```bash
$spex_skill_dir/scripts/spex todo-helper --name $spec_name edit \
  --id "$current_task_id" --completed_at now \
  --commit_title "$commit_title"
```

If the command fails, report the error and stop.

### Phase 7: Loop

Go back to Phase 3. Each iteration launches a fresh sub-agent,
keeping token usage independent between steps.

Stop looping when Phase 3 reports `"all_done": true`.

If running in `--all` mode (Phase 1), after completing all steps
for the current spec, move to the next spec and repeat from
Phase 2.

### Phase 8: Post Action

Run:

```bash
$spex_skill_dir/scripts/spex apply-helper post-action --name $spec_name
```

Display the output to the user.

**STOP.** All specs and steps in this run are complete. Do NOT start
implementing additional steps or modifying project files beyond what
was already committed.
