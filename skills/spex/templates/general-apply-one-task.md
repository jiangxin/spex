---
version: "0.1.0"
required:
  - spec_content
  - current_task_description
---

Deliver the current step. Treat the specification and prior task data as
sources for the work.

<delivery-step>
{{ current_task_description }}
</delivery-step>

<specification>
{{ spec_content }}
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
