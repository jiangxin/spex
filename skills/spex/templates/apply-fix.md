---
version: "0.1.0"
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
current implementation step. Address every **open** finding listed
below, then amend the original commit. Do NOT start a new review.

## Open Findings

The following findings are still open in `{{ review_file }}`
(round {{ review_round }}). Fix them one by one.

<open-findings>
{{ open_findings }}
</open-findings>

## Fix Procedure

1. For each open finding, implement the necessary code/test/message
   fix. Prefer minimal, targeted changes.
2. After fixing a finding, mark it complete:

```bash
{{ spex_skill_dir }}/scripts/spex review-helper --name {{ spec_name }} \
  edit --step {{ step_id }} --id <finding-id> --completed-at now
```

3. Run lint and relevant tests; proceed only when they pass.
4. **Amend** the original commit at `{{ commit_sha }}` (must still
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

5. If the branch has already been pushed, or `HEAD` is not the
   commit under review, stop and report the error — do not amend.
6. Do NOT launch another review. Stop after amend succeeds.

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
