"""Tests for read-only plan review and spec discovery."""

import json
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
