"""Check greeting CLI trial outcomes from outside the trial workspace."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FORMAT = "2000-01-01-00-00-greeting-format"
DECORATION = "2000-01-01-00-01-greeting-decoration"
SPECS = Path(".spex/specs")


def read(repo, relative):
    path = repo / relative
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"Expected a regular trial file: {relative}")
    return path.read_text(encoding="utf-8")


def read_tasks(repo, name):
    tasks = json.loads(read(repo, SPECS / name / "todo.json"))
    if not isinstance(tasks, list) or not tasks or not all(isinstance(t, dict) for t in tasks):
        raise ValueError("Expected a non-empty list of task objects")
    return tasks


def lifecycle_name(repo):
    names = [path.name for path in (repo / SPECS).glob("*-lifecycle-greeting")]
    if len(names) != 1:
        raise ValueError("Expected exactly one lifecycle greeting spec")
    return names[0]


def plan_checks(repo, scenario):
    root = repo / SPECS
    name = FORMAT
    if scenario == "lifecycle-plan":
        name = lifecycle_name(repo)
    elif scenario == "new-plan":
        candidates = set(p.name for p in root.iterdir()) - {FORMAT, DECORATION}
        if len(candidates) != 1:
            return {"one-new-spec": False}
        name = candidates.pop()
    spec = read(repo, SPECS / name / "spec.md")
    meta = json.loads(read(repo, SPECS / name / "meta.json"))
    tasks = read_tasks(repo, name)
    ids = [t.get("id") for t in tasks]
    pending = [t for t in tasks if not t.get("completed_at")]
    checks = {
        "spec-written": bool(spec.strip()),
        "meta-written": isinstance(meta, dict) and bool(meta.get("name")),
        "valid-task-identifiers": ids == [f"step-{i}" for i in range(1, len(tasks) + 1)],
        "pending-tasks": bool(pending),
        "task-details-written": all(t.get("name") and t.get("details") for t in tasks),
    }
    if scenario == "modify-plan":
        checks["updated-option"] = "--punctuation" in spec and any(
            "--punctuation" in t["details"] for t in pending if isinstance(t.get("details"), str)
        )
    elif scenario == "lifecycle-plan":
        checks["updated-tail-plan"] = (
            "--tail" in spec and len(pending) == 2
            and "--prefix" in pending[0].get("details", "")
            and "--tail" in pending[1].get("details", "")
        )
    else:
        checks["planning-only"] = tasks == pending
    return checks


def invoke(repo, *flags):
    cli = repo / "greet.py"
    if cli.resolve() != cli or not cli.is_file():
        raise ValueError("Expected a regular trial greet.py")
    return subprocess.run(
        [sys.executable, "-I", "-B", str(cli), "Ada", *flags],
        cwd=repo, capture_output=True, text=True, timeout=10, check=False,
    )


def output_is(repo, expected, *flags):
    result = invoke(repo, *flags)
    return (result.returncode, result.stdout, result.stderr) == (0, expected, "")


def commits_ordered(repo, tasks):
    shas = [str(task.get("commit_title", "")).split(":", 1)[0] for task in tasks]
    if not all(re.fullmatch("[0-9a-f]{7,40}", sha) for sha in shas):
        return False
    history = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--first-parent", "--reverse", "HEAD"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if history.returncode != 0:
        return False
    fixture_commit, *step_history = history.stdout.splitlines()
    previous = -1
    for sha in shas:
        if fixture_commit.startswith(sha):
            return False
        matches = [i for i, commit in enumerate(step_history) if commit.startswith(sha)]
        if len(matches) != 1 or matches[0] <= previous:
            return False
        previous = matches[0]
    return True


def clean_worktree(repo):
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, timeout=10, check=False,
    )
    return status.returncode == 0 and not status.stdout


def decoration_checks(repo, scenario):
    lifecycle = scenario.startswith("lifecycle-")
    tasks = read_tasks(repo, lifecycle_name(repo) if lifecycle else DECORATION)
    done = [t for t in tasks if t.get("completed_at")]
    suffix_flag = "--tail" if lifecycle else "--suffix"
    checks = {
        "default-compatible": output_is(repo, "Hello, Ada!\n"),
        "uppercase-compatible": output_is(repo, "HELLO, ADA!\n", "--upper"),
        "prefix-verbatim": output_is(repo, "[hi] HELLO, ADA!\n", "--upper", "--prefix", "[hi] "),
        "commits-in-step-order": bool(done) and commits_ordered(repo, done),
        "clean-worktree": clean_worktree(repo),
    }
    if scenario in ("prefix-only", "lifecycle-prefix"):
        suffix = invoke(repo, suffix_flag, " tail")
        checks["suffix-not-implemented"] = suffix.returncode == 2 and suffix.stdout == ""
        checks["expected-completed-steps"] = [t.get("id") for t in done] == ["step-1"]
    else:
        checks["expected-completed-steps"] = [t.get("id") for t in done] == ["step-1", "step-2"]
        checks["suffix-verbatim"] = output_is(
            repo, "[hi] HELLO, ADA! tail\n", "--upper", "--prefix", "[hi] ", suffix_flag, " tail"
        )
        checks["suffix-only"] = output_is(repo, "Hello, Ada! tail\n", suffix_flag, " tail")
    if scenario == "resumed-decoration":
        seed = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "refs/tags/eval-review-base"],
            text=True, timeout=10,
        ).strip()
        prefix_sha = tasks[0].get("commit_title", "").partition(":")[0]
        checks["resumed-original-commit"] = bool(prefix_sha) and seed.startswith(prefix_sha)
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument(
        "scenario", choices=(
            "new-plan", "modify-plan", "prefix-only", "all-decoration", "resumed-decoration",
            "lifecycle-plan", "lifecycle-prefix", "lifecycle-all",
        ),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    try:
        if args.scenario.endswith("-plan"):
            checks = plan_checks(repo, args.scenario)
        else:
            checks = decoration_checks(repo, args.scenario)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"passed": False, "checks": {}, "error": str(error)}))
        return 1
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "checks": checks}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
