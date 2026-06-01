---
version: "0.1.0"
required:
  - spec_content
  - next_task_text
optional:
  - spex_root
  - completed_tasks_concise
  - future_tasks_concise
---

Act as a senior software engineer creating a precise, meaningful git
commit. Your task is to stage the relevant file changes and create a
single commit with a well-crafted message.

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

## Specification

The following is the full specification. Use it as the authoritative
reference for understanding the project scope and deriving commit
context.

<specification>
{{ spec_content }}
</specification>

{% if completed_tasks_concise -%}
## Completed Steps

The following steps have already been implemented and committed. Use
them to understand prior work — the commit message can reference this
context but should not duplicate their content.

<completed-steps>
{{ completed_tasks_concise }}
</completed-steps>

{% endif -%}
## Current Task

The commit is for implementing the following task. The commit message
should describe THIS work specifically.

<current-task>
{{ next_task_text }}
</current-task>
{% if future_tasks_concise %}

## Future Steps

The following steps have NOT been implemented yet.
Do NOT include them in the commit message.

{{ future_tasks_concise }}
{% endif %}
