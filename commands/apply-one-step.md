# spex apply-one-step

Apply a single step from a specification's todo list.

## Usage

```text
/spex apply-one-step [topic_name]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Resolve Topic

Run:

```bash
$spex_skill_dir/scripts/spex get-topic --json --must-undone "$topic_name"
```

Read the command output and parse it as a JSON array:

- If the array contains a single element, set `$topic_name` to its
  `topic_name` and `$topic_path` to its `topic_path`.
- If the array contains multiple elements, present a numbered list of
  `topic_name` values to the user and ask them to choose. Set
  `$topic_name` and `$topic_path` from the selected entry.
- If the script exits with an error, report the error and stop.

### Phase 2: Validate Branch

Run:

```bash
$spex_skill_dir/scripts/spex apply-helper precheck --topic $topic_name
```

If the script exits with an error (non-zero), the error message is already
printed to stderr. Stop execution. On success, continue to the next phase.

### Phase 3: Build Prompt

Run:

```bash
$spex_skill_dir/scripts/spex prompt apply-one-task --json --topic $topic_name
```

Parse the JSON output from stdout:

- If the response contains `"all_done": true`, all tasks are
  completed — report completion to the user and stop.
- If the command exits with a non-zero exit code, a real error
  occurred — report the stderr message and stop.
- Otherwise, save `$prompt` from the `"prompt"` field and
  `$current_task_id` from the `"task_id"` field.

### Phase 4: Execute Task

Launch a subagent with `$prompt` to implement the current task.
Ensure the subagent's working directory is set to the topic's
workdir (read from `meta.json` via `$topic_path/meta.json` or
`spex get-topic` output).
If the subagent fails or produces no file changes, report the error
to the user and retry.

### Phase 5: Commit

Load the commit prompt:

```bash
$spex_skill_dir/scripts/spex prompt apply-commit --topic $topic_name
```

The prompt output will contain explicit instructions for creating the git
commit. Read the output and follow it exactly:

- Stage the relevant file changes (do NOT stage any files under
  `$spex_root/`).
- Create the commit using a heredoc: `git commit -F- <<-EOF ... EOF`.
- If the commit fails (e.g., pre-commit hook), fix the issues and retry.

After a successful commit, run:

```bash
git log -1 --pretty="%h: %s"
```

Save the output to `$commit_title`.

### Phase 6: Mark Task Complete

Run:

```bash
$spex_skill_dir/scripts/spex todo-helper --topic $topic_name edit --id "$current_task_id" --completed_at now --commit_title "$commit_title"
```

If the command fails, report the error and stop.

### Phase 7: STOP — One Step Only

Display a summary to the user:

- The completed step name and `$commit_title`
- The number of remaining undone tasks in `todo.json`

> **This command implements exactly one step. Stop here.**
> Do NOT loop back to Phase 3 or implement additional steps.
> The user must invoke `/spex apply-one-step` again to continue.

### Phase 8: Post Action

Run:

```bash
$spex_skill_dir/scripts/spex apply-helper post-action --topic $topic_name
```

Display the output to the user.
