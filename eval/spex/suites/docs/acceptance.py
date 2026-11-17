"""Verify docs trial scope and provide artifacts for semantic evaluation."""

import argparse
import json
import subprocess
from pathlib import Path

NAMES = {
    "edit-guide": "2000-01-01-00-00-export-guide",
    "analyze-incident": "2000-01-01-00-01-export-incident",
}


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, timeout=10)


def read(repo, relative):
    path = repo / relative
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"Expected a regular trial file: {relative}")
    return path.read_text(encoding="utf-8")


def evaluate(repo, scenario):
    head = git(repo, "rev-parse", "HEAD").strip()
    base, *commits = git(repo, "rev-list", "--first-parent", "--reverse", "HEAD").splitlines()
    tasks = json.loads(read(repo, f".spex/specs/{NAMES[scenario]}/todo.json"))
    if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], dict):
        raise ValueError("Expected a single task object")
    task = tasks[0]
    checks = {
        "task-completed": str(task.get("id")) in {"1", "step-1"} and bool(task.get("completed_at")),
        "clean-worktree": not git(repo, "status", "--porcelain", "--untracked-files=all"),
    }
    if scenario == "analyze-incident":
        checks["skip-commit"] = (
            task.get("skip_commit") is True and task.get("commit_title") == "" and head == base
        )
        return checks, {"incident_log": git(repo, "show", f"{base}:incident.log")}

    changed = git(repo, "diff", "--name-only", "-z", base, head)
    short_head = git(repo, "rev-parse", "--short", "HEAD").strip()
    title = task.get("commit_title", "")
    guide = read(repo, "GUIDE.md")
    checks.update({
        "guide-only": changed == "GUIDE.md\0",
        "guide-committed": (
            len(commits) == 1 and isinstance(title, str) and title.partition(":")[0] == short_head
        ),
    })
    return checks, {"guide": guide, "original_guide": git(repo, "show", f"{base}:GUIDE.md")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("scenario", choices=NAMES)
    args = parser.parse_args()
    try:
        checks, evidence = evaluate(args.repo.resolve(), args.scenario)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"passed": False, "checks": {}, "error": str(error)}))
        return 1
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "checks": checks, "evidence": evidence}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
