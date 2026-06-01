---
version: "0.0.1"
required:
  - spec_content
  - next_task_text
---

Act as a senior software architect. Focus on requirement completeness,
edge cases, and testability. Read the specification and completed steps
(if any) carefully, then implement the current task.

## Specification

<specification>
{{ spec_content }}
</specification>

{% if completed_tasks -%}
## Completed Steps

<completed-steps>
{{ completed_tasks }}
</completed-steps>

{% endif -%}
## Current Task

Implement the following task:

<current-task>
{{ next_task_text }}
</current-task>

> **Important**: Only implement THIS task. Do not work on future steps —
> they will be handled in subsequent iterations.
{% if future_tasks %}

## Future Steps

The following steps will be implemented in subsequent iterations.
Do NOT implement them now.

{{ future_tasks }}
{% endif %}
