# Todo-Helper Cookbook

Shared `spex todo-helper` examples. Read the sections needed for the
current operation.

## Principles

- Small batches: each coding step independently committable +
  verifiable
- Self-contained: production code + tests in the same step —
  never split
- Ordered by dependency: each builds on previous; no forward refs
- Append in execution order. The helper assigns numeric IDs from 1.
- No per-step review flag — review runs only when a step produces
  a commit (and global `step_review` allows it)

## Selecting a Step

Use a positive step number (`2`) or a label with `--id` for `show`,
`edit`, `complete`, and `remove`, with `--before` or `--after` for
`insert`, or with `--from` and `--to` for `move`. The `step` prefix is
case-insensitive and accepts a hyphen or a space before the number. For example,
`--id step-2`, `--id STEP-2/5`, and `--id "STEP 2/5"` all select the
second entry in the current list. Only the step number before the
first slash is parsed. Everything after that slash is ignored.

## skip_commit Conventions

| Step type | Flag |
|-----------|------|
| Coding / expected repo change | Default `false` — **omit** `--skip-commit` |
| Non-coding / must not touch repo | `--skip-commit true` |
| Commit only if files change | `--skip-commit auto` |

- Do **not** put `--skip-commit true` on coding steps
- Values: `true` | `auto` | `false` (default omit / `false`)
- JSON bool `true`/`false` and lowercase strings only — not
  `"True"` / `"AUTO"`

## details Formatting

- Multi-line Markdown OK (file changes, logic, acceptance
  criteria)
- Use lists, bold, inline code
- Do **not** use headings (`#`, `##`, etc.)

Prefer `--details-from-stdin` + heredoc for multi-line details.

## Transactions

Start before the first edit in a batch.

```bash
$spex_skill_dir/scripts/spex todo-helper transaction start "$spec_name"
```

Commit after the batch passes validation.

```bash
$spex_skill_dir/scripts/spex todo-helper transaction commit "$spec_name"
```

Roll back if the batch is abandoned.

```bash
$spex_skill_dir/scripts/spex todo-helper transaction rollback "$spec_name"
```

`start` saves the original todo file in `todo.json.lock`. An absent or
blank todo file produces an empty backup. `commit` assigns integer IDs
in list order and deletes the backup after the write succeeds.
`rollback` restores the backup or removes both files if it is empty.
Serialize writes to a given todo file. An existing backup blocks another
start and can be committed or rolled back by its owning transaction.

## Remove unfinished steps

Use this command in `/spex modify` when the remaining plan needs a
rebuild. Check for unfinished steps with a recorded commit before
clearing the list. Those steps must finish review first.

```bash
$spex_skill_dir/scripts/spex todo-helper remove-undone "$spec_name"
```

Completed entries retain their order and completion data.

## Append

Omit `--id`. During a transaction, new entries receive their stored
IDs at commit. Outside a transaction, the helper numbers them on write.

**Coding step** (default — omit `--skip-commit`):

```bash
$spex_skill_dir/scripts/spex todo-helper append "$spec_name" \
  --step-name "Short description for the step" \
  --details-from-stdin <<'DETAILS'
- Create `src/auth.py` with login endpoint
- Add input validation for email and password
- Write unit tests in `tests/test_auth.py`

**Acceptance criteria**: all tests pass, endpoint returns JWT
DETAILS
```

**Non-coding / no-repo-change** — set `--skip-commit true` (or
`auto` when a commit is only needed if files change):

```bash
$spex_skill_dir/scripts/spex todo-helper append "$spec_name" \
  --step-name "Confirm checklist without repo edits" \
  --skip-commit true \
  --details-from-stdin <<'DETAILS'
Verify acceptance criteria without changing tracked files.

**Acceptance criteria**: working tree stays clean (excl. spex_root)
DETAILS
```

Optional on `append`, `insert`, and `edit`: `--skip-commit true|auto|false`
(default `false` / omit).

The task name field on `append` and `insert` is `--step-name`.
`--title` belongs to `review-helper append` findings, not to todo
entries; passing it here exits 2 with a hint pointing at
`--step-name`.

## Insert

Use exactly one of `--before` or `--after` with the current position
displayed by `show`. Supply the same entry fields as for `append`.

```bash
$spex_skill_dir/scripts/spex todo-helper insert "$spec_name" \
  --before "STEP 2/5" --step-name "Add input validation" \
  --details "Reject empty input."
```

An open transaction preserves existing stored IDs until commit, which
numbers the full list. Outside a transaction, insertion numbers the
list on write. Refresh `show` before selecting steps again.

## Show

Review the full current list before choosing targeted edits or a
rebuild. JSON shows the current positional IDs and completion state.
Markdown labels use `step-<num>/<count>`, where `<count>` is the total
number of steps even after filtering. Use the current position for
positional arguments. Refresh the list after inserting, removing, or
swapping steps before selecting another entry by position.

```bash
$spex_skill_dir/scripts/spex todo-helper show "$spec_name" \
  --format markdown
```

## Edit

Only specified fields are updated:

```bash
$spex_skill_dir/scripts/spex todo-helper edit "$spec_name" \
  --id 1 --details-from-stdin <<'DETAILS'
Updated multi-line details for this step.

- Revised implementation approach
- Added error handling requirements
DETAILS
```

## Move

Swap two steps by their current positions:

```bash
$spex_skill_dir/scripts/spex todo-helper move "$spec_name" --from Step-2/5 --to 5
```

Each step keeps its stored ID when swapped. The next `show` displays
IDs based on the new order. Use those displayed IDs for subsequent edits.
To persist consecutive IDs for the new order, start a transaction before
moving the steps and commit it after the edits.

## Renumber

Persist the positional IDs shown by `show` after an edit outside a
transaction:

```bash
$spex_skill_dir/scripts/spex todo-helper renumber "$spec_name"
```

`renumber` assigns consecutive integer IDs from 1 and preserves step order
and other entry fields. It can repair missing, duplicate, or invalid IDs in
an otherwise valid todo file. Use `transaction commit` to renumber when a
transaction is open.

## Remove

```bash
$spex_skill_dir/scripts/spex todo-helper remove "$spec_name" \
  --id 1
```
