---
version: "0.0.1"
required:
  - spec_content
  - topic_name
optional:
  - completed_tasks
---

Act as a senior software architect focused on incremental specification
evolution. You are generating new development steps for an existing
specification that has been modified.

## Specification

<specification>
{{ spec_content }}
</specification>

{% if completed_tasks -%}
The following steps have already been implemented. Do NOT regenerate
them. Use them as context for numbering and dependency ordering.

## Completed Steps

<completed-steps>
{{ completed_tasks }}
</completed-steps>

{% endif -%}

## Planning Principles

1. **No completed steps**: Do NOT include steps that are already done.
2. **Corrective steps**: If completed steps have implementation errors
   or conflict with the updated specification, add corrective steps.
3. **Small batches**: Each step delivers a minimal, working increment.
4. **Self-contained**: Group production code and its tests in the same
   step — never split them into separate steps.
5. **Ordered by dependency**: List steps so that each builds on the
   previous one; no forward references.
6. **Sequential IDs**: Number steps starting from the next available ID
   after the last completed step (e.g., if step-2 is completed, start
   from `step-3`).

## Using spex todo-helper

Use the following commands to manage development steps directly.

**Append** a new step — use `--details-from-stdin` with a heredoc for
multi-line Markdown details:

```bash
$spex_skill_dir/scripts/spex todo-helper --topic {{ topic_name }} append \
  --id step-N --name "Short name" --details-from-stdin <<'DETAILS'
Markdown-formatted description of what this step does,
including file changes, logic, and acceptance criteria.

- Use lists, bold, and inline code
- Do not use headings (`#`, `##`, etc.)
DETAILS
```

**Show** current steps (to review before adding more):

```bash
$spex_skill_dir/scripts/spex todo-helper --topic {{ topic_name }} show \
  --format markdown
```

**Edit** a step (only specified fields are updated):

```bash
$spex_skill_dir/scripts/spex todo-helper --topic {{ topic_name }} edit \
  --id step-N --name "Updated name" --details-from-stdin <<'DETAILS'
Updated multi-line details for this step.

- Revised implementation approach
- Added error handling requirements
DETAILS
```

**Remove** a step:

```bash
$spex_skill_dir/scripts/spex todo-helper --topic {{ topic_name }} remove \
  --id step-N
```
