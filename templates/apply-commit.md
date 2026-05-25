---
version: "0.0.1"
required:
  - spec_content
  - next_task_text
---

## Goal

Stage the relevant file changes and create a single git commit.

## Commit Message Guidelines

- Follow the **Conventional Commits** format.
- Wrap lines at 72 characters.
- Convey WHY the change was made and the core technical reasoning —
  not an exhaustive list of HOW things were modified.
- Derive context from the Specification below; derive scope from the
  Current Task.
- Use HereDoc to pass the message:
  `git commit -F- <<-EOF`
{% if spex_root -%}
- **Do NOT stage or commit any files under `{{ spex_root }}/`.**
{% endif %}

## References

### Specification

<specification>
{{ spec_content }}
</specification>

{% if completed_tasks -%}
### Completed Steps

<completed-steps>
{% for task in completed_tasks.splitlines() -%}
- {{ task }}
{% endfor -%}
</completed-steps>

{% endif -%}
### Current Task

The commit is for implementing the following task:

<current-task>
{{ next_task_text }}
</current-task>
{% if future_tasks %}

### Future Steps

The following steps have NOT been implemented yet.
Do NOT include them in the commit message.

{{ future_tasks }}
{% endif %}
</output>
