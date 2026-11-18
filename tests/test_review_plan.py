"""Tests for read-only plan review and spec discovery."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SPEX_DIR = Path(__file__).resolve().parents[1] / "skills" / "spex"


def test_review_plan_routes_explicit_and_free_form_requests():
    skill = (SPEX_DIR / "SKILL.md").read_text(encoding="utf-8")
    metadata, body = skill.split("---", 2)[1:]
    assert "modify, review-plan, apply" in metadata
    assert "`commands/review-plan.md`" in body
    intent = body.split("### Free-form Intent Inference", 1)[1]
    assert "review the development plan" in intent
    assert "检查任务拆分" in intent
    assert "combined plan review and edits are conflicting" in intent
    assert "changing the requirements, spec, or development plan" in intent
    assert "Match command words as whole tokens" in intent
    assert "`2026-11-18-14-56-review-plan`" in intent
    assert 'Too short/vague (e.g. "help", "review", "评审"' in intent


def test_review_plan_requires_a_read_only_probe_and_manual_handoff():
    sop = (SPEX_DIR / "commands" / "review-plan.md").read_text(encoding="utf-8")
    assert 'list --read-only --json -- "<probe>"' in sop
    assert "never falls\n  back to an unfiltered list" in sop
    assert "choose from the numbered matches" in sop
    assert "unfinished steps with a recorded `commit_title`" in sop
    assert "`/spex modify <spec-name> <suggested changes>`" in sop
    assert "run it manually" in sop


@pytest.mark.slow
@pytest.mark.parametrize("existing_spec", [False, True])
def test_read_only_list_leaves_storage_and_tracing_untouched(
    tmp_path, monkeypatch, existing_spec,
):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    config = tmp_path / ".spex.toml"
    config.write_text('[spex]\nspex_root = ".spex"\n', encoding="utf-8")
    monkeypatch.setenv("SPEX_CONFIG_FILE", str(config))
    trace_dir = tmp_path / "trace"
    monkeypatch.setenv("SPEX_LOG_DIR", str(trace_dir))
    storage = tmp_path / ".spex"
    spec_dir = storage / "specs" / "review-target"
    if existing_spec:
        spec_dir.mkdir(parents=True)
        (spec_dir / "meta.json").write_text(
            json.dumps({"workdir": str(tmp_path)}), encoding="utf-8",
        )
        (spec_dir / "spec.md").write_text("# Review target\n", encoding="utf-8")

    def snapshot():
        return {
            path.relative_to(storage): path.read_bytes() if path.is_file() else None
            for path in storage.rglob("*")
        }

    before = snapshot()
    result = subprocess.run(
        [sys.executable, str(SPEX_DIR / "scripts" / "spex"), "--debug",
         "list", "--read-only", "--json", "--", "review-target"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    expected = (
        [{"spec_name": spec_dir.name, "spec_path": str(spec_dir.resolve())}]
        if existing_spec else []
    )
    assert json.loads(result.stdout) == expected
    assert snapshot() == before
    assert storage.exists() == existing_spec
    assert not trace_dir.exists()


@pytest.fixture
def plan_prompt_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    skill = tmp_path / "skill"
    shutil.copytree(SPEX_DIR, skill, ignore=shutil.ignore_patterns("__pycache__"))
    cli = [sys.executable, str(skill / "scripts" / "spex"), "--debug"]
    roots = [tmp_path / "caller", tmp_path / "other"]
    configs = []
    for root in roots:
        spec = root / "specs" / "review-target"
        spec.mkdir(parents=True)
        (root / "templates").mkdir()
        (spec / "meta.json").write_text(json.dumps({"workdir": str(project)}))
        (spec / "spec.md").write_text(f"# {root.name} specification")
        (spec / "todo.json").write_text(json.dumps([
            {
                "id": "legacy-1" if i == 1 else i,
                "name": f"{root.name} step {i}",
                "details": "",
                "completed_at": "done",
                "commit_title": "",
            }
            for i in range(1, 92)
        ]))
        config = tmp_path / f"{root.name}.toml"
        config.write_text(f'[spex]\nspex_root = "{root}"\n')
        configs.append(config)

    def run(args, *, root=0, focus=""):
        monkeypatch.setenv("SPEX_CONFIG_FILE", str(configs[root]))
        monkeypatch.setenv("SPEX_LOG_DIR", str(tmp_path / "trace"))
        return subprocess.run(
            [*cli, *args], cwd=project, input=focus, capture_output=True, text=True,
        )

    def snapshot():
        return {
            path.relative_to(tmp_path): (
                (path.read_bytes(), path.stat().st_mtime_ns) if path.is_file() else None
            )
            for path in tmp_path.rglob("*")
        }

    return roots, run, snapshot


@pytest.mark.slow
def test_review_plan_override_uses_caller_root_and_exact_selected_spec(plan_prompt_project):
    (caller, other), run, snapshot = plan_prompt_project
    for root in (caller, other):
        (root / "templates" / "review-plan.md").write_text(
            root.name + " template\n{{ spec_content }}\n{{ todo_json }}\n{{ prompt_context }}",
        )
    before = snapshot()
    selected = run(["list", "--read-only", "--json", "--", "review-target"], root=1)
    assert selected.returncode == 0, selected.stderr
    [entry] = json.loads(selected.stdout)
    result = run(
        ["prompt", "review_plan", "--stdin", "--", entry["spec_path"]],
        focus="Review dependencies",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("caller template\n# other specification")
    assert "caller specification" not in result.stdout
    assert "caller step" not in result.stdout
    for i in range(1, 92):
        assert f'"name": "other step {i}"' in result.stdout
    assert '"id": "legacy-1"' in result.stdout
    assert '"completed_at": "done"' in result.stdout
    assert "Review dependencies" in result.stdout
    assert snapshot() == before


@pytest.mark.slow
@pytest.mark.parametrize("mode", [None, "general"])
def test_review_plan_builtin_and_mode_specific_override(plan_prompt_project, mode):
    (caller, _), run, snapshot = plan_prompt_project
    spec = caller / "specs" / "review-target"
    if mode:
        (spec / "meta.json").write_text(json.dumps({"task_mode": mode}))
    args = ["prompt", "review-plan", str(spec)]
    before = snapshot()
    result = run(args)
    assert result.returncode == 0, result.stderr
    expected = "missing sources" if mode else "compatibility"
    assert expected in result.stdout
    assert snapshot() == before
    name = "general-review-plan.md" if mode else "review-plan.md"
    (caller / "templates" / name).write_text("Custom {{ task_mode }} review for {{ spec_name }}")
    result = run(args)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"Custom {mode or 'software'} review for review-target"


@pytest.mark.slow
@pytest.mark.parametrize(("target", "contents", "error"), [
    ("template", "{% if prompt_context %}Focused{% endif %} \n", "rendered an empty prompt"),
    ("template", "{% invalid %}", "Error rendering review-plan"),
    ("todo.json", "{}", "top-level value must be an array"),
    ("todo.json", "[4]", "is not an object"),
    ("todo.json", '[{"id": 1}]', "missing required field 'name'"),
    ("todo.json", '[{"id": 1}, {"id": 1}]', "duplicate id '1'"),
    ("todo.json.lock", "", "Unfinished todo transaction"),
    ("meta.json", '{"task_mode": "invalid"}', "Invalid task mode"),
    ("spec.md", None, "spec.md"),
])
def test_review_plan_failures_are_read_only(plan_prompt_project, target, contents, error):
    (caller, other), run, snapshot = plan_prompt_project
    spec = other / "specs" / "review-target"
    template = caller / "templates" / "review-plan.md"
    path = template if target == "template" else spec / target
    if contents is None:
        path.unlink()
    else:
        path.write_text(contents)
    before = snapshot()
    result = run(["prompt", "review-plan", str(spec)])
    assert result.returncode != 0
    assert result.stdout == ""
    assert error in result.stderr
    if "empty prompt" in error:
        assert str(template) in result.stderr
    assert snapshot() == before
