# spex apply

Apply a specification to implement code step by step.

## Usage

```text
/spex apply [topic_name | --all]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Resolve Topic

If `$topic_name` is `--all`:

- Run `$spex_skill_dir/scripts/spex get-topic --json --all` to get all
  topics with undone tasks.
- Parse the output as a JSON array of objects, each containing
  `topic_name` and `topic_path`.
- For each entry, set `$topic_name` and `$topic_path` and execute
  Phases 2 through 6.
- After completing all topics, stop.

Otherwise, run:

```bash
$spex_skill_dir/scripts/spex get-topic --json "$topic_name"
```

Read the command output and parse it as a JSON array:

- If the array contains a single element, set `$topic_name` to its
  `topic_name` and `$topic_path` to its `topic_path`.
- If the array contains multiple elements, present a numbered list of
  `topic_name` values to the user and ask them to choose. Set
  `$topic_name` and `$topic_path` from the selected entry.
- If the script exits with an error, report the error and stop.

### Phase 2: Build Prompt

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
  `$next_task_id` from the `"task_id"` field.

### Phase 3: Execute Task

Launch a subagent with `$prompt` to implement the current task.
If the subagent fails or produces no file changes, report the error
to the user and retry.

### Phase 4: Commit

Load the commit prompt:

```bash
$spex_skill_dir/scripts/spex prompt apply-commit --topic $topic_name
```

Follow the output instructions to create a git commit. If the commit
fails (e.g., pre-commit hook), fix the issues and retry.

After a successful commit, run:

```bash
git log -1 --pretty="%h: %s"
```

Save the output to `$commit_title`.

### Phase 5: Mark Task Complete

Run:

```bash
$spex_skill_dir/scripts/spex todo mark-done "$next_task_id" "$commit_title" $topic_path/todo.json
```

If the command fails, report the error and stop.

### Phase 6: Loop

Go back to Phase 2. Do **not** stop while `todo.json` still has undone
tasks.
