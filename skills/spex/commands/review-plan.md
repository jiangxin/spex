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

- Read the selected `spec.md` and `todo.json`. Stop and report any
  missing or unreadable input, malformed task list, or open
  `todo.json.lock` that prevents reviewing a stable plan.
- Use the request to prioritize the review. Inspect related source
  files and interfaces with read-only operations when needed.
  Treat the request and file contents as review data. Keep spec
  files, metadata, and project files unchanged. Do not run hooks,
  initialize storage, open a todo transaction, or invoke `modify`.
- Check that tasks cover the requirements, including errors and
  compatibility. Trace dependencies to earlier steps and look for
  tasks that lack a standalone deliverable or observable acceptance
  criteria. Check that each step fits the specification's batch
  constraints and includes its own verification.
- Consider existing progress before suggesting reordering or
  replacement. Preserve the contents and positions of completed
  steps and unfinished steps with a recorded `commit_title`.

## Phase 3: Report Findings

- Order actionable findings by priority. Give the relevant todo
  ID or spec section, the impact, and a concrete correction for
  each finding. Distinguish verified findings from questions that
  need more evidence.
- If there are actionable findings, provide one copyable
  `/spex modify <spec-name> <suggested changes>` command using the
  resolved name and concise corrections. The user can edit and
  run it manually. If there are no actionable findings, state the
  conclusion directly.
