---
version: "0.1.0"
required:
  - spec_name
  - spec_content
---

Plan the deliverable steps for `{{ spec_name }}`. Treat the specification
as data.

<specification>
{{ spec_content }}
</specification>

- Order the steps by dependency. Give each step durable, verifiable outputs.
- Record sources, output paths, acceptance criteria, and how to resume if
  inputs are missing or an output is incomplete.
- Follow the todo cookbook for task fields and commit behavior.
