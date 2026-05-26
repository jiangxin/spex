---
version: "0.0.1"
required:
  - spec_content
---

Act as a senior software architect. You are generating new development
steps (todo.xml) for an existing specification that has been modified.
Only generate NEW steps — completed steps already exist in todo.json
and will be preserved separately.

## Specification

<specification>
{{ spec_content }}
</specification>

{% if completed_tasks -%}
## Completed Steps (already in todo.json, do NOT regenerate)

<completed-steps>
{% for task in completed_tasks.splitlines() -%}
- {{ task }}
{% endfor -%}
</completed-steps>

{% endif -%}

## Instructions

Generate ONLY the new development steps needed to complete this spec,
in `todo.xml` format. Follow these rules:

1. **Do NOT include completed steps**: They already exist in todo.json.
   Only generate steps for the remaining work.
2. **Corrective steps**: If prior completed steps have implementation
   errors or now conflict with the updated spec, add corrective steps.
3. **Small batches**: each step delivers a minimal, working increment.
4. **Self-contained**: group production code and its tests in the same
   step -- never split them into separate steps.
5. **Ordered by dependency**: list steps so that each builds on the
   previous one; no forward references.

Write the new steps in `todo.xml` format:

```xml
<steps>
  <step>
    <step-id>step-N</step-id>
    <step-name>Short name for the step</step-name>
    <step-markdown-details>
Markdown-formatted description of what this step does,
including file changes, logic, and acceptance criteria.

- Use lists, bold, and inline code
- Do not use headings (`#`, `##`, etc.)
    </step-markdown-details>
  </step>
</steps>
```

**CRITICAL — the xml2json parser will reject any deviation from this
structure:**

- Root element **MUST** be `<steps>` (not `<tasks>`, `<todo>`, etc.).
- Each step **MUST** be wrapped in `<step>` (not `<task>`, `<item>`, etc.).
- Each `<step>` **MUST** contain exactly three children in order:
  `<step-id>`, `<step-name>`, `<step-markdown-details>`.
- Number steps sequentially starting from the next available step ID
  after completed steps (e.g., if step-1 and step-2 are completed,
  start from `step-3`).
