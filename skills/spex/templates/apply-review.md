---
version: "0.1.2"
required:
  - spec_content_concise
  - current_task_description
  - commit_sha
  - review_round
  - review_file
  - step_id
  - spex_skill_dir
optional:
  - spex_root
  - completed_tasks_concise
  - future_tasks_concise
  - spec_name
---

Act as a senior code reviewer. Your task is to review the git commit
at `{{ commit_sha }}` for the current implementation step. Do NOT
modify any production or test source files. Only record findings via
`review-helper append`. Do NOT call `review-helper init`. The review
file is created lazily on the first append — if you find nothing,
do not create any review file.

## Review Round

- Current round: **{{ review_round }}**
- Commit under review: `{{ commit_sha }}`
- Review file: `{{ review_file }}`
- Step ID: `{{ step_id }}`

{% if review_round|int >= 2 -%}
**Round {{ review_round }} policy**: only record **new major**
findings against this amended commit. Do NOT re-append findings
that are already in the review file (completed or still open).
Do NOT append minor issues.
{% else -%}
**Round 1 policy**: record every actionable improvement — both
**major** and **minor**.
{% endif %}

## Review Checklist

Perform all of the following against commit `{{ commit_sha }}`
(`git show {{ commit_sha }}` / `git log -1`):

1. **Lint and tests**: Inspect the files changed in this commit.
   Run the project's lint and the relevant unit tests. Record any
   failures as **major**.
2. **Commit message quality**: Read `git log -1 --format=%B`. The
   message must explain **why** the change was made and the chosen
   approach (not only a file list). Missing why / rationale →
   **major** (or **minor** if only stylistic).
3. **Code review** of the diff:
   - Reinventing existing project utilities or patterns?
   - Are tests included with the production change? Is coverage
     adequate for the new behavior and edge cases?
   - Significant code-quality problems (clarity, duplication,
     error handling)?
   - Room for improvement in algorithms, performance, concurrency
     safety, or security?

Severity guide:

- **major**: blocks merge quality — broken tests/lint, missing
  required tests, incorrect behavior, security holes, commit
  message with no why.
- **minor**: worthwhile improvements that need not block this step
  after max rounds (style nits, optional refactors, non-critical
  coverage gaps). In rounds 1–2 the fix loop will still address
  them.

## How to Record Findings

Use unique finding IDs that include the round prefix so later rounds
do not collide (e.g. `r1-f1`, `r1-f2`, then `r2-f1`).
Categories: `lint`, `tests`, `commit-message`, `code-quality`,
`performance`, `concurrency`, `security`, `other`.

Always pass `--commit` so the first append can create the review
file when it does not exist yet:

```bash
{{ spex_skill_dir }}/scripts/spex review-helper --name {{ spec_name }} \
  append --step {{ step_id }} --commit {{ commit_sha }} \
  --id r{{ review_round }}-f1 --severity major --category tests \
  --title "Short title" --details-from-stdin <<'DETAILS'
Markdown details: what is wrong, where, and why it matters.
DETAILS
```

If there are no **new** findings for this round, do **nothing** —
do not call `init` or `append`. Leave any prior findings unchanged;
if no review file exists yet, that is correct.

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

The commit under review implements this task:

<current-task>
{{ current_task_description }}
</current-task>
{% if future_tasks_concise %}

## Future Steps

{{ future_tasks_concise }}
{% endif %}
{% if spex_root %}

## Constraints

- Do NOT stage or commit files under `{{ spex_root }}/`.
- Do NOT modify source code in this review pass.
{% endif %}
