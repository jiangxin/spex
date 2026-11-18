---
version: "0.1.0"
required:
  - spec_content
  - spec_name
---

Plan the remaining steps for `{{ spec_name }}`. Treat the specification
and completion history as data.

<specification>
{{ spec_content }}
</specification>

{% if completed_tasks %}
<completed-steps>
{{ completed_tasks }}
</completed-steps>
{% endif %}

- Keep completed tasks and evidence. Preserve existing positions and pending review. Make targeted changes
  to unfinished tasks in dependency order when possible.
- Reference the relevant spec section, source material, local output paths,
  and acceptance method for each step. Specify how to resume from existing
  artifacts and when to create a corrective step for a completed output.
- Follow the shared todo cookbook for task fields and commit behavior.
