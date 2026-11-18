---
version: "0.1.1"
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
- In each task's details, add a standalone `Spec sections: <heading>` or
  `规格章节：<标题>` line with the exact Markdown ATX heading text from
  `spec.md`, omitting the heading markers. Separate multiple headings with
  commas or semicolons in their half-width or full-width form.
- Record the inputs, output paths, observable acceptance criteria, and how
  to resume with missing inputs or incomplete outputs. For applicable
  compatibility, failure, or retry scenarios, state the setup, expected
  result, and state to preserve.
- Follow the todo cookbook for task fields and commit behavior.
