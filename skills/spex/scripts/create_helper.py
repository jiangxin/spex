"""Helper utilities for spec creation."""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from cli import ArgumentParser, nonempty_spec_name
from common import (
    DEFAULT_SPEX_BRANCH_PREFIX,
    SpecMeta,
    atomic_write_json,
    get_spex_root,
    logger,
    resolve_spec_dir,
    strip_date_prefix,
    wrap_text,
)
from task_mode import SOFTWARE, TASK_MODES, template_filename

SPEC_NAME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
DATE_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-")
# Short create name (no date prefix): [a-z0-9][a-z0-9-]* and ≤31 bytes.
CREATE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_CREATE_NAME_BYTES = 31
MAX_SPEC_NAME_BYTES = 64


def _do_modify_session(args):
    import modify_session

    try:
        specs_dir = Path(get_spex_root(auto_init=False)) / "specs"
        spec_dir = resolve_spec_dir(args.name, specs_dir=specs_dir)
        modify_session.begin(spec_dir)
        if args.stdin_flag:
            from meta_helper import save_modify_request

            save_modify_request(spec_dir)
    except KeyboardInterrupt:
        if not args.stdin_flag:
            raise
        sys.exit("Modify request save interrupted. Check the spec state before starting again.")
    except (OSError, RuntimeError, ValueError) as exc:
        sys.exit(str(exc))


def validate_create_name(name: str, description: str) -> dict:
    """Validate Phase 3 create name/description; return normalized fields.

    Raises ValueError with a human-readable reason on failure.
    """
    if name is None or not str(name).strip():
        raise ValueError("name is required and must be non-empty.")
    name = str(name).strip()

    if DATE_PREFIX_PATTERN.match(name):
        raise ValueError(
            f"name '{name}' must not include a YYYY-MM-DD-HH-MM- date "
            "prefix; prepare-spec adds it."
        )

    if not CREATE_NAME_PATTERN.match(name):
        raise ValueError(
            f"invalid name '{name}'. Must match [a-z0-9][a-z0-9-]* "
            "(lowercase letters, digits, hyphens; must start with "
            "alphanumeric)."
        )

    name_bytes = len(name.encode("utf-8"))
    if name_bytes > MAX_CREATE_NAME_BYTES:
        raise ValueError(
            f"name '{name}' is {name_bytes} bytes; must be at most "
            f"{MAX_CREATE_NAME_BYTES} bytes."
        )

    if description is None:
        raise ValueError("description is required and must be non-empty.")
    description = str(description)
    if not description.strip():
        raise ValueError("description is required and must be non-empty.")
    if "\n" in description or "\r" in description:
        raise ValueError(
            "description must be a single line (no embedded newlines)."
        )

    return {"name": name, "description": description.strip()}


def _do_validate_name(args):
    """CLI: validate create name/description; print JSON on success."""
    try:
        result = validate_create_name(args.name, args.description)
    except ValueError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    print(json.dumps(result))


def _require_spex_root() -> str:
    """Return spex_root or exit with an error."""
    import config as cfg

    spex_root = cfg.get_project_context().spex_root
    if not spex_root:
        logger.error(
            "Error: cannot determine spex_root. "
            "Configure .spex.toml with spex_root.",
        )
        sys.exit(1)
    return spex_root


def _begin_temporary_log() -> tuple[str, Path]:
    """Create a fresh directory, retrying an ID collision."""
    from debug_log import temporary_log_dir

    spex_root = _require_spex_root()
    for _ in range(10):
        log_id = secrets.token_hex(16)
        directory = temporary_log_dir(spex_root, log_id)
        directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            continue
        return log_id, directory
    raise OSError("could not allocate a unique temporary log ID")


def _do_begin_log(log_route) -> None:
    from debug_log import DEBUG_LOG_NAME

    try:
        log_id, directory = _begin_temporary_log()
    except (OSError, ValueError) as exc:
        sys.exit(f"Error starting create log: {exc}")
    if log_route is not None:
        log_route.directory = directory
    print(json.dumps({"log_id": log_id, "log_path": str(directory / DEBUG_LOG_NAME)}))


def _do_end_log(args) -> None:
    from debug_log import temporary_log_dir

    try:
        directory = temporary_log_dir(_require_spex_root(), args.log_id)
        shutil.rmtree(directory)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        sys.exit(f"Error ending create log: {exc}")


def _append_create_debug_anchor(log_path: Path, line: str) -> None:
    """Append a CREATE debug anchor; propagate OSError (hard success signal).

    Unlike APPLY's soft ``append_debug_anchor`` (tee best-effort), CREATE
    handoff/post-action anchors must fail loud so prepare can restore
    its temporary logs if the prepare-ok marker cannot be written.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    text = line if line.endswith("\n") else f"{line}\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _append_prepare_anchor(spec_dir: Path, spec_name: str) -> tuple[Path, int, bytes] | None:
    from debug_log import debug_enabled, prepare_spec_log_parent, spec_debug_log_path

    if debug_enabled(sys.argv):
        log_path = spec_debug_log_path(spec_dir)
        if not prepare_spec_log_parent(log_path):
            raise OSError(f"Cannot write spec log: {log_path}")
        offset = log_path.stat().st_size if log_path.exists() else 0
        anchor = f"===== CREATE prepare-spec ok name={spec_name} =====\n"
        _append_create_debug_anchor(log_path, anchor)
        return log_path, offset, anchor.encode("utf-8")
    return None


def _remove_prepare_anchor(log_path: Path, offset: int, anchor: bytes) -> None:
    """Undo the marker before returning the logs of a failed preparation."""
    try:
        with log_path.open("r+b") as handle:
            handle.seek(offset)
            if handle.read(len(anchor)) == anchor:
                tail = handle.read()
                handle.seek(offset)
                handle.write(tail)
                handle.truncate()
    except OSError as err:
        logger.warning("Could not remove prepare marker from %s: %s", log_path, err)


def create_spec(spec, specs_dir, auto_prefix=True):
    """Create a spec directory under specs_dir.

    Returns (spec_name, spec_dir) tuple.
    Raises ValueError on invalid input, FileExistsError if spec exists.
    """
    specs_dir = Path(specs_dir)

    if not DATE_PREFIX_PATTERN.match(spec) and auto_prefix:
        prefix = datetime.now().strftime("%Y-%m-%d-%H-%M")
        spec = f"{prefix}-{spec}"

    if not SPEC_NAME_PATTERN.match(spec):
        raise ValueError(
            f"invalid spec name '{spec}'. "
            "Must match YYYY-MM-DD-HH-MM-<name> with [a-z0-9-]."
        )

    if len(spec.encode("utf-8")) > MAX_SPEC_NAME_BYTES:
        raise ValueError(f"spec name '{spec}' exceeds {MAX_SPEC_NAME_BYTES} bytes.")

    spec_dir = specs_dir / spec
    if spec_dir.exists():
        raise FileExistsError(f"'{spec}' already exists, use a different name.")

    specs_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir()
    return (spec, spec_dir)


def is_incomplete_spec_dir(spec_dir: Path) -> bool:
    """True when a directory exists but has no ``spec.md`` yet.

    Prefer :func:`is_incomplete_spec_stub` before deleting; this helper only
    answers whether ``spec.md`` is missing.
    """
    path = Path(spec_dir)
    return path.is_dir() and not (path / "spec.md").is_file()


def is_incomplete_spec_stub(
    spec_dir: Path,
    specs_dir: Path | str | None = None,
) -> bool:
    """True for a prepare-spec stub that is safe to discard.

    Requires a dated spec directory name, no ``spec.md``, and either an empty
    directory or only stub allowlist files with ``meta.json`` present. When
    ``specs_dir`` is set, the path must be a direct child of that directory.
    """
    path = Path(spec_dir)
    if path.is_symlink() or not path.is_dir() or (path / "spec.md").is_file():
        return False
    if not SPEC_NAME_PATTERN.match(path.name):
        return False
    if specs_dir is not None:
        parent = path.parent.resolve()
        expected = Path(specs_dir).resolve()
        if parent != expected:
            return False
    entries = list(path.iterdir())
    if not entries:
        return True
    from debug_log import spec_logs_only

    meta = path / "meta.json"
    return meta.is_file() and not meta.is_symlink() and spec_logs_only(
        [entry for entry in entries if entry.name != "meta.json"],
    )


def discard_incomplete_spec(
    spec_dir: Path,
    specs_dir: Path | str | None = None,
) -> bool:
    """Remove a prepare-spec stub directory.

    Returns True if the directory was removed. Raises ValueError when the
    path exists but is not a safe stub (has ``spec.md``, unexpected files,
    bad name, or wrong parent under ``specs_dir``).
    """
    path = Path(spec_dir)
    if not path.exists():
        return False
    if not path.is_dir():
        raise ValueError(f"Not a spec directory: {path}")
    if (path / "spec.md").is_file():
        raise ValueError(
            f"Refusing to discard '{path.name}': spec.md already exists"
        )
    if not is_incomplete_spec_stub(path, specs_dir=specs_dir):
        raise ValueError(
            f"Refusing to discard '{path.name}': not a prepare-spec stub "
            "(require dated name under specs/, empty or meta.json-only "
            "with optional debug.log files)"
        )
    shutil.rmtree(path)
    return True


def _write_meta(spec_dir, ctx, prompt, timestamp, description="", *, task_mode=SOFTWARE):
    """Write meta.json into spec_dir with project context and prompt."""
    workdir = str(ctx.top_workdir) if ctx.in_git_workdir() else ""
    main_worktree = str(ctx.main_worktree) if ctx.main_worktree else workdir
    meta = SpecMeta(
        name=strip_date_prefix(Path(spec_dir).name),
        workdir=workdir,
        main_worktree=main_worktree,
        remote_url=ctx.remote_url,
        branch=ctx.branch,
        user_name=ctx.user_name,
        user_email=ctx.user_email,
        created_at=timestamp,
        prompts=[{"text": prompt, "timestamp": timestamp}] if prompt else [],
        description=wrap_text(description) if description else "",
        use_git_worktree=bool(ctx.config.get("use_git_worktree", False)),
        task_mode=task_mode,
    )
    meta_path = Path(spec_dir) / "meta.json"
    atomic_write_json(meta_path, meta.to_dict())


def list_working_tree_dirty_paths(
    cwd: str | Path | None = None,
) -> list[str]:
    """Return relative dirty paths from ``git status --porcelain``.

    Reuses ``apply_helper.parse_porcelain_paths`` for path extraction.
    Raises ``subprocess.CalledProcessError`` on git failure.
    """
    from apply_helper import parse_porcelain_paths

    porcelain = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        text=True,
        stderr=subprocess.PIPE,
    )
    paths: list[str] = []
    for line in porcelain.splitlines():
        if line:
            paths.extend(parse_porcelain_paths(line))
    return paths


def validate_create_branch(
    config: dict, cwd: str | Path | None = None,
) -> str:
    """Validate whether branch creation is enabled and feasible.

    Prints errors to stderr and exits on failure.
    Returns the current branch name on success.
    """
    from branch import get_current_branch, switch_branch

    try:
        current = get_current_branch(cwd)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error: cannot determine current branch: {e}")
        sys.exit(1)
    except RuntimeError as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

    if not bool(config["branch_management"]):
        logger.info("Note: branch management is not enabled in .spex.toml, "
                    "will not create new branch for spec.")
        return current

    main_branch = config["main_branch_name"]
    if main_branch and current != main_branch:
        try:
            dirty_paths = list_working_tree_dirty_paths(cwd)
        except subprocess.CalledProcessError as e:
            logger.error(
                "Error: cannot check working tree status: %s",
                e.stderr.strip() if e.stderr else e,
            )
            sys.exit(1)
        if dirty_paths:
            logger.error(
                "Working tree is dirty; refusing to switch to '%s'. "
                "Commit or stash first, or switch manually: %s",
                main_branch,
                dirty_paths,
            )
            sys.exit(1)
        logger.warning(
            f"Warning: current branch '{current}' does not match "
            f"main_branch_name '{main_branch}'. "
            f"Switching to '{main_branch}'...",
        )
        try:
            switch_branch(main_branch, cwd)
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Error: failed to switch to '{main_branch}': "
                f"{e.stderr.strip() or e}",
            )
            sys.exit(-1)
        logger.info(f"Switched to branch '{main_branch}'.")
        return main_branch

    if current.startswith(DEFAULT_SPEX_BRANCH_PREFIX):
        logger.error(
            f"Error: current branch '{current}' starts with "
            f"'{DEFAULT_SPEX_BRANCH_PREFIX}'.\n"
            f"Hint: configure 'main_branch_name' in .spex.toml "
            f"to enable automatic branch switching.",
        )
        sys.exit(1)

    return current


def cli_create_validate() -> None:
    """CLI: validate branch creation feasibility."""

    import config as cfg

    ctx = cfg.get_project_context()
    current = validate_create_branch(ctx.config, cwd=ctx.main_worktree)
    if current:
        logger.info(f"Valid: currently on branch '{current}'")


def _do_precheck(args, log_route=None) -> None:
    """Validate create branch state, then optionally allocate a log."""
    cli_create_validate()
    if args.begin_log:
        _do_begin_log(log_route)


def _do_prepare_spec(args, log_route=None):
    try:
        if args.log_id is not None and log_route is None:
            from debug_log import TemporaryLogRoute, temporary_log_dir

            log_route = TemporaryLogRoute(temporary_log_dir(_require_spex_root(), args.log_id))
        source = log_route.directory if log_route is not None else None
        exit_code = _prepare_spec(args, log_route)
    except (Exception, SystemExit) as err:
        logger.error("Error preparing spec: %s", err)
        if args.log_id is not None and log_route is not None and source is not None:
            _report_prepare_retry(args, source, log_route.directory)
        sys.exit(3)
    if exit_code:
        sys.exit(exit_code)


def _report_prepare_retry(args, source: Path, current: Path) -> None:
    if current != source:
        logger.error(
            "Logs for ID %s remain at %s. Move that directory back to %s after "
            "fixing the rollback error, then discard the incomplete spec with: %s",
            args.log_id, current, source, shlex.join([
                "spex", "create-helper", "discard-incomplete", "--name", current.parent.name,
            ]),
        )
    command = [
        "spex", "create-helper", "prepare-spec", "--log-id", args.log_id,
        "--description", args.description, "--name", args.name, "--mode", args.mode,
    ]
    logger.error("Retry with the original requirement on stdin: %s", shlex.join(command))


def _prepare_spec(args, log_route=None):
    """Create spec directory and return JSON with metadata."""
    import config as cfg
    import hooks
    import prompt as prompt_mod
    from common import get_specs_dir, local_iso_timestamp
    from template import TemplateError

    specs_dir = get_specs_dir()
    prompt = "" if sys.stdin.isatty() else sys.stdin.read().strip()

    try:
        validated = validate_create_name(args.name, args.description)
    except ValueError as e:
        logger.error("Error: %s", e)
        return 1

    try:
        spec_name, spec_dir = create_spec(validated["name"], specs_dir)
    except (ValueError, FileExistsError) as e:
        logger.error(f"Error: {e}")
        return 1

    source = log_route.directory if log_route is not None else None
    try:
        ctx = cfg.get_project_context()
        timestamp = local_iso_timestamp()
        _write_meta(
            spec_dir, ctx, prompt, timestamp, validated["description"],
            task_mode=args.mode,
        )

        filename = template_filename("create-spec", args.mode)
        template_error = False
        try:
            spec_prompt = prompt_mod.render_prompt(
                "create-spec",
                metadata={
                    "prompt_context": prompt, "spec_name": spec_name, "task_mode": args.mode,
                },
            )
            if not spec_prompt.strip():
                raise TemplateError("Rendered prompt is empty")
        except SystemExit:
            # Required metadata validation already reports the missing fields.
            logger.error("Invalid metadata for %s.", filename)
            template_error = True
        except (OSError, UnicodeError, TemplateError) as err:
            logger.error("Error rendering %s: %s", filename, err)
            template_error = True

        if template_error:
            discard_incomplete_spec(spec_dir, specs_dir=specs_dir)
            return 2

        result = {
            "spec_name": spec_name,
            "spec_path": str(spec_dir),
            "spec_template": prompt_mod.render_prompt("spec-template", spec_name),
            "spec_prompt": spec_prompt,
            "task_mode": args.mode,
        }
        rendered = json.dumps(result, indent=2)
        with log_route.handoff(spec_dir) if log_route is not None else nullcontext():
            anchor = _append_prepare_anchor(spec_dir, spec_name)
            spex_branch = DEFAULT_SPEX_BRANCH_PREFIX + strip_date_prefix(spec_name)
            try:
                hooks.run_pre_action(
                    "create",
                    {"spex_branch": spex_branch},
                    workdir=ctx.top_workdir,
                    spec_name=spec_name,
                )
                print(rendered)
            except BaseException:
                if log_route is not None and anchor is not None:
                    _remove_prepare_anchor(*anchor)
                raise
    except BaseException:
        # prepare-spec owns the new directory until success; roll back stubs
        # so a retry with another name does not leave meta-only trees.
        if log_route is None or log_route.directory == source:
            try:
                discard_incomplete_spec(spec_dir, specs_dir=specs_dir)
            except ValueError as err:
                logger.warning("prepare-spec rollback skipped: %s", err)
        raise


def _do_discard_incomplete(args):
    """Remove a prepared spec directory that never received spec.md."""
    from common import get_specs_dir

    specs_dir = get_specs_dir()
    # resolve_spec_dir exits on missing / ambiguous names.
    spec_dir = resolve_spec_dir(args.name, specs_dir)
    try:
        removed = discard_incomplete_spec(spec_dir, specs_dir=specs_dir)
    except ValueError as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    print(json.dumps({
        "discarded": removed,
        "spec_path": str(spec_dir),
    }, indent=2))


def cli_prepare_spec(argv=None):
    """CLI: create spec directory and return JSON with metadata."""

    args = _build_parser().parse(["prepare-spec"] + (argv or []))
    _do_prepare_spec(args)


def _git_diagnostic(exc):
    if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
        stderr = exc.stderr
        return (stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr).strip()
    return str(exc)


def _description_git_env() -> dict[str, str]:
    # Match Git's repository-local environment, plus ref namespace and
    # discovery controls. Keep ordinary environment and user Git config.
    overrides = {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
        "GIT_DIR", "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_GRAFT_FILE",
        "GIT_IMPLICIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_NAMESPACE",
        "GIT_NO_REPLACE_OBJECTS", "GIT_OBJECT_DIRECTORY", "GIT_PREFIX",
        "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE", "GIT_WORK_TREE",
    }
    return {name: value for name, value in os.environ.items() if name not in overrides}


def _description_worktree(meta: SpecMeta, env: dict[str, str]) -> Path:
    errors = []
    for recorded in dict.fromkeys((meta.main_worktree, meta.workdir)):
        if not recorded:
            continue
        cwd = Path(recorded)
        try:
            if not cwd.is_absolute():
                raise ValueError("Expected an absolute worktree path.")
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cwd, capture_output=True, text=True, check=True, env=env,
            )
            if Path(result.stdout.rstrip("\n")).resolve() != cwd.resolve():
                raise ValueError("Recorded path is not the worktree root.")
            return cwd
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            errors.append(f"{recorded}: {_git_diagnostic(exc)}")
    details = "; ".join(errors) or "No worktree path was recorded."
    raise ValueError(f"Spec repository is unavailable: {details}")


def _sync_modified_description(meta_path: Path, meta: SpecMeta, description: str) -> None:
    from branch import (
        get_branch_description,
        has_local_branch,
        set_branch_description,
        unset_branch_description,
    )

    branch = meta.spex_branch
    env = _description_git_env()
    cwd = _description_worktree(meta, env) if branch else None
    changed_git = False
    try:
        if cwd is not None and has_local_branch(branch, cwd, env=env):
            previous = get_branch_description(branch, cwd, env=env)
            if previous != description:
                set_branch_description(branch, description, cwd, env=env)
                changed_git = True
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"{cwd}: branch.{branch}.description: {_git_diagnostic(exc)}") from exc

    if meta.description == description:
        return
    meta.description = description
    try:
        atomic_write_json(meta_path, meta.to_dict())
    except OSError as exc:
        if changed_git:
            try:
                if previous is None:
                    unset_branch_description(branch, cwd, env=env)
                else:
                    set_branch_description(branch, previous, cwd, env=env)
            except (OSError, subprocess.CalledProcessError) as rollback_error:
                raise ValueError(
                    f"{exc}; could not restore branch.{branch}.description in "
                    f"{cwd}: {_git_diagnostic(rollback_error)}"
                ) from rollback_error
        raise


def _do_post_action(args, *, spec_dir=None):
    """Validate todo.json and trigger post-action hook."""
    from common import (
        SpecMeta,
        load_meta,
        parse_front_matter_description,
    )
    from config import get_project_context
    from todo_helper import validate_todo

    spec_dir = spec_dir or resolve_spec_dir(args.name)
    json_path = spec_dir / "todo.json"

    if not json_path.is_file():
        logger.error(f"Error: {json_path} not found.")
        sys.exit(1)

    data = validate_todo(json_path, allow_empty=False)
    logger.info(f"OK: {len(data)} step(s) validated.")

    # Update description from spec.md front-matter
    spec_path = spec_dir / "spec.md"
    if spec_path.is_file():
        spec_content = spec_path.read_text(encoding="utf-8")
        desc = parse_front_matter_description(spec_content)
        if desc:
            meta_path = spec_dir / "meta.json"
            meta_data = load_meta(spec_dir)
            description = wrap_text(desc)
            if args.event_type == "modify":
                if meta_data is None:
                    sys.exit(f"Could not read spec metadata: {meta_path}")
                try:
                    _sync_modified_description(meta_path, meta_data, description)
                except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                    sys.exit(f"Could not synchronize the spec description: {_git_diagnostic(exc)}")
            else:
                meta_data = meta_data or SpecMeta()
                meta_data.description = description
                atomic_write_json(meta_path, meta_data.to_dict())

    import hooks
    from debug_log import debug_enabled, prepare_spec_log_parent, spec_debug_log_path

    meta = load_meta(spec_dir)
    spec_name = spec_dir.name
    ctx = get_project_context()
    workdir = (meta.workdir if meta else "") or (
        str(ctx.top_workdir) if ctx.in_git_workdir() else None
    )
    done = sum(
        1 for item in data
        if isinstance(item, dict) and item.get("completed_at")
    )
    undone = len(data) - done
    spex_branch = meta.spex_branch if meta else ""

    if debug_enabled(sys.argv):
        log_path = spec_debug_log_path(spec_dir)
        if not prepare_spec_log_parent(log_path):
            raise OSError(f"Cannot write spec log: {log_path}")
        _append_create_debug_anchor(
            log_path,
            f"===== CREATE post-action ok name={spec_name} "
            f"steps={len(data)} =====",
        )

    hooks.run_post_action(
        args.event_type,
        {"spex_branch": spex_branch, "done": done, "undone": undone},
        workdir or None,
        spec_name,
    )


def cli_post_action(argv=None):
    """CLI: validate todo.json and trigger post-action hook."""

    args = _build_parser().parse(["post-action"] + (argv or []))
    _do_post_action(args)


def _commit_finalized_todo(spec_name, todo_path, backup_path, *, modify=False):
    """Commit the todo transaction with a commit-only recovery diagnostic."""
    import todo_helper

    attempts = 2 if modify else 1
    for attempt in range(attempts):
        try:
            todo_helper.cmd_transaction(todo_path, "commit")
            return
        except (SystemExit, UnicodeError) as exc:
            if isinstance(exc, UnicodeError):
                logger.error("Could not read %s: %s", todo_path, exc)
            if attempt + 1 < attempts:
                logger.info("Retrying todo transaction commit for %s.", spec_name)
                continue
            if modify:
                logger.error("Todo transaction backup: %s", backup_path)
            logger.error(
                "Recovery command: spex todo-helper transaction commit %s",
                shlex.quote(spec_name),
            )
            if modify:
                sys.exit(3)
            raise


def _do_finalize(args, *, modify=False):
    """Run post-action work and commit any open todo transaction."""
    spec_dir = resolve_spec_dir(args.name)
    todo_path = spec_dir / "todo.json"
    backup_path = todo_path.with_name(f"{todo_path.name}.lock")
    has_transaction = backup_path.exists() or backup_path.is_symlink()
    if not modify and not has_transaction:
        logger.warning("Todo transaction backup '%s' not found; skipping commit.", backup_path)

    args.event_type = "modify" if modify else "create"
    _do_post_action(args, spec_dir=spec_dir)
    if has_transaction:
        _commit_finalized_todo(args.name, todo_path, backup_path, modify=modify)


def cli_finalize(argv=None):
    """CLI: finish create post-actions and commit its todo transaction."""
    args = _build_parser().parse(["finalize"] + (argv or []))
    _do_finalize(args)


def _build_parser():
    """Build the top-level parser with subcommand sub-parsers."""
    parser = ArgumentParser(
        prog="spex create-helper",
        description="Helper utilities for spec creation.",
    )
    subs = parser.add_subparsers(dest="subcmd", title="Subcommands")

    p_precheck = subs.add_parser(
        "precheck",
        description="Validate branch creation feasibility.",
        help="Validate branch creation feasibility",
    )
    p_precheck.add_argument(
        "--begin-log", action="store_true",
        help="Allocate an isolated create log after validation",
    )

    p_end_log = subs.add_parser("end-log", help="Remove an isolated create log")
    p_end_log.add_argument("--log-id", required=True, help="Allocated temporary log ID")

    p_validate_name = subs.add_parser(
        "validate-name",
        description=(
            "Validate create Phase 3 name and description."
        ),
        help="Validate create Phase 3 name and description",
    )
    p_validate_name.add_argument(
        "--name", required=True, help="Short spec name (no date prefix)",
    )
    p_validate_name.add_argument(
        "--description", required=True,
        help="Single-line brief description",
    )

    p_prepare = subs.add_parser(
        "prepare-spec",
        description=(
            "Create spec directory and return JSON metadata."
        ),
        help="Create spec directory and return JSON metadata",
    )
    p_prepare.add_argument(
        "--name", required=True, help="Spec name",
    )
    p_prepare.add_argument("--log-id", help="Allocated temporary log ID")
    p_prepare.add_argument(
        "--description", default="",
        help="Brief description (saved to meta.json)",
    )
    p_prepare.add_argument(
        "--mode", choices=TASK_MODES, default=SOFTWARE, help="Task mode (default: software)",
    )

    p_discard = subs.add_parser(
        "discard-incomplete",
        description=(
            "Remove a prepared spec directory that has no spec.md yet."
        ),
        help="Discard an incomplete (no spec.md) spec directory",
    )
    p_discard.add_argument(
        "--name", required=True,
        help="Spec name or path fragment to resolve under specs/",
    )

    p_post = subs.add_parser(
        "post-action",
        description=(
            "Validate todo.json and run post-action hook."
        ),
        help="Validate todo.json and run post-action hook",
    )
    p_post.add_argument(
        "--name", required=True, help="Spec name",
    )
    p_post.add_argument(
        "--event-type", default="create",
        help="Hook event type (default: create)",
    )

    p_finalize = subs.add_parser(
        "finalize",
        description=(
            "Validate the todo plan, run create post-action, and "
            "commit its transaction."
        ),
        help="Finalize create and commit its todo transaction",
    )
    p_finalize.add_argument(
        "name", type=nonempty_spec_name, metavar="<spec-name>",
    )

    p_finalize_modify = subs.add_parser(
        "finalize-modify", help="Finalize modify and commit its todo transaction if open",
    )
    p_finalize_modify.add_argument("name", type=nonempty_spec_name, metavar="<spec-name>")

    snapshot = subs.add_parser("begin-modify", help="Snapshot and increment the spec version")
    snapshot.add_argument("name", type=nonempty_spec_name, metavar="<spec-name>")
    snapshot.add_argument(
        "--stdin", action="store_true", dest="stdin_flag",
        help="Run pre-action and save the modification request from stdin",
    )

    return parser


def main(argv=None, *, log_route=None):
    """Parse args, route to subcommand."""

    parser = _build_parser()
    args = parser.parse(argv)

    if not args.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    if args.subcmd == "precheck":
        _do_precheck(args, log_route)
    elif args.subcmd == "end-log":
        _do_end_log(args)
    elif args.subcmd == "validate-name":
        _do_validate_name(args)
    elif args.subcmd == "prepare-spec":
        _do_prepare_spec(args, log_route)
    elif args.subcmd == "discard-incomplete":
        _do_discard_incomplete(args)
    elif args.subcmd == "post-action":
        _do_post_action(args)
    elif args.subcmd == "finalize":
        _do_finalize(args)
    elif args.subcmd == "finalize-modify":
        _do_finalize(args, modify=True)
    elif args.subcmd == "begin-modify":
        _do_modify_session(args)
