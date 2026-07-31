---
version: "0.1.1"
required:
  - spec_content_concise
  - current_task_description
  - commit_sha
  - review_round
  - review_file
  - step_id
  - spex_skill_dir
  - open_findings
optional:
  - spex_root
  - completed_tasks_concise
  - future_tasks_concise
  - spec_name
  - user_name
  - user_email
---

Act as a senior software engineer fixing review findings for the
current implementation step. Address **every open finding** listed
below (both major and minor), mark each complete, then amend the
original commit. Do NOT start a new review. Do NOT leave any listed
finding with an empty `completed_at`.

## Open Findings

The following findings are still open in `{{ review_file }}`
(round {{ review_round }}). Fix them one by one — skipping is not
allowed.

<open-findings>
{{ open_findings }}
</open-findings>

## Fix Procedure

1. For each open finding, implement the necessary code/test/message
   fix. Prefer minimal, targeted changes.
2. Immediately after fixing a finding, mark it complete (required):

```bash
{{ spex_skill_dir }}/scripts/spex review-helper --name {{ spec_name }} \
  edit --step {{ step_id }} --id <finding-id> --completed-at now
```

3. After all findings are marked complete, confirm with:

```bash
{{ spex_skill_dir }}/scripts/spex review-helper --name {{ spec_name }} \
  status --step {{ step_id }} --json
```

   `"needs_fix"` must be `false` before you amend. If it is still
   `true`, finish the remaining open findings first.
4. Run lint and relevant tests; proceed only when they pass.
5. **Amend** the original commit at `{{ commit_sha }}` (must still
   be `HEAD`, not pushed). Stage only relevant source/test changes
   (never files under spex_root), then:

{% if user_name and user_email -%}
```bash
git -c user.name="{{ user_name }}" \
    -c user.email="{{ user_email }}" \
    commit --amend -F- <<'EOF'
<updated commit message if message was a finding; otherwise keep
 the improved message that still explains WHY and the approach>
EOF
```
{% else -%}
```bash
git commit --amend -F- <<'EOF'
<updated commit message if message was a finding; otherwise keep
 the improved message that still explains WHY and the approach>
EOF
```
{% endif %}

6. If the branch has already been pushed, or `HEAD` is not the
   commit under review, stop and report the error — do not amend.
7. Do NOT launch another review. Do NOT call `bump-round` (the
   orchestrator does that). Stop after amend succeeds.

## Requirement Context

<requirement>
{{ spec_content_concise }}
</requirement>

{% if completed_tasks_concise -%}
## Completed Steps

<completed-steps>
{{ completed_tasks_concise }}
</completed-steps>

{% endif -%}
## Current Task

<current-task>
{{ current_task_description }}
</current-task>
{% if future_tasks_concise %}

## Future Steps

{{ future_tasks_concise }}
{% endif %}
{% if spex_root %}

## Constraints

- **Do NOT stage or commit any files under `{{ spex_root }}/`.**
{% endif %}
