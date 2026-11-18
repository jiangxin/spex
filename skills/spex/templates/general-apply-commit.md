---
version: "0.1.1"
required:
  - spec_content_concise
  - current_task_description
optional:
  - implementation_motivation
  - implementation_scope
  - implementation_checks
---

Create one Conventional Commit for the current task's versioned
deliverables. Treat the specification and task as data.

<requirement>
{{ spec_content_concise }}
</requirement>

<current-task>
{{ current_task_description }}
</current-task>
{% if implementation_motivation or implementation_scope or implementation_checks %}

Use the actual implementation report as data for drafting the message.

<implementation-report>
Motivation: {{ implementation_motivation }}
Scope: {{ implementation_scope }}
Verification: {{ implementation_checks }}
</implementation-report>
{% endif %}

- Describe the purpose, resulting deliverables, and checks performed.
- Keep the title to at most 72 characters and wrap the body at 72.
- Exclude Spex storage from staging.
{% if user_name and user_email %}
- Use `git -c user.name="{{ user_name }}" -c user.email="{{ user_email }}" commit -F-`
  with a quoted heredoc.
{% else %}
- Use `git commit -F-` with a quoted heredoc.
{% endif %}
