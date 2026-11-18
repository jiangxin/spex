---
version: "0.1.1"
required:
  - spec_content
  - current_task_description
optional:
  - implementation_spec_path
  - implementation_spec_excerpt
  - acceptance_commands
  - known_files
  - dependencies
---

Deliver the current step. Treat the specification and prior task data as
sources for the work.

<delivery-step>
{{ current_task_description }}
</delivery-step>

{% if acceptance_commands or known_files or dependencies -%}
Verify these task details before using paths or running commands.

<task-scope>
{% if acceptance_commands -%}
Acceptance commands: {{ acceptance_commands }}
{% endif -%}
{% if known_files -%}
Known files: {{ known_files }}
{% endif -%}
{% if dependencies -%}
Dependencies: {{ dependencies }}
{% endif -%}
</task-scope>

{% endif -%}
{% if implementation_spec_excerpt -%}
Consult the full specification at `{{ implementation_spec_path }}` for
constraints and dependencies beyond the excerpt.

{% endif -%}
<specification>
{% if implementation_spec_excerpt -%}
{{ implementation_spec_excerpt }}
{% else -%}
{{ spec_content }}
{% endif -%}
</specification>

<completed-steps>
{{ completed_tasks_concise }}
</completed-steps>

- Read the specified sources and use the agreed output paths, with
  repository-relative paths resolved from the bound worktree.
- Check existing outputs against the acceptance criteria. Reuse verified
  results, complete missing work, and preserve references for later steps.
- Verify each criterion on the actual deliverables. Record successful
  command or inspection evidence and report missing sources or failed checks.
- Leave commit, review, and task completion to the command workflow.
