"""Seed case-specific greeting plans and review state."""

import argparse
import json
import os
import subprocess
from pathlib import Path

SPEC = Path(".spex/specs/2000-01-01-00-01-greeting-decoration")
BRANCH = "spex/greeting-decoration"
MODIFY_SPEC = Path(".spex/specs/2000-01-01-00-00-greeting-format")
MODIFY_CASES = ("modify-rebuild", "modify-targeted")


def seed_modify(repo, scenario):
    plans = json.loads((repo / ".spex/modify-plans.json").read_text(encoding="utf-8"))
    spec = repo / MODIFY_SPEC
    todo = spec / "todo.json"
    upper = json.loads(todo.read_text(encoding="utf-8"))[0]
    tasks = [{**upper, "id": 1}]
    for number, flag in enumerate(plans[scenario], 2):
        tasks.append({
            "id": number, "name": f"Add {flag}", "details": plans["details"][flag],
            "completed_at": "", "commit_title": "",
        })
    todo.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    requirements = "\n".join(f"- {task['details']}" for task in tasks)
    (spec / "spec.md").write_text(
        "<!-- spex:begin:requirement -->\n# Greeting format\n\n"
        f"{requirements}\n\n"
        "<!-- spex:begin:detailed-design -->\n# Design\n\n"
        "Use argparse and preserve the default greeting.\n\n"
        "<!-- spex:begin:test-plan -->\n# Tests\n\n"
        "Pair each option with its tests and keep the existing uppercase tests.\n",
        encoding="utf-8",
    )


def seed_review(repo, fail_review):
    env = dict(os.environ, GIT_AUTHOR_DATE="2000-01-02T00:00:00Z",
               GIT_COMMITTER_DATE="2000-01-02T00:00:00Z")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, env=env, text=True).strip()

    git("switch", "-c", BRANCH)
    cli = repo / "greet.py"
    text = cli.read_text(encoding="utf-8")
    text = text.replace(
        "    args = parser.parse_args()",
        '    parser.add_argument("--prefix", default="")\n    args = parser.parse_args()',
    )
    text = text.replace("print(greeting.upper() if args.upper else greeting)",
                        "print(args.prefix + (greeting.upper() if args.upper else greeting))")
    cli.write_text(text, encoding="utf-8")
    test = repo / "test_greet.py"
    tests = test.read_text(encoding="utf-8").replace(
        '\n\nif __name__ == "__main__":',
        '\n\n    def test_prefix(self):\n'
        '        cli = Path(__file__).with_name("greet.py")\n'
        '        result = subprocess.run(\n'
        '            [sys.executable, str(cli), "Ada", "--upper", "--prefix", "[hi] "],\n'
        '            capture_output=True, text=True, check=True,\n'
        '        )\n'
        '        self.assertEqual(result.stdout, "[hi] HELLO, ADA!\\n")\n'
        '\n\nif __name__ == "__main__":',
    )
    test.write_text(tests, encoding="utf-8")
    git("commit", "-am", "Add optional greeting prefix")
    git("tag", "eval-review-base")
    meta = repo / SPEC / "meta.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["spex_branch"] = BRANCH
    meta.write_text(json.dumps(data), encoding="utf-8")
    todo = repo / SPEC / "todo.json"
    tasks = json.loads(todo.read_text(encoding="utf-8"))
    tasks[0]["commit_title"] = git("log", "-1", "--pretty=%h: %s")
    todo.write_text(json.dumps(tasks), encoding="utf-8")
    if fail_review:
        (repo / SPEC / "review-step-1.json").write_text("{\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("scenario", choices=("review-resume", "review-failure", *MODIFY_CASES))
    args = parser.parse_args()
    if args.scenario in MODIFY_CASES:
        seed_modify(args.repo, args.scenario)
    else:
        seed_review(args.repo, args.scenario == "review-failure")
