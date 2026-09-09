# Apply Sub-agent Handoff (Phases 4–5)

Load from `/spex apply` only (not `apply-one-step`). Covers Phase 3
`resume_phase=implement` wrapping: launch a Phases 4–5 sub-agent,
then validate the return in **main** before Phase 6 or Phase 7.

Shared Phase 2–7 semantics live in `apply-task-phases.md`. This
file owns the decision table and main-session checklist so
`skip_commit` / `$did_commit` / `outcome=` cannot drift.

## Sub-agent launch (implement path)

When `$resume_phase` is `implement`, launch a sub-agent for
Phases 4–5 only (implement + optional first commit per
`$skip_commit`). Instruct it to follow Phases 4–5 of
`apply-task-phases.md` exactly.

Pass:

- `$task_prompt` as Phase 4 guide
- `$current_task_id`, `$spec_name`, `$skip_commit`, `$spex_root`

Implementation prompt must NOT create the commit — when a commit
is required, sub-agent runs Phase 5 (`apply-commit`) after
implementation.

ON_FAIL (implement/commit **execution** errors only — not
intentional STOP): report + retry **once**, with retry
preconditions:

1. Run `apply-helper dirty --json` to capture current state
2. Choose explicitly between:
   - **(a) default**: keep dirty changes; hand "partial implementation + dirty paths" to the fresh sub-agent as context
   - **(b)**: `git restore` to a clean tree, then re-run
3. The report **must** state which option was taken
4. IF still fails -> STOP

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

## Decision table (main session)

After OK return (or on `resume_phase=review` without a
sub-agent), main binds state from **todo + dirty CLI**, not
sub-agent shell vars.

| Input | Main action |
|-------|-------------|
| `$resume_phase=review` (durable non-empty `commit_title`, empty `completed_at`) | `$did_commit` ← `true` → Phase 6. Do NOT set `$commit_sha` from `HEAD` — Phase 6 **6-entry** resolves it |
| `outcome=committed` and todo non-empty `commit_title`, empty `completed_at` | `$did_commit` ← `true`; `$commit_title` ← task's `commit_title` → Phase 6 |
| `outcome=skip_commit`, empty `commit_title`/`completed_at`, main dirty=false | `$did_commit` ← `false` → Phase 7 |
| `outcome=skip_commit` claimed but main dirty CLI `dirty=true` | unexpected handoff → **STOP** (no Phase 7) |
| Intentional STOP / FAIL from Phase 4 | **STOP**; no Phase 7; do not mark complete |
| Empty `commit_title` alone (no verified skip + clean dirty) | **not** skip OK → unexpected handoff → **STOP** |
| Any other combination | unexpected handoff → **STOP** (no Phase 7) |

## Main-session checklist (after Phases 4–5)

Numbered steps — follow in order; do not skip:

1. Re-read the current task in **main** (e.g.
   `todo-helper show --id "$current_task_id"`).
2. IF non-empty `commit_title` AND empty `completed_at`
   AND (sub-agent reported `outcome=committed` OR this is the
   `resume_phase=review` path with no sub-agent) ->
   `$did_commit` ← `true`; `$commit_title` ← task's
   `commit_title` -> Phase 6. **Done.**
   (Matching durable fields without `outcome=committed` and
   without the review path fall through — step 3 will not match
   either → step 4 unexpected handoff STOP.)
3. ELSE IF sub-agent reported `outcome=skip_commit` AND empty
   `commit_title` AND empty `completed_at` -> recompute `$dirty`
   in **main** via:

   ```bash
   $spex_skill_dir/scripts/spex apply-helper dirty --json
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
