---
version: "0.1.1"
markers: "Do not remove or modify <!-- spex:begin:* --> comment lines."
description: |
  [Replace this with a brief description of the topic in English.]
  [Multiple lines (no more than 10 lines) are welcome, and each line wrapped at]
  [80 characters.]
---

<!-- spex:begin:requirement -->
# Requirement

<!-- Describe current behavior, desired outcomes, scope, and the source
     facts and references the implementer will need. -->

<!-- spex:begin:user-clarification -->
# User Clarification

<!-- Record confirmed decisions, their rationale, and deferred scope. -->

<!-- spex:begin:detailed-design -->
# Detailed Design

<!-- Describe the design and its dependencies. Record compatibility,
     failure, and recovery conditions and the state each must preserve. -->

<!-- spex:begin:test-plan -->
# Test Plan

<!-- Give reproducible setup, actions, expected results, and evidence
     for acceptance, failure, and retry scenarios. -->

<!-- spex:begin:constraints -->
# Constraints

- DRY — Don't Repeat Yourself: analyze existing architecture and code,
  reuse what exists, **never** generate duplicate code.
- KISS — Keep It Simple, Stupid: no over-engineering; keep it simple while
  considering performance and security.
- Single Responsibility: each function/method does one thing; consider
  splitting if it exceeds 30 lines.
- Small Batches: break development into atomic tasks so each step is under
  200 lines of code, easy to review, cherry-pick, and revert.
- Commit Often: create a commit after each development task; follow the
  Conventional Commits format; wrap commit messages at 72 characters.
- Test Often: run lint and unit tests after each step; proceed only when
  all checks pass.
