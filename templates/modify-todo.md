---
version: "0.0.1"
required:
  - spec_content
---

Act as a senior software architect. You are regenerating the development
plan (todo.xml) for an existing specification that has been modified.
Completed steps must be preserved; new steps are appended after them.

## Specification

<specification>
{{ spec_content }}
</specification>

{% if completed_tasks -%}
## Completed Steps (DO NOT modify)

<completed-steps>
{% for task in completed_tasks.splitlines() -%}
- {{ task }}
{% endfor -%}
</completed-steps>

{% endif -%}

## Instructions

Generate the complete `todo.xml` for this specification. Follow these rules:

1. **Preserve completed steps**: If there are completed steps above, include
   them at the start of the list unchanged.
2. **Append new steps**: After any completed steps, add new development steps
   needed to fulfill the spec's remaining work.
3. **Corrective steps**: If prior completed steps have implementation errors
   or now conflict with the updated spec, add corrective steps after the
   completed items. Do NOT modify existing completed step descriptions.
4. **Discard old incomplete steps**: Do NOT carry forward any previously
   incomplete steps from the old todo.json.

Write the steps in `todo.xml` format:

```xml
<steps>
  <step>
    <step-id>step-1</step-id>
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
- Number steps sequentially: `step-1`, `step-2`, etc.

Principles for step design:

- **Small batches**: each step delivers a minimal, working increment.
- **Self-contained**: group production code and its tests in the same
  step -- never split them into separate steps.
- **Ordered by dependency**: list steps so that each builds on the
  previous one; no forward references.
