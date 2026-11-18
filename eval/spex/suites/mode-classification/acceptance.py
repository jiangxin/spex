"""Score persisted create classification without a model judge."""

import argparse
import json
from pathlib import Path


def evaluate(repo, expected):
    root = repo / ".spex/specs"
    specs = sorted(root.glob("*/spec.md"))
    checks = {"one-created-spec": len(specs) == 1, "task-mode": False, "pending-plan": False}
    evidence = {"expected_mode": expected, "actual_mode": None}
    if checks["one-created-spec"]:
        spec, = specs
        meta = json.loads(spec.with_name("meta.json").read_text(encoding="utf-8"))
        tasks = json.loads(spec.with_name("todo.json").read_text(encoding="utf-8"))
        actual = meta.get("task_mode") if isinstance(meta, dict) else None
        checks["task-mode"] = actual == expected
        checks["pending-plan"] = bool(spec.read_text(encoding="utf-8").strip()) and (
            isinstance(tasks, list) and bool(tasks) and all(
                isinstance(task, dict) and task.get("completed_at") == ""
                and task.get("commit_title") == ""
                and isinstance(task.get("details"), str) and bool(task["details"].strip())
                for task in tasks
            )
        )
        evidence.update(actual_mode=actual, spec=spec.read_text(encoding="utf-8"), tasks=tasks)
    return {"passed": all(checks.values()), "checks": checks, "evidence": evidence}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("expected", choices=("software", "general"))
    args = parser.parse_args()
    try:
        result = evaluate(args.repo, args.expected)
    except (OSError, ValueError) as error:
        result = {"passed": False, "checks": {}, "error": str(error)}
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
