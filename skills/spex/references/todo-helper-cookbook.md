# Todo-Helper Cookbook

Shared `spex todo-helper` usage for planning steps (`/spex create`
Phase 6, `/spex modify` todo redesign, and templates such as
`templates/modify-todo.md`). Load and follow when a command says
to build or revise `todo.json` via todo-helper.

## Principles

- Small batches: each coding step independently committable +
  verifiable
- Self-contained: production code + tests in the same step —
  never split
- Ordered by dependency: each builds on previous; no forward refs
- Append in execution order. The helper assigns numeric IDs from 1.
- No per-step review flag — review runs only when a step produces
  a commit (and global `step_review` allows it)

## skip_commit Conventions

Aligned with create Phase 6 and `templates/modify-todo.md`. Do
**not** weaken the coding-default commit:

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
Markdown-formatted description of what this step does,
including file changes, logic, and acceptance criteria.

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

Optional on `append` / `edit`: `--skip-commit true|auto|false`
(default `false` / omit).

## Show

Review current steps before adding more or selecting an entry to edit
or remove. Labels use `step-<num>/<count>`, where `<count>` is the
total number of steps even after filtering. Use `<num>` for `--id`.
Refresh the list after removing steps, since positions can change.

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
$spex_skill_dir/scripts/spex todo-helper move "$spec_name" --from 2 --to 5
```

Each step keeps its stored ID when swapped. The next `show` displays
IDs based on the new order. Use those displayed IDs for subsequent edits.
To persist consecutive IDs for the new order, start a transaction before
moving the steps and commit it after the edits.

## Remove

```bash
$spex_skill_dir/scripts/spex todo-helper remove "$spec_name" \
  --id 1
```
