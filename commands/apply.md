# spex apply

Apply a specification to implement code step by step.

## Usage

```text
/spex apply [topic_name | --all | -a]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Step 1: Resolve Topic

If `$topic_name` is `--all` or `-a`:

1. Run `$spex_skill_dir/scripts/spex get-topic --json --all` to get all topics
   with undone tasks.
2. Parse the output as a JSON array of objects, each containing
   `topic_name` and `topic_path`.
3. For each entry, set `$topic` and `$topic_path` and execute Steps 2
   through 5.
4. After completing all topics, stop.

Otherwise, run:

```bash
$spex_skill_dir/scripts/spex get-topic --json "$topic_name"
```

Read the command output and parse it as a JSON array:

- If the array contains a single element, set `$topic` to its
  `topic_name` and `$topic_path` to its `topic_path`.
- If the array contains multiple elements, present a numbered list of
  `topic_name` values to the user and ask them to choose. Set `$topic`
  and `$topic_path` from the selected entry.
- If the script exits with an error, report the error and stop.

### Step 2: Build Prompt and Execute

Run:

```bash
$spex_skill_dir/scripts/spex prompt apply-one-task --topic $topic_name
```

If the command exits with a non-zero exit code, all tasks are
completed — report completion to the user and stop.

1. Save stdout to `$prompt`.
2. Parse `$next_task_id` from stderr (format: `task_id=<id>`).
3. Launch a subagent with `$prompt` to implement the current task.

### Step 3: Commit

Load the commit prompt:

```bash
$spex_skill_dir/scripts/spex prompt apply-commit
```

Follow the output instructions to create a git commit.

After a successful commit, run:

```bash
git log -1 --pretty="%h: %s"
```

Save the output to `$commit_title`.

### Step 4: Mark Task Complete

Run:

```bash
$spex_skill_dir/scripts/spex todo mark-done "$next_task_id" "$commit_title" $topic_path/todo.json
```

### Step 5: Loop

Go back to Step 2. Do **not** stop while `todo.json` still has undone
tasks.
