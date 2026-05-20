# Agent Guidelines

## About This Project

This project is a **Claude Code skill** (invoked via `/sdd`). All changes to
`SKILL.md`, commands, scripts, and references MUST conform to the Claude Code
Skills Specification documented in `references/SKILLS-SPEC.md`.

## Language

- All code, comments, and commit messages MUST be written in English.

## Project Structure

- `SKILL.md` — Skill entry point (front-matter + instructions).
- `commands/` — Sub-command definitions (Markdown).
- `scripts/` — Executable helper scripts, written in Python (3.9+).
- `references/` — Reference documentation loaded into context as needed.
- `tests/` — Unit tests.

## Quality Checks

Before committing, `make check` runs automatically via a husky pre-commit hook. It executes:

1. `ruff check scripts/ tests/` — Python lint
2. `npx markdownlint-cli2` — Markdown lint
3. `pytest` — unit tests

If the pre-commit hook does not fire (e.g., hooks are not installed), run `make check` manually before creating a commit. Fix any failures before retrying.
