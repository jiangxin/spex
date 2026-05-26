"""Branch management utilities for spex."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from common import DEFAULT_SPEX_BRANCH_PREFIX


def _strip_refs_prefix(name: str) -> str:
    """Strip refs/heads/ prefix if present, returning a short branch name."""
    if name.startswith("refs/heads/"):
        return name[len("refs/heads/"):]
    return name


def get_current_branch() -> str:
    """Return the current git branch name in short format (no refs/heads/ prefix)."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stderr)
    branch_name = result.stdout.strip()
    if branch_name == "HEAD":
        raise RuntimeError("Currently in detached HEAD state, no branch name.")
    return branch_name


def strip_date_prefix(topic_name: str) -> str:
    """Remove the YYYY-MM-DD-HH-MM- datetime prefix from a topic name."""
    return re.sub(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-", "", topic_name)


def branch_exists(branch_name: str) -> bool:
    """Check if a local git branch exists."""
    branch_name = _strip_refs_prefix(branch_name)
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch_name}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def create_branch(branch_name: str) -> None:
    """Create a new local branch. Raises subprocess.CalledProcessError on failure."""
    branch_name = _strip_refs_prefix(branch_name)
    subprocess.run(
        ["git", "branch", branch_name],
        capture_output=True,
        text=True,
        check=True,
    )


def switch_branch(branch_name: str) -> None:
    """Switch to the given branch. Raises subprocess.CalledProcessError on failure."""
    branch_name = _strip_refs_prefix(branch_name)
    subprocess.run(
        ["git", "switch", branch_name],
        capture_output=True,
        text=True,
        check=True,
    )


def set_branch_description(branch: str, description: str) -> None:
    """Set the git branch description. Branch must be short format (no refs/heads/)."""
    branch = _strip_refs_prefix(branch)
    subprocess.run(
        ["git", "config", f"branch.{branch}.description", description],
        capture_output=True,
        text=True,
        check=True,
    )


def merge_branch(target: str, source: str) -> None:
    """Merge source branch into target. Raises CalledProcessError on conflict."""
    subprocess.run(
        ["git", "switch", target],
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git",
         "-c", "merge.branchdesc=true",
         "-c", "merge.log=true",
         "merge", source,
         "--no-ff",
         "--no-edit"],
        capture_output=True,
        text=True,
        check=True,
    )


def validate_create_branch(config: dict) -> str:
    """Validate whether branch creation is enabled and feasible.

    Prints errors to stderr and exits on failure.
    Returns the current branch name on success.
    """
    enabled = bool(config.get("create_branch", False))
    if not enabled:
        print("Error: branch creation is not enabled in config.", file=sys.stderr)
        sys.exit(1)

    try:
        current = get_current_branch()
    except subprocess.CalledProcessError as e:
        print(f"Error: cannot determine current branch: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # 1. If main_branch_name is set, current branch must match it.
    main_branch = config.get("main_branch_name", "")
    if main_branch and current != main_branch:
        print(
            f"Error: current branch '{current}' does not match main_branch_name '{main_branch}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 2. Current branch must not start with the spex prefix.
    if current.startswith(DEFAULT_SPEX_BRANCH_PREFIX):
        print(
            f"Error: current branch '{current}' starts with "
            f"'{DEFAULT_SPEX_BRANCH_PREFIX}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    return current


def _extract_topic_name_for_branch(topic_dir: Path, meta: dict) -> str:
    """Get the topic name to use for branch naming.

    Uses the 'topic' field from meta.json if available, otherwise falls back
    to the directory name.
    """
    return meta.get("topic", "") or topic_dir.name


def validate_apply_branch(config: dict, topic_dir: Path) -> None:
    """Perform branch setup for applying a topic spec.

    Steps:
    1. If all topic tasks are completed, error and exit.
    2. If create_branch is False in config, return immediately.
    3. If meta.json has spex_branch, ensure current branch matches it;
       switch if not (exit on failure).
    4. If meta.json has no spex_branch, try creating a branch using
       spex/<topic-name-without-date-prefix>, then spex/<topic-name-with-date-prefix>.
       Exit on failure if both fail.
    5. On success, switch to the branch, set git branch description from
       the topic's spec description, and persist spex_branch to meta.json.
    """
    import common

    # Step 1: check topic completion — must have undone tasks
    if common.is_topic_completed(topic_dir):
        status = common.format_topic(topic_dir, verbose=2)
        print(f"Error: topic is already completed.\n{status}", file=sys.stderr)
        sys.exit(1)

    # Step 2
    if not config.get("create_branch", False):
        return

    meta = common.load_meta(topic_dir) or {}
    spex_branch = meta.get("spex_branch", "")

    # Step 3: spex_branch exists in meta — ensure current branch matches
    if spex_branch:
        current = get_current_branch()
        if current != spex_branch:
            if not branch_exists(spex_branch):
                print(
                    f"Error: spex_branch '{spex_branch}' defined in meta.json "
                    f"does not exist.",
                    file=sys.stderr,
                )
                sys.exit(1)
            try:
                switch_branch(spex_branch)
            except subprocess.CalledProcessError as e:
                print(
                    f"Error: failed to switch to '{spex_branch}': "
                    f"{e.stderr.strip() or e}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"Switched to branch '{spex_branch}'.")
        return

    # Step 4: no spex_branch — try to create one
    topic_name = _extract_topic_name_for_branch(topic_dir, meta)
    short_name = strip_date_prefix(topic_name)

    candidates = [
        f"{DEFAULT_SPEX_BRANCH_PREFIX}{short_name}",
        f"{DEFAULT_SPEX_BRANCH_PREFIX}{topic_name}",
    ]

    created_branch = None
    for candidate in candidates:
        if branch_exists(candidate):
            created_branch = candidate
            break
        try:
            create_branch(candidate)
            created_branch = candidate
            break
        except subprocess.CalledProcessError:
            continue

    if created_branch is None:
        print(
            f"Error: failed to create branch. Tried: {', '.join(candidates)}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Step 5: switch to the branch and set metadata
    try:
        switch_branch(created_branch)
    except subprocess.CalledProcessError as e:
        print(
            f"Error: failed to switch to '{created_branch}': "
            f"{e.stderr.strip() or e}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Set branch description from topic's spec description
    description = common.get_spec_description(topic_dir)
    if description:
        try:
            set_branch_description(created_branch, description)
        except subprocess.CalledProcessError:
            pass  # non-fatal

    # Persist spex_branch to meta.json
    meta_path = topic_dir / "meta.json"
    meta["spex_branch"] = created_branch
    common.atomic_write_json(meta_path, meta)

    print(f"Created and switched to branch '{created_branch}'.")


# --- CLI handler functions ---


def _parse_topic_arg() -> str:
    """Parse --topic <name> from sys.argv. Exit 1 if missing."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--topic" and i + 1 < len(args):
            return args[i + 1]
    print("Error: --topic <name> is required", file=sys.stderr)
    sys.exit(1)


def cli_create_validate() -> None:
    """CLI: validate branch creation feasibility."""
    import config as cfg

    conf = cfg.load_config()
    current = validate_create_branch(conf)
    print(f"Valid: currently on branch '{current}'")


def cli_apply_validate() -> None:
    """CLI: perform branch setup for applying a topic."""
    import common
    import config as cfg

    topic_name = _parse_topic_arg()
    conf = cfg.load_config()
    topic_dir = common.resolve_topic_dir(topic_name)
    validate_apply_branch(conf, topic_dir)


def cli_apply_post_action() -> None:
    """CLI: show post-apply branch status info."""
    import common

    topic_name = _parse_topic_arg()
    topic_dir = common.resolve_topic_dir(topic_name)
    meta = common.load_meta(topic_dir)
    spex_branch = meta.get("spex_branch", "") if meta else ""
    if not spex_branch:
        return

    target = meta.get("branch", "main")
    print(
        f"Development completed on topic branch {spex_branch}.\n"
        f"After local code review, run /spex merge to merge into\n"
        f"branch {target}, or create a pull request."
    )


def cli_submit() -> None:
    """CLI: submit (merge) a spex branch back to target. Output JSON."""
    import common
    import config as cfg

    topic_name = _parse_topic_arg()
    conf = cfg.load_config()
    topic_dir = common.resolve_topic_dir(topic_name)
    meta = common.load_meta(topic_dir)
    source = meta.get("spex_branch", "") if meta else ""
    target = meta.get("branch", "main") if meta else "main"
    method = conf.get("submit_method", "merge")
    errors: list[str] = []

    if not source:
        errors.append("No spex_branch in topic meta.json")
        print(json.dumps({"action": method, "source": "", "target": target,
                          "errors": errors}))
        sys.exit(1)

    if method == "merge":
        try:
            merge_branch(target, source)
        except subprocess.CalledProcessError as e:
            errors.append(f"Merge failed: {e.stderr.strip() or str(e)}")
            print(json.dumps({"action": method, "source": source,
                              "target": target, "errors": errors}))
            sys.exit(1)

    print(json.dumps({"action": method, "source": source,
                      "target": target, "errors": errors}))
