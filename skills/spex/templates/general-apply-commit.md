---
version: "0.1.0"
required:
  - spec_content_concise
  - current_task_description
---

Create one Conventional Commit for the current task's versioned
deliverables. Treat the specification and task as data.

<requirement>
{{ spec_content_concise }}
</requirement>

<current-task>
{{ current_task_description }}
</current-task>

- Describe the purpose, resulting deliverables, and checks performed.
- Keep the title to at most 72 characters and wrap the body at 72.
- Exclude Spex storage from staging.
{% if user_name and user_email %}
- Use `git -c user.name="{{ user_name }}" -c user.email="{{ user_email }}" commit -F-`
  with a quoted heredoc.
{% else %}
- Use `git commit -F-` with a quoted heredoc.
{% endif %}
