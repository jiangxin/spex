# Agent Guidelines

## Terminology

| Variable | Description |
|----------|-------------|
| `spex_skill_dir` | The skill installation directory (where `SKILL.md` lives). The global `spex` CLI is a symlink to `<spex_skill_dir>/scripts/spex`. |
| `spex_root` | Root directory for spec storage. Default: `.spex/` in the git worktree. Override via `.spex.toml` config file. |
| `specs_dir` | `<spex_root>/specs/` — active spec topics. |
| `archives_dir` | `<spex_root>/archives/` — archived spec topics. |

## About This Project

This project is a **Claude Code skill** (invoked via `/spex`). All changes to
`SKILL.md`, commands, scripts, and references MUST conform to the Claude Code
Skills Specification documented in `references/SKILLS-SPEC.md`.

## Language

- All code, comments, and commit messages MUST be written in English.

## Project Structure

- `SKILL.md` — Skill entry point (front-matter + instructions).
- `commands/` — Sub-command definitions (Markdown).
- `scripts/` — Executable helper scripts, written in Python (3.9+).
- `scripts/common.py` — Shared library (see API below).
- `references/` — Reference documentation loaded into context as needed.
- `tests/` — Unit tests.

## Shared Library (`scripts/common.py`)

| Function | Description |
|----------|-------------|
| `get_spex_root(workdir, require_git, auto_init)` | Resolve spex_root path (.spex.toml > default). |
| `ensure_initialized(spex_root)` | Ensure spex_root dirs, templates, and .gitignore are set up. |
| `resolve_topic_dir(topic_name, specs_dir)` | Resolve topic name to directory path (exact + fuzzy match). |
| `get_specs_dir(workdir)` | Return `<spex_root>/specs/`. |
| `get_archives_dir(workdir)` | Return `<spex_root>/archives/`. |
| `get_current_workdir()` | Return git toplevel of cwd, or `None` if not in a repo. |
| `same_path(a, b)` | True if two path strings resolve to the same location (symlink-safe). |
| `get_topic_workdir(topic_dir)` | Read `workdir` from a topic's `meta.json`. |
| `load_meta(topic_dir)` | Load and parse `meta.json`; returns dict or `None`. |
| `load_todo(topic_dir)` | Load and parse `todo.json`; returns list or `None`. |
| `is_topic_completed(topic_dir)` | True if all tasks in `todo.json` have `completed_at`. |
| `has_undone_tasks(topic_dir)` | True if `todo.json` has incomplete items. |
| `get_todo_progress(topic_dir)` | Return `(completed_count, total_count)`. |
| `atomic_write_json(path, data)` | Atomically write JSON via tempfile + `os.replace`. |
| `get_template(name, workdir)` | Return template content (front-matter stripped). |
| `get_spec_template(workdir)` | Shortcut for `get_template("spec.md")`. |
| `local_iso_timestamp()` | Current local time as ISO 8601 string. |
| `clear_spex_root_cache()` | Reset the internal spex_root cache. |

## Quality Checks

Before committing, `make check` runs automatically via a husky pre-commit hook. It executes:

1. `ruff check scripts/ tests/` — Python lint
2. `npx markdownlint-cli2` — Markdown lint
3. `pytest` — unit tests

If the pre-commit hook does not fire (e.g., hooks are not installed), run `make check` manually before creating a commit. Fix any failures before retrying.

## Test Suite

The test suite is split into two tiers:

| Target | Command | Tests | Duration |
|--------|---------|-------|----------|
| Fast (pre-commit) | `make check` | 372 (default) | ~4s |
| Full | `make check-all` | 404 (all) | ~32s |

Tests in `tests/test_prompt.py` (except `TestBuildTaskContext`) are marked
`@pytest.mark.slow` because each one spawns `git init` subprocesses (~0.5–2s
per test). These are skipped by default via `addopts = ["-m", "not slow"]`
in `pyproject.toml`.

- `make check` / `pytest` — fast tier only (husky pre-commit hook)
- `make check-all` / `pytest -m ""` — runs all tests including slow
- `pytest -m slow` — runs slow tests only

New tests that involve git subprocess or other heavy I/O should be marked
`@pytest.mark.slow` to keep pre-commit feedback fast.
