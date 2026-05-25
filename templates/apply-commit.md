---
version: "0.0.1"
required:
  - "spex_root"
---

Create a git commit for the changes:

- Follow the Conventional Commits format.
- Wrap commit message lines at 72 characters.
- Use HereDoc format to run git commit commands, such as:
  `git commit -F- <<-EOF` to create a multi-line commit message.
{% if spex_root -%}
- **Do NOT stage or commit any files under `{{ spex_root }}/`.**
{% endif %}
{% if prompt_context -%}

The commit is based on the following requirement — implementing the
Current Task caused these code changes. The commit message should
convey the background, WHY the change was made, and core technical
reasoning — not an exhaustive description of HOW things were modified.

<commit-context>
{{ prompt_context }}
</commit-context>
{% endif -%}
