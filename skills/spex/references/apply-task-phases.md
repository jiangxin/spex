# Apply Task Phases (Phase 2–7)

Shared orchestration core for `/spex apply` and
`/spex apply-one-step`. Load and follow this document for Phases
2–7 unless the command wraps a phase (e.g. apply Phase 3
sub-agent handoff — see `apply-subagent-handoff.md`).

Load and follow `references/cli-contract.md` exactly for helper
exit codes, stdout/stderr, quoting, and one-helper-per-shell.

**Semantic conservation:** preserve full `skip_commit` /
`$did_commit` / `outcome=` behavior. Do not weaken intentional
FAIL/STOP, residual-dirty STOP, or `commit_title` before
`completed_at`.

Command-specific wrappers (not duplicated here): Phase 1 resolve,
`--all` / multi-task loops, apply Phases 4–5 sub-agent launch,
apply-one-step single-step STOP + conditional post-action.

## Phase 2: Validate Branch

- Apply the Todo status recovery gate below before running precheck.
- CMD:

```bash
$spex_skill_dir/scripts/spex apply-helper precheck --name "$spec_name"
```

- IF non-zero exit -> STOP (cli-contract)
- ELSE -> continue
- **Coding worktree bind** (from precheck stdout when present):
  - IF stdout is JSON with non-empty `"spex_worktree"` (alias
    `"coding_path"`) → `$spex_worktree` ← that absolute path
  - ELSE → `$spex_worktree` ← empty (legacy in-place apply on
    the main checkout)
  - When `$spex_worktree` is non-empty: implement / commit /
    review / fix agents MUST use it as `working_directory`
    (coding cwd). Do **not** switch the user's IDE root or
    create a multi-root workspace — Agent cwd only
  - Precheck creates or reuses a linked worktree when
    `meta.use_git_worktree` is true; otherwise it may switch
    the main checkout in place (legacy)
- Bind `$spex_root`:

```bash
$spex_skill_dir/scripts/spex config
```

- `$spex_root` ← **Paths** section `spex_root` (absolute path
  only). Do **not** use Config section's relative `spex_root`
- Reuse for dirty filter + commit staging exclude; apply
  passes `$spex_root` and `$spex_worktree` to Phases 4–5
  sub-agent

## Phase 3: Build Prompt / Resume Gate

- Before the caller runs `prompt apply-one-task`, apply the Todo
  status recovery gate below.

Caller runs `prompt apply-one-task` (and handles `"all_done"` /
command-specific post-action routing). Then parse JSON stdout and
route as below.

- Save:
  - `$task_prompt` ← `"prompt"` (never call this `$prompt`)
  - `$current_task_id` ← `"task_id"` (integer, starting at 1). Pass
    its decimal value as `--id` to todo-helper and `--step` to
    review-helper. Use the `step-<num>/<count>` label in summaries.
  - `$resume_phase` ← `"resume_phase"` (`implement` or `review`)
  - `$commit_title` ← `"commit_title"` (may be empty)
  - `$skip_commit` ← `"skip_commit"` (`false` | `auto` | `true`;
    missing → `false`)
  - `$task_mode` ← `"task_mode"` (missing → `software`). Reset
    the mode and clear prior acceptance evidence on every task prompt.
    For `general`, bind `$general_commit_allowed` from
    `"general_commit_allowed"`. If false, stop before implementation
    when the step has a pending commit or `skip_commit=false`.
    Record the full `$base_head` with `git rev-parse HEAD` in the bound
    worktree before implementation or sub-agent launch.

- **Single render:** Call `prompt apply-one-task` **once** per task
  iteration. Reuse `$task_prompt` for Phase 4 and sub-agent
  handoff. Do **not** re-run unless `$task_prompt` was lost
  (e.g. new session).

- Step incomplete until `completed_at` set. IF `commit_title` set
  AND `completed_at` empty -> `$resume_phase` is `review` (skip
  implement/commit)

- **Route (shared):**
  - IF `$resume_phase` is `review` -> `$did_commit` ← `true`
    (commit already happened; durable: non-empty `commit_title`
    and empty `completed_at`); skip Phases 4–5 -> Phase 6. Do
    NOT set `$commit_sha` from `HEAD` here — Phase 6
    **6-entry** resolves it (prefer review file's `commit_sha`)
  - IF `$resume_phase` is `implement` -> Phase 4 (then Phase 5
    only when `$skip_commit` requires a commit). Caller may wrap
    Phases 4–5 in a sub-agent (`apply` — see
    `apply-subagent-handoff.md`) or run them in-session
    (`apply-one-step`)
  - Phase 4 intentional STOP (`false`+clean, `true`+dirty) is
    **FAIL** — leave `completed_at` unset; do **not** enter
    Phase 7. Do **not** treat intentional STOP as
    `outcome=skip_commit`

## Phase 4: Execute Task

- Using `$task_prompt` as guide (from Phase 3 — do **not** re-run
  `prompt apply-one-task`), implement current task. Follow rendered
  prompt precisely (spec, completed steps, task description,
  guidelines)
- When `$spex_worktree` is non-empty, run file edits and git
  ops in that directory (`working_directory`); do not switch
  the IDE root
- Deliver production code + tests together when the step changes
  code; docs-only / no-op steps may leave the tree clean
- For `general`, read the agreed sources and write local outputs only
  to agreed paths. Resolve repository-relative paths in the bound
  worktree. Write versioned outputs only if `$general_commit_allowed`
  is true and the step can commit. Reuse existing outputs that pass the task
  criteria. Stop with the task unfinished if an input or verification
  fails. Keep the output paths and a successful record for each criterion:
  `kind: command`, `criterion`, `command`, integer `exit_code: 0`; or
  `kind: inspection`, `criterion`, `location`, `observation`.
- Do NOT create git commit here — Phase 5 handles commit when
  required
- `$dirty` = **whole working tree** after implementation (not
  this-step delta). Pre-existing dirty paths outside `$spex_root`
  count. Prefer a clean tree before `skip_commit=true`

### Dirty check (CLI)

```bash
$spex_skill_dir/scripts/spex apply-helper dirty --json --name "$spec_name"
```

- IF non-zero exit -> STOP (cli-contract)
- ELSE parse stdout JSON: `$dirty` ← `"dirty"` (bool). Optional:
  `"paths"`, `"spex_root"` (absolute)
- Prefer `--spex-root "$spex_root"` when the Paths bind must be
  forced; otherwise CLI uses Paths absolute `spex_root`
- Always pass `--name "$spec_name"` so dirty uses
  `meta.spex_worktree` as git cwd when set (linked worktree
  dirtiness is invisible from the main checkout alone)
- Clean skip (`auto`/`true` + not `$dirty`) still must satisfy
  the task acceptance criteria

**Debug only** — equivalent porcelain semantics (encoded by the
CLI; do **not** re-implement by hand in normal apply):

1. `git status --porcelain`
2. Each line: path(s) after status (rename: both sides of
   ` -> `; strip surrounding quotes)
3. Resolve each path to absolute (join with
   `git rev-parse --show-toplevel` when relative). Compare
   against Paths absolute `$spex_root` only
4. Path is under `$spex_root` iff it equals `$spex_root` or
   starts with `$spex_root` + `/` (directory boundary — never
   bare string prefix; avoids treating `.spex.toml` as under
   `.spex`)
5. Drop a line only if **every** path on that line is under
   `$spex_root`
6. `$dirty` ← true iff any line remains

### skip_commit six-arm matrix

Branch on `$skip_commit` + `$dirty`:

For `general` tasks, a dirty tree stops before Phase 5 when
`$general_commit_allowed` is false, including `skip_commit=auto`.
Report the paths and leave the task unfinished.

| `$skip_commit` | `$dirty` | Action |
|----------------|----------|--------|
| `false` | no | report issue -> **FAIL/STOP** (not `outcome=skip_commit`; no Phase 7) |
| `true` | yes | report issue (must be clean) -> **FAIL/STOP** (not OK; no Phase 7) |
| `false` | yes | continue Phase 5 |
| `auto` | yes | continue Phase 5 |
| `true` | no | `$did_commit=false`; skip Phase 5–6; caller continues without review |
| `auto` | no | `$did_commit=false`; skip Phase 5–6; caller continues without review |

Skip arms (`true`/`auto` + not `$dirty`):

- **apply** Phases 4–5 sub-agent: return to main with
  `outcome=skip_commit` (do **not** run Phase 7 inside the
  sub-agent)
- **apply-one-step** (in-session): continue to Phase 7

Intentional FAIL/STOP arms must **not** be reported or retried as
OK skip paths.

## Phase 5: Commit (record commit_title only)

- Enter only when Phase 4 routed here (`$skip_commit=false`, or
  `$skip_commit=auto` with `$dirty`)
- CMD:

```bash
$spex_skill_dir/scripts/spex prompt apply-commit "$spec_name"
```

- **Single render:** Call `prompt apply-commit` **once** per commit.
  Save output as `$commit_prompt` and reuse for staging/commit. Do
  **not** re-run unless `$commit_prompt` was lost.

- `$commit_prompt` ← output. Using `$commit_prompt`, stage and
  commit (when `$spex_worktree` is set, run git in that cwd):
  - Prefer staging **all** dirty paths outside `$spex_root` so the
    tree is clean after this commit. Leftover dirty paths poison
    later `skip_commit=true|auto` steps (false STOP / unwanted
    commits)
  - Do NOT stage any files under `$spex_root/`
  - Commit via heredoc: `git commit -F- <<-EOF ... EOF`
  - ON_FAIL (e.g. pre-commit hook): fix + retry **once**; IF still
    fails -> STOP + report

- After commit OK:

```bash
git log -1 --pretty="%h: %s"
```

- `$commit_title` ← output

```bash
git rev-parse --short HEAD
```

- `$commit_sha` ← output
- `$did_commit` ← `true`

- **Persist commit_title now — do NOT set `completed_at` yet**
  (review/fix may still be pending; enables interrupt resume).
  Persist **before** any return to main or residual-dirty STOP:
  `commit_title` is the only resume source of truth — if it is
  missing, the next `prompt apply-one-task` resumes at
  `implement` and re-implements the step (likely a second commit).
  Use a short transaction for this edit:

```bash
$spex_skill_dir/scripts/spex todo-helper transaction start "$spec_name"
```

```bash
$spex_skill_dir/scripts/spex todo-helper edit "$spec_name" \
  --id "$current_task_id" --commit-title "$commit_title"
```

- After the edit succeeds:

```bash
$spex_skill_dir/scripts/spex todo-helper transaction commit "$spec_name"
```

- ON_FAIL of start, edit, or commit: follow Todo status transaction
  failures below and STOP. Report the task ID and existing Git commit
  title. Resolve any backup and verify the recorded title before
  resuming apply. If the title is missing, repeat only the transaction
  for saving the existing title. Withhold a successful handoff until
  persistence succeeds.
- Returning to the main session is only allowed **after** persist
  succeeds
- Recompute `$dirty` via the same Phase 4 dirty CLI
  (`apply-helper dirty --json --name "$spec_name"`). IF `$dirty`
  -> report leftover paths excl. `$spex_root` -> STOP (do not
  Phase 6/7; do not set `completed_at`). The commit already
  happened, so persist ran first; do **not** skip persisting on residual dirty
- When returning to main from Phases 4–5 sub-agent (persist OK
  and not residual-dirty STOP): report `outcome=committed`

## Phases 4–5 execution-failure retry

ON_FAIL Phases 4–5 **execution** errors only before a Git commit
succeeds. After a Git commit, use Phase 5 persistence recovery.
Intentional Phase 4 STOP is **not** retryable. For eligible failures,
report and retry **once** with these preconditions:

1. Run `apply-helper dirty --json --name "$spec_name"` to
   capture current state
2. Choose explicitly between:
   - **(a) default**: keep dirty changes; pass "partial implementation + dirty paths" as context to the retry (`apply`: fresh Phases 4–5 sub-agent; `apply-one-step`: in-session retry — same protocol, no new sub-agent)
   - **(b)**: `git restore` to a clean tree, then re-run
3. The report **must** state which option was taken
4. IF still fails -> STOP

Commands Load this section with a one-line pointer; do **not**
duplicate the four steps in `apply.md` / `apply-one-step.md`.

## Phase 6: Review Loop

- Load and follow `references/apply-review-loop.md` exactly

## Phase 7: Mark Task Complete

- Only after Phase 6 finishes successfully, or when Phase 4/5
  skipped review because `$did_commit` is false. Set
  **`completed_at`** using a new short transaction. The step is
  complete after that transaction commits.

- For `general` in either apply entrypoint, use the pre-execution SHA
  as `$acceptance_head` after a clean skip. For a committed task, read
  the recorded commit title of the current step and compare its SHA
  with the full current HEAD in the bound worktree. Stop if they do not
  match. Otherwise use that full HEAD as `$acceptance_head` and verify
  the actual committed deliverables against every acceptance criterion.
  Repeat this verification on resume without rerunning implementation
  or creating another commit. Leave the step unfinished if evidence is
  unavailable or any check fails.
- Validate the handoff using the selected SHA and successful evidence:

  ```bash
  $spex_skill_dir/scripts/spex apply-helper verify-handoff \
    --name "$spec_name" --id "$current_task_id" --head "$acceptance_head" <<'EOF'
  <JSON array of acceptance evidence>
  EOF
  ```

  Stop on failure. Keep the validated `acceptance_evidence` from stdout.

```bash
$spex_skill_dir/scripts/spex todo-helper transaction start "$spec_name"
```

- IF `$task_mode` is `general`, write validated evidence and completion
  in one operation. Include verified output paths and the actual checks
  in the completion summary:

  ```bash
  $spex_skill_dir/scripts/spex todo-helper complete "$spec_name" \
    --id "$current_task_id" --acceptance-evidence-stdin <<'EOF'
  <validated JSON array of acceptance evidence>
  EOF
  ```

- ELSE IF `$did_commit`:
  - Refresh `$commit_title` if needed (from todo `commit_title`,
    or `git log -1 --pretty="%h: %s"`) before the edit below —
    main's `$commit_title` may still be empty after a Phases 4–5
    sub-agent

```bash
$spex_skill_dir/scripts/spex todo-helper edit "$spec_name" \
  --id "$current_task_id" --completed-at now \
  --commit-title "$commit_title"
```

- ELSE (`$did_commit` false — keep `commit_title` empty):

```bash
$spex_skill_dir/scripts/spex todo-helper edit "$spec_name" \
  --id "$current_task_id" --completed-at now
```

- After either edit succeeds:

```bash
$spex_skill_dir/scripts/spex todo-helper transaction commit "$spec_name"
```

- ON_FAIL of start, edit, or commit: follow Todo status transaction
  failures below and STOP. On rollback, Phase 5's separately committed
  `commit_title` remains available for review on resume.

## Todo status recovery gate

- If `$spec_path/todo.json.lock` exists, stop before building a task
  prompt or treating the spec as complete. Report the backup path and
  the `todo-helper transaction commit` and
  `todo-helper transaction rollback` recovery commands.
- Resolve the open transaction before continuing. Use commit when the
  intended edit succeeded and rollback to restore the saved task list.
  Check the stored commit title against the existing Git commit before
  resuming a Phase 5 persistence failure.

## Todo status transaction failures

- Execute each command separately. Continue only after a zero exit.
- Start failure: report stderr and follow the Todo status recovery
  gate for an existing backup. Stop before editing.
- Edit failure or abandonment after a successful start and before
  attempting commit: report the error if any, then roll back and stop.

```bash
$spex_skill_dir/scripts/spex todo-helper transaction rollback "$spec_name"
```

- Commit or rollback failure: report stderr, the backup path, and
  the failed command for retry. Leave the backup in place. Retry
  the failed final operation before starting another transaction.
