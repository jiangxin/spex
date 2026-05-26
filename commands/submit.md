# spex submit

Submit completed work by merging the feature branch or creating a PR.

## Usage

```text
/spex submit [topic_name]
```

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Resolve Topic

Run:

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

### Phase 2: Validate

Read `$topic_path/meta.json` and check:

- If `spex_branch` is not set, report that branch management is not
  active for this topic and stop.
- If the topic still has undone tasks (check `$topic_path/todo.json`),
  warn the user that the spec is not fully implemented and ask whether
  to continue. If the user aborts, stop.

### Phase 3: Submit

Run:

```bash
$spex_skill_dir/scripts/spex submit --topic $topic_name
```

Parse the JSON output:

- If `errors` is non-empty, report the errors to the user and stop.
- Otherwise, note the `action`, `source`, and `target` fields.

### Phase 4: Output

Display the following summary to the user:

```text
**Submit**: `$topic_name`

- Action: $action
- Source branch: $source
- Target branch: $target
```
