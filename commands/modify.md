# spex modify

Modify an existing specification's requirements and regenerate the
development plan.

## Usage

```text
/spex modify [topic_name] [prompt]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Step 1: Collect Prompt

If `$prompt` is not provided or empty, ask the user to describe what
changes they want to make to the spec. The user's full input becomes
`$prompt`.

### Step 2: Resolve Topic

Run:

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

### Step 3: Build Prompt

Run:

```bash
echo "$prompt" | $spex_skill_dir/scripts/spex prompt modify-spec --json --topic $topic --stdin
```

Parse the JSON output from stdout:

- If the command exits with a non-zero exit code, report the stderr
  message and stop.
- Otherwise, save `$modify_prompt` from the `"prompt"` field.

### Step 4: Modify spec.md

Using `$modify_prompt` as the prompt, update `$topic_path/spec.md`
according to the instructions rendered in the prompt.

### Step 5: Generate todo.json

Regenerate `$topic_path/todo.json` by first producing `todo.xml` via a
prompt, then converting and appending:

1. Run:

   ```bash
   $spex_skill_dir/scripts/spex prompt modify-todo --json --topic $topic
   ```

   This command internally:
   - Removes incomplete steps from `todo.json` (preserving completed ones)
   - Renders a prompt with the updated spec and completed steps context

   Parse the JSON output and save `$modify_prompt` from the `"prompt"` field.

2. Use `$modify_prompt` as context to write new `$topic_path/todo.xml`.
   Follow these rules:
   - **Do NOT include completed steps**: They are preserved in todo.json.
   - **Corrective steps**: If completed steps conflict with the new spec,
     add corrective steps.
   - **Add new steps**: Append steps for remaining work.

3. Run:

   ```bash
   $spex_skill_dir/scripts/spex todo xml2json --append $topic_path/todo.xml
   ```

   This converts `todo.xml` to JSON and appends the new steps to the
   existing `todo.json`, preserving completed steps. If the script exits
   with an error, read the error message, fix the XML format in
   `todo.xml`, and re-run until conversion succeeds.

### Step 6: Validate todo.json

Run:

```bash
$spex_skill_dir/scripts/spex todo validate $topic_path/todo.json
```

If the script exits with an error, read the error message, fix the JSON
format in `todo.json`, and re-run until validation passes.

### Step 7: Output

Display the following summary to the user:

```text
**Topic**: `$topic`

- Spec: `$topic_path/spec.md`
- Todo: `$topic_path/todo.json`
```
