# Apply Sub-agent Handoff (Phases 4–5)

Load from `/spex apply` only (not `apply-one-step`). Covers Phase 3
`resume_phase=implement` wrapping: launch a Phases 4–5 sub-agent,
then validate the return in **main** before Phase 6 or Phase 7.

Shared Phases 2–7 live in `apply-task-phases.md`. Use the
[main-session checklist](#main-session-checklist-after-phases-45)
to verify the reported outcome, persisted todo fields, and worktree state.

## Sub-agent launch (implement path)

When `$resume_phase` is `implement`, launch a sub-agent for
Phases 4–5 only (implement + optional first commit per
`$skip_commit`). Instruct it to follow Phases 4–5 of
`apply-task-phases.md` exactly.

Pass:

- `$task_prompt` as Phase 4 guide
- `$current_task_id`, `$spec_name`, `$skip_commit`, `$spex_root`
- `$base_head` for the split eligibility check
- `$task_mode`; for `general`, require the output paths and an
  `acceptance_evidence` array in the
  successful skip handoff.
- `$spex_worktree` (may be empty). When non-empty, instruct the
  sub-agent to use it as `working_directory` for implement /
  commit — do **not** switch the user's IDE root

Implementation prompt must NOT create the commit — when a commit
is required, sub-agent runs Phase 5 (`apply-commit`) after
implementation.

The guarded split in shared Phases 4–5 may edit the current todo and
insert follow-ups before commit. Bind the narrowed first step to the
original position. Return `outcome=committed` only after its commit
is recorded, cleanup succeeds, and isolated verification passes.

ON_FAIL (implement/commit **execution** errors before a Git commit
succeeds, excluding intentional STOP): Load and follow Phases 4–5
execution-failure retry in `references/apply-task-phases.md` (fresh
sub-agent). After a Git commit, use Phase 5 persistence recovery.

Phase 4/5 still set `$did_commit` inside the sub-agent for
**local** routing only.

## Required OK outcomes

Sub-agent final report MUST state exactly one OK outcome:

| Outcome | Meaning |
|---------|---------|
| `outcome=committed` | Phase 5 wrote `commit_title` (persist only; no `completed_at`) |
| `outcome=skip_commit` | `$did_commit=false`; tree clean excl. `$spex_root`; Phase 4 skip arms only (`true`/`auto` and not dirty) |

Phase 4 intentional STOP (`false`+clean, `true`+dirty) is
**FAIL** (not OK): leave `completed_at` unset; main must
**STOP** — do **not** enter Phase 7. Do **not** retry
intentional STOP as a success path.

## Main-session checklist (after Phases 4–5)

Numbered steps — follow in order; do not skip:

1. Re-read the current task in **main** (e.g.
   `todo-helper show "$spec_name" --id "$current_task_id"`).
2. IF non-empty `commit_title` AND empty `completed_at`
   AND (sub-agent reported `outcome=committed` OR this is the
   `resume_phase=review` path with no sub-agent) ->
   `$did_commit` ← `true`; `$commit_title` ← task's `commit_title`
   -> Phase 6. Let 6-entry resolve the review SHA.
   (Matching durable fields without `outcome=committed` and
   without the review path fall through — step 3 will not match
   either → step 4 unexpected handoff STOP.)
3. ELSE IF sub-agent reported `outcome=skip_commit` AND empty
   `commit_title` AND empty `completed_at` -> recompute `$dirty`
   in **main** via:

   ```bash
   $spex_skill_dir/scripts/spex apply-helper dirty --json --name "$spec_name"
   ```

   - IF `$dirty` -> report unexpected handoff (skip claimed but
     tree dirty excl. `$spex_root`) -> STOP (do **not** Phase 7)
   - ELSE `$did_commit` ← `false` -> Phase 7. **Done.**
4. ELSE -> report unexpected handoff -> STOP (do **not** Phase 7)

## Trust boundary (required)

- Do **not** treat empty `commit_title` alone as skip OK
- Do **not** rely on sub-agent `$did_commit` / `$commit_title` /
  `$dirty` shell vars (they do not cross the boundary)
- Trust only: durable todo fields + main-session
  `apply-helper dirty --json` (+ the sub-agent's explicit
  `outcome=` string as a claim to verify)
