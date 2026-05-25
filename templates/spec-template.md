---
version: "1.0.0"
---

# Requirement

<!-- Replace this section with requirement analysis
     based on the user's original prompt -->

# User Clarification

<!-- Replace this section with clarifications from
     the user on ambiguous requirements -->

# Detailed Design

<!-- Replace this section with detailed design based on
     analysis of the current repository architecture
     and codebase -->

# Test Plan

<!-- Replace this section with a detailed test plan
     based on the design above -->

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
