# Agent Guidelines

## Terminology

| Variable | Description |
|----------|-------------|
| `spex_skill_dir` | The skill installation directory (where `SKILL.md` lives). The global `spex` CLI is a symlink to `<spex_skill_dir>/scripts/spex`. |
| `spex_root` | Root directory for spec storage. Default: `.spex/` in the git worktree. Override via `.spex.toml` config file. |
| `specs_dir` | `<spex_root>/specs/` — active specs. |
| `archives_dir` | `<spex_root>/archives/` — archived specs. |

## About This Project

This project is a **coding agent skill** (invoked via `/spex`). All changes
to `SKILL.md`, commands, scripts, and references MUST conform to the Skills
Specification documented in `references/SKILLS-SPEC.md`.

## Language

- All code, comments, and commit messages MUST be written in English.
- The project maintains two README files: `README.md` (English) and
  `README.zh.md` (Chinese). When updating either file, the other MUST
  be updated to keep both versions consistent.

## Project Structure

- `skills/spex/SKILL.md` — Skill entry point (front-matter + instructions).
- `skills/spex/commands/` — Sub-command definitions (Markdown).
- `skills/spex/scripts/` — Executable helper scripts, written in Python (3.9+).
- `skills/spex/scripts/common.py` — Shared library (see API below).
- `skills/spex/references/` — Reference documentation loaded into context as needed.
- `tests/` — Unit tests.

## Naming Conventions

### Script Files

Script filenames in `skills/spex/scripts/` MUST use **underscores** (`_`) as the word
separator. Do NOT use hyphens in filenames. This follows the Python module
naming convention.

| Subcommand (user sees) | Script file |
|------------------------|-------------|
| `spex todo-helper` | `todo_helper.py` |
| `spex archive` | `archive.py` |

### CLI Display

CLI help and user-facing output MUST use **hyphens** (`-`) as the word
separator for multi-word subcommands. For example, the USAGE text shows
`spex todo-helper`, not `spex todo_helper`.

### CLI Parsing

The CLI accepts both hyphens and underscores as equivalent separators for
subcommand names. Internally, hyphens are normalized to underscores before
dispatch, to match Python module names and internal method names.
For example, `spex todo-helper` and `spex todo_helper` are equivalent.

### Excluded Modules

Public library modules (`common.py`, `cli.py`, `config.py`, `branch.py`,
`hooks.py`, `version.py`, `init.py`) are not subject to these naming rules.

## Shared Library (`skills/spex/scripts/common.py`)

| Function | Description |
|----------|-------------|
| `setup_logging(verbose)` | Configure logging to stderr with message-only format. |
| `logger` | Module-level Logger instance (`logging.getLogger("spex")`). |
| `clear_spex_root_cache()` | Clear the spex_root configuration cache. |
| `ensure_initialized(spex_root)` | Create spex_root dirs, templates, and .gitignore if missing. |
| `get_spex_root(workdir, require_git, auto_init)` | Resolve spex_root path (.spex.toml > default). |
| `get_spex_roots(workdir)` | Return all resolved spex_root directories (highest priority first). |
| `get_spex_tomls(workdir)` | Return discovered `.spex.toml` config paths. |
| `get_specs_dir(workdir)` | Return `<spex_root>/specs/`. |
| `get_archives_dir(workdir)` | Return `<spex_root>/archives/`. |
| `same_path(a, b)` | True if two path strings resolve to the same location (symlink-safe). |
| `load_meta(spec_dir)` | Load and parse `meta.json`; returns dict or `None`. |
| `get_spec_workdir(spec_dir)` | Read `workdir` from a spec's `meta.json`. |
| `load_todo(spec_dir)` | Load and parse `todo.json`; returns list or `None`. |
| `is_spec_completed(spec_dir)` | True if all tasks in `todo.json` have `completed_at`. |
| `has_undone_tasks(spec_dir)` | True if `todo.json` has incomplete items. |
| `get_todo_progress(spec_dir)` | Return `(completed_count, total_count)`. |
| `has_active_branch(spec_dir)` | True if `meta.json` has `spex_branch` and that git branch exists. |
| `find_completed_specs(specs_dir, ctx, force, all_projects)` | Return sorted list of completed spec paths, filtered by project context. |
| `atomic_write_json(path, data)` | Atomically write JSON via tempfile + `os.replace`. |
| `local_iso_timestamp()` | Current local time as ISO 8601 string. |
| `strip_date_prefix(spec_name)` | Remove `YYYY-MM-DD-HH-MM-` prefix from a spec name. |
| `strip_front_matter(content)` | Remove YAML front-matter block from template content. |
| `parse_front_matter_description(content)` | Extract `description` from YAML front-matter. |
| `get_spec_description(spec_dir)` | Return spec description from `meta.json` or `spec.md` front-matter. |
| `get_template(name, workdir)` | Return template content (front-matter stripped). |
| `resolve_spec_dir(spec_name, specs_dir)` | Resolve spec name to directory path (exact + fuzzy match). |
| `format_spec(spec_dir, verbose)` | Format a spec with progress icon, counts, and optional details. |
| `escape_xml_text(text)` | Escape &, <, > unconditionally in text content. |
| `escape_xml_preserving_entities(text)` | Escape XML chars while preserving existing entities. |
| `load_and_validate_todo_json(path, allow_empty)` | Load JSON, validate as list, exit on failure. |
| `validate_unique_ids(data)` | Check unique non-empty 'id' fields, exit on duplicates. |
| `find_matching_specs(name, dirs)` | Find spec directories matching a name (exact + fuzzy). |

## Logging Convention

Scripts use Python's `logging` module for all informational output
(status, progress, errors). stdout is reserved for programmatic data
(JSON, rendered content, paths).

- `setup_logging()` is called once in `skills/spex/scripts/spex` main(); subcommand
  scripts only need `from common import logger`.
- Scripts with `if __name__ == "__main__"` call `setup_logging()` there
  as a fallback for direct execution (e.g., in tests).
- Use `-d` / `--debug` global flag for DEBUG-level output.

| Usage | API |
|-------|-----|
| Info messages | `logger.info("Created branch '%s'", name)` |
| Warnings | `logger.warning("...")` |
| Errors | `logger.error("...")` |
| Data output (stdout) | `print(json.dumps(...))` / `print(rendered)` |

## Project Context (`skills/spex/scripts/config.py`)

| Symbol | Description |
|--------|-------------|
| `ProjectContext` | Dataclass with unified project metadata: `cwd`, `top_workdir`, `main_worktree`, `remote_url`, `branch`, `user_name`, `user_email`, `spex_tomls`, `config`, `spex_root`, `spex_roots`. |
| `get_project_context(workdir)` | Return a cached `ProjectContext` for the given workdir (default: cwd). |
| `clear_config_cache()` | Clear all module-level caches including `ProjectContext`. |

## Version Management

The version is stored in `skills/spex/pyproject.toml` and `SKILL.md`.
A dev-only `pyproject.toml` at the project root holds tooling config
(ruff, pytest, coverage) and mirrors the version field for sync checking.
Use the following Makefile targets:

- `make version` — print current version
- `make version-check` — verify sources are in sync (runs in `make check`)
- `make bump VERSION=x.y.z` — update version in all files

### Release SOP

When releasing a new version:

1. **Bump version**: Run `make bump VERSION=x.y.z`. This updates
   `skills/spex/pyproject.toml`, `pyproject.toml` (root), and `SKILL.md`
   via `skills/spex/scripts/version.py`.
2. **Update changelog**: Add a new `## x.y.z` section to `CHANGELOG.md`
   above the previous version. Group changes by heading: `### Features`,
   `### Bug Fixes`, `### Refactoring`.
3. **Commit**: Commit all changes with message
   `chore: bump version to x.y.z and update changelog`.
4. **Tag**: Create a tag `git tag vx.y.z` at the commit.
5. **Push**: Ask the user to manually push the commit and tag
   (`git push` and `git push --tags`).

Run `make check` before committing to verify version consistency and
pass all tests.

## Quality Checks

Before committing, `make check` runs automatically via a husky pre-commit hook. It executes:

1. `python3 skills/spex/scripts/version.py --check` — version consistency
2. `ruff check skills/spex/scripts/ tests/` — Python lint
3. `npx markdownlint-cli2` — Markdown lint
4. `pytest` — unit tests

If the pre-commit hook does not fire (e.g., hooks are not installed), run `make check` manually before creating a commit. Fix any failures before retrying.

## Test Suite

The test suite is split into two tiers:

| Target | Command | Tests | Duration |
|--------|---------|-------|----------|
| Fast (pre-commit) | `make check` | default | seconds |
| Full | `make check-all` | all | ~30s |

Tests in `tests/test_prompt.py` (except `TestBuildTaskContext`) are marked
`@pytest.mark.slow` because each one spawns `git init` subprocesses (~0.5–2s
per test). These are skipped by default via `addopts = ["-m", "not slow"]`
in `pyproject.toml`.

- `make check` / `pytest` — fast tier only (husky pre-commit hook)
- `make check-all` / `pytest -m ""` — runs all tests including slow
- `pytest -m slow` — runs slow tests only

New tests that involve git subprocess or other heavy I/O should be marked
`@pytest.mark.slow` to keep pre-commit feedback fast.
