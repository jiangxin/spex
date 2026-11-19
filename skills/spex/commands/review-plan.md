# spex review-plan

Review a spec and its development plan. Use only read-only operations.

## Usage

```text
/spex review-plan [spec-name] [review focus]
```

## Phase 1: Resolve the Spec

Follow [CLI I/O rules](../references/cli-contract.md#spex-cli-contract).
For explicit syntax, use the first argument as the probe and the remaining
text as `$review_focus`. For inferred intent, use the name in the request
and its remaining context. Use an empty probe when no name is supplied.

```bash
$spex_skill_dir/scripts/spex list --read-only --json -- "<probe>"
```

Run the lookup once. On `[]`, report no match and stop. For matches,
follow [Candidate selection](../references/resolve-spec-list.md#candidate-selection).

## Phase 2: Review the Plan

Follow the [plan review prompt contract](../references/cli-contract.md#read-only-plan-review-prompt).
Pass redacted `$review_focus` as the heredoc body, empty when absent.
Use a quoted delimiter that does not appear alone on a line in the focus.

```bash
$spex_skill_dir/scripts/spex prompt review-plan --stdin -- "$spec_path" <<'EOF'
$review_focus
EOF
```

After exit 0, read `spec.md` and `todo.json` directly from the selected
`$spec_path` regardless of template content. Report the problem and
stop if either file is unreadable, the task list is malformed, or
`todo.json.lock` exists.

Use the rendered prompt as guidance and the request and files as review
data. Preserve the contents and positions of completed steps and
unfinished steps with a recorded `commit_title`.

## Phase 3: Report Findings

For actionable findings, give one copyable
`/spex modify <spec-name> <suggested changes>` command with the resolved
name and concise corrections for the user to run manually. Otherwise
state the conclusion.
