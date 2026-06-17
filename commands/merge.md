# spex merge

Submit completed work by merging the feature branch or creating a PR.

## Usage

```text
/spex merge [spec_name] [--dry-run | -n] [--no-archive]
```

When `spec_name` is omitted, the CLI automatically searches for
submittable specs (completed tasks + has `spex_branch` + related to
the current project). If exactly one is found it is auto-selected;
if multiple are found a numbered list is displayed for interactive
selection.

## Procedure

Follow these steps in order. Do not skip or reorder.

### Phase 1: Resolve Spec

Run:

```bash
$spex_skill_dir/scripts/spex list --json --must-done "$spec_name"
```

Read the command output and parse it as a JSON array:

- If the array contains a single element, set `$spec_name` to its
  `spec_name` and `$spec_path` to its `spec_path`.
- If the array contains multiple elements, present a numbered list of
  `spec_name` values to the user and ask them to choose. Set
  `$spec_name` and `$spec_path` from the selected entry.
- If the script exits with an error, report the error and stop.

### Phase 2: Validate

Read `$spec_path/meta.json` and check:

- If `spex_branch` is not set, report that branch management is not
  active for this spec and stop.

### Phase 3: Submit

Run:

```bash
$spex_skill_dir/scripts/spex merge $spec_name
```

Parse the JSON output:

- If `errors` is non-empty, report the errors to the user and stop.
- Otherwise, note the `action`, `source`, and `target` fields.

### Phase 4: Output

Display the following summary to the user:

```text
**Submit**: `$spec_name`

- Action: $action
- Source branch: $source
- Target branch: $target
- Archived: $archived
```

Where `$archived` is `yes` if the JSON response has `"archived": true`,
or `no` if `"archived": false`.

**STOP.** The submit is complete. Do NOT start implementing any
further changes.
