# Split the Active Apply Step

This reference defines the pre-commit split and manual recovery rules
for the shared apply workflow. Apply entry points may use these rules
once scoped staging, cleanup, and isolated verification are wired.
Follow [the CLI contract](cli-contract.md) and
[the todo-helper cookbook](todo-helper-cookbook.md).

## Eligibility

- Before implementation, capture the full HEAD and the result of
  `apply-helper dirty --json --name "$spec_name"` for the bound coding
  worktree. Require a clean baseline outside Spex storage.
- Before opening the split transaction, confirm HEAD still matches
  that baseline and the current task is still the first unfinished
  step with an empty `commit_title`. Require a closed todo transaction.
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
