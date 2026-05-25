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

1. Run `$spex_skill_dir/scripts/spex get-topic --json ""` to get all topics
   with undone tasks.
2. Parse the output as a JSON array of objects, each containing
   `topic_name` and `topic_path`.
3. For each entry, set `$topic` and `$topic_path` and execute Steps 2
   through 8.
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

### Step 2: Get Next Undone Task

Run:

```bash
$spex_skill_dir/scripts/spex todo get-next-undone --only-id $topic_path/todo.json
```

Save the output to `$next_task_id`.

If `$next_task_id` is empty, all tasks are done — report completion and
stop.

Then run:

```bash
$spex_skill_dir/scripts/spex todo get-next-undone --details $topic_path/todo.json
```

Save the output to `$next_task_text`.

### Step 3: Get Completed Tasks

Run:

```bash
$spex_skill_dir/scripts/spex todo get-done $topic_path/todo.json
```

Save the output to `$completed_tasks`.

### Step 4: Build Prompt

Read the full contents of `$topic_path/spec.md` into `$spec_content`.

Assemble `$prompt` using the following template:

````text
你是一个资深软件工程师，在架构设计、代码开发有着20年的经验。下面是完整的需求分析和设计。

<requirement>
$spec_content
</requirement>

$completed_section

待完成的开发步骤如下：

$next_task_text

# Constraints

- DRY — Don't Repeat Yourself: analyze existing architecture and code,
  reuse what exists, **never** generate duplicate code.
- KISS — Keep It Simple, Stupid: no over-engineering; keep it simple while
  considering performance and security.
- Single Responsibility: each function/method does one thing; consider
  splitting if it exceeds 30 lines.
- Test Often: run lint and unit tests to make sure all checks pass.
````

Where `$completed_section` is included only if `$completed_tasks` is not
empty:

```text
已经完成如下步骤的开发：

- <each line of $completed_tasks as a list item>
```

### Step 5: Execute Development

Launch a subagent with `$prompt` to implement the current task.

### Step 6: Commit

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

### Step 7: Mark Task Complete

Run:

```bash
$spex_skill_dir/scripts/spex todo mark-done "$next_task_id" "$commit_title" $topic_path/todo.json
```

### Step 8: Loop

Go back to Step 2. Do **not** stop while `todo.json` still has undone
tasks.
