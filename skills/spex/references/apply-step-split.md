# Split the Active Apply Step

Use this reference in shared Phases 4–5 when the current task needs
multiple independently verifiable commits.
Follow [the CLI contract](cli-contract.md) and
[the todo-helper cookbook](todo-helper-cookbook.md).

## Eligibility

- Before implementation, capture the full HEAD and the result of
  `apply-helper dirty --json --name "$spec_name"` for the bound coding
  worktree. Require a clean baseline outside Spex storage.
- Before opening the split transaction, confirm HEAD still matches
  that baseline and the current task is still the first unfinished
  step with an empty `commit_title`. Require a closed todo transaction.
- Use the split commit path only for a first replacement that requires
  a commit under the existing `skip_commit` matrix.
- Verify that each proposed step can be delivered and checked
  independently in dependency order. Assign the current changes to
  specific steps and identify any residue that can be redone from the
  new plan. Stop and preserve the changes when attribution is unclear,
  cleanup would affect outputs outside the coding worktree, or an
  eligibility check fails.

## Save the Split Plan

- Read the whole list with `todo-helper show`. Keep the current
  position for the first replacement step. Plan insertions directly
  after it, in dependency order. Stop before editing if the proposed
  changes would alter the contents or positions of completed steps or
  unfinished steps with a recorded `commit_title`.
- Use one existing `todo-helper transaction`. Edit the current step
  and insert each follow-up using current positions from `show`.
  Give each follow-up its own scope, deliverable, and acceptance
  criteria. Leave its `commit_title` and `completed_at` empty.
- Check the edited list before transaction commit. Verify the first
  replacement's original position, follow-up order and empty progress,
  and preservation of protected entries. Roll back the todo transaction
  on an edit or validation failure. On transaction commit or rollback
  failure, preserve the backup and report the existing recovery command.
  Stop before making a Git commit until the transaction succeeds.
- After transaction commit, reread the list and bind the same task
  position to the narrowed first step. Refresh its task description,
  commit strategy, and execution report before Phase 5. The main
  session's handoff still verifies the recorded commit for that position.

## Scope the First Commit

- Inspect the staged patch against HEAD, the unstaged patch against the
  index, and untracked files. For a path with staged follow-up changes,
  use `git --literal-pathspecs restore --staged -- "$path"` to unstage it
  while preserving the worktree. Before unstaging, confirm that doing
  so will preserve every staged change in the worktree. Stop and
  preserve both versions if the index holds changes absent from it.
- Stage wholly first-step paths explicitly. For mixed paths, select
  only first-step hunks with `git add -p` or apply a reviewed first-step
  patch with `git apply --cached`. Keep the remaining changes in the
  worktree. Verify all paths in the full staged diff against HEAD
  before committing, including after fixing a failed commit attempt.
- Verify the narrowed first step and use its actual outcomes in the
  commit report. Run any required repository checks before committing.
  Confirm HEAD still matches the base, then make one commit in Phase 5
  and persist only its `commit_title`.

## Clean and Verify After the First Commit

- Confirm HEAD is the recorded first-step commit, its diff matches the
  first-step scope, and the index matches HEAD. Inspect the remaining
  unstaged changes and untracked files. Proceed with cleanup only when
  each remaining change is a known, reproducible follow-up from this
  invocation. Stop if any ownership or path is uncertain.
- Before any cleanup, inspect the filesystem shape of each exact path
  and its ancestors without following symlinks. Require all ancestors
  below the coding worktree root to be real directories. Require a
  tracked cleanup target to be a regular file in HEAD and either a
  regular file or absent in the worktree. An untracked cleanup target
  must be an individual regular file. Stop and preserve all remaining
  paths if any target is a directory, symlink, or other unexpected type,
  or if an ancestor would need replacement. Check the shape again just
  before operating on each path. Git status can omit ignored descendants
  of a directory that replaced a tracked file, and a literal restore
  can delete that directory and its contents.
- Restore a tracked path with
  `git --literal-pathspecs restore --worktree -- "$tracked_path"` only
  when all of its remaining changes qualify for cleanup. For untracked
  files, check the exact path is listed as untracked and non-ignored,
  and remove it individually. Keep cleanup inside the bound coding
  worktree and outside Spex storage. Leave ignored files, directories
  requiring recursive deletion, user changes, and external outputs
  alone. Stop on any cleanup failure.
- Run the dirty CLI and require a clean worktree outside Spex storage.
  Run the narrowed first step's acceptance checks on this clean tree
  and check it is still clean afterward. For general mode, keep the
  existing acceptance evidence requirements. Continue to Phase 6
  only on success.
- On cleanup or acceptance failure, keep the plan and recorded commit,
  leave `completed_at` empty, and report the remaining work and the
  explicit recovery path. A failed cleanup may have removed some
  confirmed follow-up paths already.

## Resume After a Pre-Commit Interruption

- If the split plan was saved but the first Git commit was interrupted,
  explicitly recover in the bound worktree. Identify the first
  replacement in the saved todo list and confirm HEAD is still its
  pre-commit base. If a Git commit already exists, use the post-commit
  recovery path instead.
- Inspect staged and unstaged diffs and untracked files separately.
  Recheck the boundary between the first replacement and its follow-ups,
  including mixed hunks in the same file. Keep all changes and stop if
  ownership or the commit boundary is unclear.
- Resume using scoped staging for the first replacement. Verify the full
  staged patch contains only its changes before committing. A normal
  apply retry can stage all changes, so keep it out of this explicit
  recovery path. Leave follow-up changes for split-specific cleanup
  after the first commit is recorded.

## Resume After a Post-Commit Interruption

- Callers recovering a known split must complete these steps before
  rerunning either apply entry point for review. Verify the first-step
  Git commit against the narrowed todo and current HEAD. If its
  `commit_title` is missing, use the Phase 5 persistence recovery to
  record the existing commit.
- Use the same scoped cleanup rules. When provenance cannot be
  established after interruption, preserve those changes and stop for
  the operator to resolve. Verify the worktree is clean and rerun the
  first-step acceptance checks even if cleanup has already finished.
- After successful isolated verification, resume existing review of
  the recorded commit. Keep the step pending and stay out of review
  if cleanup or acceptance fails. Recovery keeps the existing commit
  and uses the existing todo fields.
