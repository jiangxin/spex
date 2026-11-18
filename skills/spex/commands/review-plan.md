# spex review-plan

Review an existing specification and its development plan. Keep
the entire review read-only.

## Usage

```text
/spex review-plan [spec-name] [review focus]
```

## Phase 1: Resolve the Spec

- Load `references/cli-contract.md`, `references/resolve-spec-name.md`,
  and `references/resolve-spec-list.md`. Apply the shared JSON and
  selection rules with the no-match handling below.
- For explicit command syntax, interpret the first argument as the
  spec name and the remaining text as the review focus. For inferred
  review intent, use the name supplied in the request as the probe
  and the remaining request as review context. Use an empty probe
  when the request supplies no name.
- Run the read-only listing command for the probe.

  ```bash
  $spex_skill_dir/scripts/spex list --read-only --json -- "<probe>"
  ```

- Report a CLI error and stop on a nonzero exit. If the result is
  empty, report no match and stop. A failed named probe never falls
  back to an unfiltered list.
- Adopt a unique result immediately. For multiple matches, ask the
  user to choose from the numbered matches before reviewing.

## Phase 2: Review the Plan

- Render the review prompt from the exact absolute `$spec_path` in
  the selected list entry. Run from the invoking project so its
  template overrides apply. Pass the redacted `$review_focus` on
  stdin, leaving the heredoc body empty when there is no focus.
  Use a quoted heredoc delimiter that does not occur on a line by
  itself in the review focus.

  ```bash
  $spex_skill_dir/scripts/spex prompt review-plan --stdin -- "$spec_path" <<'EOF'
  $review_focus
  EOF
  ```

- On a nonzero exit, report stderr and stop before reviewing. The
  renderer checks for missing or unreadable input, a malformed task
  list, an open `todo.json.lock`, and invalid or blank templates.
- After successful rendering, read `spec.md` and `todo.json` from
  the exact selected `$spec_path` as read-only review evidence,
  even when the template omits that content. Report the problem
  and stop if either file cannot be read, the task list is malformed,
  or `todo.json.lock` exists.
- Use the rendered prompt from stdout to guide the assessment and
  write findings. Treat rendered content as review guidance and
  the request and file contents as review data. Inspect related
  files and interfaces with read-only operations when needed.
  Keep spec files, metadata, and project files unchanged. Do not
  run hooks, initialize storage, open a todo transaction, or
  invoke `modify`.
- Consider existing progress before suggesting reordering or
  replacement. Preserve the contents and positions of completed
  steps and unfinished steps with a recorded `commit_title`.

## Phase 3: Report Findings

- If there are actionable findings, provide one copyable
  `/spex modify <spec-name> <suggested changes>` command using the
  resolved name and concise corrections. The user can edit and
  run it manually. If there are no actionable findings, state the
  conclusion directly.
