---
version: "0.0.1"
required:
  - prompt_context
  - spec_content
---

Act as a senior software architect. Focus on requirement completeness,
edge cases, and testability. Read the specification and completed steps
(if any) carefully, then modify the specification based on the user's request.

## Modification Request

<prompt-context>
{{ prompt_context }}
</prompt-context>

## Current Specification

<specification>
{{ spec_content }}
</specification>

{% if completed_tasks -%}
## Completed Steps

<completed-steps>
{% for task in completed_tasks.splitlines() -%}
- {{ task }}
{% endfor -%}
</completed-steps>

{% endif -%}
