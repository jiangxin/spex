"""End-to-end fixtures for the optimized Phase 6 review state machine.

Simulates orchestrator routes against ``review_helper`` (and compact
prompt sizing) without launching LLM sub-agents. Counters stand in for
sub-agent / check / amend launches so route contracts stay enforceable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import review_helper
from prompt import (
    DEFAULT_REVIEW_PROMPT_MAX_BYTES,
    build_compact_review_context,
    measure_prompt_bytes,
    render_prompt,
    should_render_delta_prompt,
)

# Pre-optimization debug samples approached ~30 KiB review prompts.
LEGACY_REVIEW_PROMPT_BASELINE_BYTES = 30_000
# Matches build_compact_review_context headroom (max_bytes - 8_192).
_TEMPLATE_HEADROOM_BYTES = 8_192
PROMPT_CONTENT_BUDGET = DEFAULT_REVIEW_PROMPT_MAX_BYTES - _TEMPLATE_HEADROOM_BYTES
# Full rendered apply-review (template + compact context) must stay under
# the hard cap — the layer that produced the ~30KiB debug samples.
PROMPT_SIZE_REGRESSION_CEILING = DEFAULT_REVIEW_PROMPT_MAX_BYTES


@dataclass
class RouteCounters:
    """Stand-ins for sub-agent / check / amend invocations."""

    full_reviews: int = 0
    delta_reviews: int = 0
    batch_fixes: int = 0
    check_sets: int = 0
    amends: int = 0
    events: list[str] = field(default_factory=list)

    def record(self, name: str) -> None:
        self.events.append(name)
        attr = {
            "full_review": "full_reviews",
            "delta_review": "delta_reviews",
            "batch_fix": "batch_fixes",
            "check_set": "check_sets",
            "amend": "amends",
        }.get(name)
        if attr:
            setattr(self, attr, getattr(self, attr) + 1)


def _evidence(sha: str, exit_code: int = 0, duration_ms: int = 12) -> str:
    return json.dumps({
        "commit_sha": sha,
        "checks": [{
            "command": "pytest -q",
            "exit_code": exit_code,
            "completed_at": "2026-09-10T16:00:00+08:00",
            "duration_ms": duration_ms,
        }],
    })


def _patch_git(monkeypatch, head_sha: str, clean: bool = True) -> None:
    monkeypatch.setattr(
        review_helper, "get_head_sha",
        lambda cwd=None: head_sha,
    )
    monkeypatch.setattr(
        review_helper, "is_project_tree_clean",
        lambda spex_root=None, cwd=None: (
            clean, [] if clean else ["dirty.py"],
        ),
    )


def _status(capsys, step: str = "step-8") -> dict:
    review_helper.main([
        "--name", "integ", "status", "--step", step, "--json",
    ])
    return json.loads(capsys.readouterr().out)


def _open_batch(capsys, step: str = "step-8") -> dict:
    review_helper.main([
        "--name", "integ", "open-batch", "--step", step,
    ])
    return json.loads(capsys.readouterr().out)


def _append(
    step: str,
    fid: str,
    severity: str,
    title: str,
    category: str = "tests",
) -> None:
    review_helper.main([
        "--name", "integ", "append",
        "--step", step,
        "--id", fid,
        "--severity", severity,
        "--category", category,
        "--title", title,
        "--details", f"details for {fid}",
    ])


@pytest.fixture()
def integ(tmp_path, monkeypatch):
    """Isolated spec dir wired to review_helper.resolve_spec_dir."""
    d = tmp_path / "integ"
    d.mkdir()
    monkeypatch.setattr(
        review_helper, "resolve_spec_dir",
        lambda name, **kw: d,
    )
    return d


class ReviewFlowSimulator:
    """Drive helper commands the way Phase 6 would, counting launches."""

    def __init__(
        self,
        spec_dir: Path,
        monkeypatch,
        capsys,
        step: str = "step-8",
        base_sha: str = "base0001",
    ):
        self.spec_dir = spec_dir
        self.monkeypatch = monkeypatch
        self.capsys = capsys
        self.step = step
        self.base_sha = base_sha
        self.counters = RouteCounters()
        self._sha_n = 1

    def _next_sha(self) -> str:
        self._sha_n += 1
        return f"fix{self._sha_n:04d}"

    def init_full_review(self) -> None:
        review_helper.main([
            "--name", "integ", "init",
            "--step", self.step, "--commit", self.base_sha,
        ])
        self.capsys.readouterr()
        self.counters.record("full_review")

    def record_findings(
        self, items: list[tuple[str, str, str]],
    ) -> None:
        for fid, severity, title in items:
            _append(self.step, fid, severity, title)
        self.capsys.readouterr()

    def batch_fix_and_complete(
        self,
        finding_ids: list[str] | None = None,
        *,
        clean: bool = True,
        expect_ok: bool = True,
    ) -> dict | None:
        batch = _open_batch(self.capsys, self.step)
        ids = finding_ids or [f["id"] for f in batch["findings"]]
        assert ids, "batch fix requires open findings"
        review_helper.main([
            "--name", "integ", "set-pending",
            "--step", self.step,
            "--ids", ",".join(ids),
            "--base-commit", self.base_sha,
        ])
        self.capsys.readouterr()
        self.counters.record("batch_fix")

        new_sha = self._next_sha()
        _patch_git(self.monkeypatch, new_sha, clean=clean)
        self.counters.record("check_set")
        self.counters.record("amend")
        try:
            review_helper.main([
                "--name", "integ", "complete-batch",
                "--step", self.step,
                "--ids", ",".join(ids),
                "--base-commit", self.base_sha,
                "--new-commit", new_sha,
                "--evidence", _evidence(new_sha),
            ])
            out = json.loads(self.capsys.readouterr().out)
            if expect_ok:
                assert out.get("completed") is True
            self.base_sha = new_sha
            return out
        except SystemExit:
            if expect_ok:
                raise
            return None

    def delta_review(
        self, new_majors: list[tuple[str, str, str]] | None = None,
    ) -> dict:
        self.counters.record("delta_review")
        status = _status(self.capsys, self.step)
        assert status["awaiting_delta"] is True
        path = self.spec_dir / f"review-{self.step}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["mode"] = "delta"
        data["awaiting_delta"] = False
        data["reviewed_commit_sha"] = self.base_sha
        path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8",
        )
        if new_majors:
            for fid, severity, title in new_majors:
                _append(self.step, fid, severity, title)
            self.capsys.readouterr()
        return _status(self.capsys, self.step)

    def bump_full_round(self) -> None:
        review_helper.main([
            "--name", "integ", "bump-round",
            "--step", self.step, "--commit", self.base_sha,
        ])
        self.capsys.readouterr()
        self.counters.record("full_review")


class TestMinorOnlyBatchRoute:
    def test_n_minors_one_full_one_fix_no_delta(
        self, integ, monkeypatch, capsys,
    ):
        """N minors → 1 full + 1 batch fix + 1 check + 1 amend; no delta/R2."""
        sim = ReviewFlowSimulator(integ, monkeypatch, capsys)
        sim.init_full_review()
        sim.record_findings([
            ("r1-f1", "minor", "Nit A"),
            ("r1-f2", "minor", "Nit B"),
            ("r1-f3", "minor", "Nit C"),
        ])
        status = _status(capsys)
        assert status["needs_fix"] is True
        assert status["open_major"] == 0
        assert status["open_minor"] == 3

        batch = _open_batch(capsys)
        assert batch["has_major"] is False
        assert len(batch["findings"]) == 3
        assert not should_render_delta_prompt(
            json.loads((integ / "review-step-8.json").read_text()),
        )

        out = sim.batch_fix_and_complete()
        assert out["awaiting_delta"] is False
        status = _status(capsys)
        assert status["done"] is True
        assert status["needs_fix"] is False
        assert status["awaiting_delta"] is False
        assert status["round"] == 1

        c = sim.counters
        assert c.full_reviews == 1
        assert c.batch_fixes == 1
        assert c.check_sets == 1
        assert c.amends == 1
        assert c.delta_reviews == 0
        assert c.events == [
            "full_review", "batch_fix", "check_set", "amend",
        ]


class TestMajorDeltaRoute:
    def test_mixed_major_minor_requires_one_delta(
        self, integ, monkeypatch, capsys,
    ):
        sim = ReviewFlowSimulator(integ, monkeypatch, capsys)
        sim.init_full_review()
        sim.record_findings([
            ("r1-f1", "minor", "Style"),
            ("r1-f2", "major", "Missing tests"),
        ])
        out = sim.batch_fix_and_complete()
        assert out["awaiting_delta"] is True
        assert should_render_delta_prompt(
            json.loads((integ / "review-step-8.json").read_text()),
        )

        status = sim.delta_review(new_majors=None)
        assert status["done"] is True
        assert status["open_major"] == 0
        assert status["awaiting_delta"] is False

        c = sim.counters
        assert c.full_reviews == 1
        assert c.batch_fixes == 1
        assert c.check_sets == 1
        assert c.amends == 1
        assert c.delta_reviews == 1

    def test_delta_new_major_bumps_to_next_full(
        self, integ, monkeypatch, capsys,
    ):
        sim = ReviewFlowSimulator(integ, monkeypatch, capsys)
        sim.init_full_review()
        sim.record_findings([("r1-f1", "major", "Security hole")])
        assert sim.batch_fix_and_complete()["awaiting_delta"] is True

        status = sim.delta_review(
            new_majors=[("r1-f2", "major", "Regression from fix")],
        )
        assert status["open_major"] == 1
        assert status["needs_fix"] is True
        assert status["round"] == 1

        sim.bump_full_round()
        status = _status(capsys)
        assert status["round"] == 2
        data = json.loads((integ / "review-step-8.json").read_text())
        assert data["mode"] == "full"

        # Round 2: open-batch rebuilds from remaining open major only.
        batch = _open_batch(capsys)
        assert batch["has_major"] is True
        assert [f["id"] for f in batch["findings"]] == ["r1-f2"]
        sim.batch_fix_and_complete(["r1-f2"])
        status = sim.delta_review()
        assert status["done"] is True

        c = sim.counters
        assert c.full_reviews == 2
        assert c.batch_fixes == 2
        assert c.check_sets == 2
        assert c.amends == 2
        assert c.delta_reviews == 2


class TestInterruptedAmendRecovery:
    def test_complete_batch_resume_after_write_failure(
        self, integ, monkeypatch, capsys,
    ):
        sim = ReviewFlowSimulator(integ, monkeypatch, capsys)
        sim.init_full_review()
        sim.record_findings([
            ("r1-f1", "minor", "A"),
            ("r1-f2", "minor", "B"),
        ])
        batch = _open_batch(capsys)
        ids = [f["id"] for f in batch["findings"]]
        review_helper.main([
            "--name", "integ", "set-pending",
            "--step", "step-8",
            "--ids", ",".join(ids),
            "--base-commit", sim.base_sha,
        ])
        capsys.readouterr()
        sim.counters.record("batch_fix")

        new_sha = "fix0002"
        _patch_git(monkeypatch, new_sha, clean=True)
        sim.counters.record("check_set")
        sim.counters.record("amend")

        real_save = review_helper.save_review

        def boom(path, data):
            raise OSError("simulated interrupt after amend")

        monkeypatch.setattr(review_helper, "save_review", boom)
        with pytest.raises(OSError, match="simulated"):
            review_helper.main([
                "--name", "integ", "complete-batch",
                "--step", "step-8",
                "--ids", ",".join(ids),
                "--base-commit", "base0001",
                "--new-commit", new_sha,
                "--evidence", _evidence(new_sha),
            ])

        path = integ / "review-step-8.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["pending_findings"] == ids
        assert all(not f.get("completed_at") for f in data["findings"])

        monkeypatch.setattr(review_helper, "save_review", real_save)
        review_helper.main([
            "--name", "integ", "complete-batch",
            "--step", "step-8",
            "--ids", ",".join(ids),
            "--base-commit", "base0001",
            "--new-commit", new_sha,
            "--evidence", _evidence(new_sha),
        ])
        out = json.loads(capsys.readouterr().out)
        assert out["completed"] is True
        status = _status(capsys)
        assert status["done"] is True
        # One fix attempt path: still a single batch / check / amend pair
        # from the orchestrator's perspective (retry reuses same amend SHA).
        assert sim.counters.batch_fixes == 1
        assert sim.counters.check_sets == 1
        assert sim.counters.amends == 1


class TestLegacyReviewFile:
    def test_legacy_open_batch_rebuilds_from_open_findings(
        self, integ, capsys,
    ):
        path = integ / "review-step-8.json"
        path.write_text(json.dumps({
            "step_id": "step-8",
            "commit_sha": "legacysha",
            "round": 1,
            "findings": [
                {
                    "id": "old-f1",
                    "severity": "major",
                    "category": "security",
                    "title": "Legacy major",
                    "details": "still open",
                    "completed_at": "",
                },
                {
                    "id": "old-f2",
                    "severity": "minor",
                    "category": "other",
                    "title": "Already fixed",
                    "details": "",
                    "completed_at": "2026-01-01T00:00:00",
                },
            ],
        }) + "\n", encoding="utf-8")

        status = _status(capsys)
        assert status["needs_fix"] is True
        assert status["open_major"] == 1
        assert status["open_minor"] == 0

        batch = _open_batch(capsys)
        assert batch["has_major"] is True
        assert [f["id"] for f in batch["findings"]] == ["old-f1"]
        assert batch["pending_findings"] == []
        # Defaults present in query payload; legacy file not rewritten yet.
        assert batch["mode"] == "full"
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert "pending_findings" not in on_disk


class TestDisabledReviewWithMajor:
    def test_open_major_blocks_silent_complete(
        self, integ, monkeypatch, capsys,
    ):
        """step_review=false + open major → skipped probe must STOP."""
        from types import SimpleNamespace

        import prompt as prompt_mod

        review_helper.main([
            "--name", "integ", "init",
            "--step", "step-8", "--commit", "abc1234",
        ])
        _append("step-8", "r1-f1", "major", "Must fix")
        capsys.readouterr()
        status = _status(capsys)
        assert status["open_major"] == 1
        assert status["needs_fix"] is True
        assert status["done"] is False
        assert status["ready_to_complete"] is False

        # Orchestrator probes apply-review --json (does not read .spex.toml).
        monkeypatch.setattr(
            prompt_mod,
            "get_project_context",
            lambda *a, **k: SimpleNamespace(config={"step_review": False}),
        )
        monkeypatch.setattr(
            prompt_mod,
            "_build_metadata",
            lambda *a, **k: {"current_task_id": "step-8"},
        )
        args = SimpleNamespace(
            name="integ",
            commit_sha="abc1234",
            json_mode=True,
            mode=None,
        )
        with pytest.raises(SystemExit) as exc_info:
            prompt_mod._do_apply_review(args)
        assert exc_info.value.code == 0
        probe = json.loads(capsys.readouterr().out)
        assert probe["skipped"] is True
        assert probe["step_review"] is False
        assert probe["prompt"] == ""
        # Contract: skipped=true AND open_major > 0 → abnormal STOP
        # (not silent skip / Phase 7).
        assert probe["skipped"] is True and status["open_major"] > 0


class TestDirtyAndDetachedSafetyGates:
    def test_dirty_tree_blocks_complete_batch(
        self, integ, monkeypatch, capsys,
    ):
        sim = ReviewFlowSimulator(integ, monkeypatch, capsys)
        sim.init_full_review()
        sim.record_findings([("r1-f1", "minor", "Nit")])
        batch = _open_batch(capsys)
        ids = [f["id"] for f in batch["findings"]]
        review_helper.main([
            "--name", "integ", "set-pending",
            "--step", "step-8",
            "--ids", ",".join(ids),
            "--base-commit", "base0001",
        ])
        capsys.readouterr()
        _patch_git(monkeypatch, "fix0002", clean=False)
        with pytest.raises(SystemExit):
            review_helper.main([
                "--name", "integ", "complete-batch",
                "--step", "step-8",
                "--ids", ",".join(ids),
                "--base-commit", "base0001",
                "--new-commit", "fix0002",
                "--evidence", _evidence("fix0002"),
            ])
        data = json.loads(
            (integ / "review-step-8.json").read_text(encoding="utf-8"),
        )
        assert data["pending_findings"] == ["r1-f1"]
        assert all(not f.get("completed_at") for f in data["findings"])
        assert data.get("fixed_commit_sha") in ("", None)

    def test_head_mismatch_blocks_complete_batch(
        self, integ, monkeypatch, capsys,
    ):
        """Detached / wrong-HEAD gate: new SHA must equal current HEAD."""
        sim = ReviewFlowSimulator(integ, monkeypatch, capsys)
        sim.init_full_review()
        sim.record_findings([("r1-f1", "minor", "Nit")])
        batch = _open_batch(capsys)
        ids = [f["id"] for f in batch["findings"]]
        review_helper.main([
            "--name", "integ", "set-pending",
            "--step", "step-8",
            "--ids", ",".join(ids),
            "--base-commit", "base0001",
        ])
        capsys.readouterr()
        # Simulate amend landing elsewhere while HEAD stayed on base.
        _patch_git(monkeypatch, "base0001", clean=True)
        with pytest.raises(SystemExit):
            review_helper.main([
                "--name", "integ", "complete-batch",
                "--step", "step-8",
                "--ids", ",".join(ids),
                "--base-commit", "base0001",
                "--new-commit", "orphan99",
                "--evidence", _evidence("orphan99"),
            ])
        data = json.loads(
            (integ / "review-step-8.json").read_text(encoding="utf-8"),
        )
        assert data["pending_findings"] == ids
        assert all(not f.get("completed_at") for f in data["findings"])


class TestPromptSizeRegression:
    def test_compact_full_prompt_below_legacy_baseline(self, monkeypatch):
        """Rendered apply-review stays under hard cap / below ~30KiB baseline."""
        # Large enough that uncapped content would exceed the content budget.
        big_diff = "diff --git a/x b/x\n" + ("+line\n" * 4_000)
        monkeypatch.setattr(
            "prompt.fetch_review_diff",
            lambda *a, **k: big_diff,
        )
        findings = [
            {
                "id": f"r1-f{i}",
                "severity": "minor" if i % 2 else "major",
                "category": "tests",
                "title": f"Finding {i}",
                "details": "x" * 400,
                "completed_at": "",
            }
            for i in range(1, 6)
        ]
        review_data = {
            "step_id": "step-8",
            "commit_sha": "abc1234",
            "round": 1,
            "mode": "full",
            "findings": findings,
            "pending_findings": [],
            "pending_has_major": False,
        }
        metadata = {
            "current_task_id": "step-8",
            "current_task_description": (
                "Document and validate optimized review behavior.\n\n"
                "**Acceptance criteria**: both READMEs describe identical "
                "behavior; minor-only N-finding flow proves one full review, "
                "one batch fix, one check set, one amend, no subsequent review."
            ),
            # Concise field bypasses _trim_spec_content so size is controlled.
            "spec_content_concise": (
                "# Requirement\nOptimize Phase 6 review.\n"
                + ("requirement detail line\n" * 800)
            ),
            "commit_sha": "abc1234",
            "mode": "full",
        }
        uncapped_floor = (
            measure_prompt_bytes(metadata["spec_content_concise"])
            + measure_prompt_bytes(metadata["current_task_description"])
            + measure_prompt_bytes(big_diff)
        )
        assert uncapped_floor > PROMPT_CONTENT_BUDGET
        assert uncapped_floor > PROMPT_SIZE_REGRESSION_CEILING

        ctx = build_compact_review_context(
            metadata,
            mode="full",
            review_data=review_data,
        )
        content_total = (
            measure_prompt_bytes(ctx.get("spec_content_concise", ""))
            + measure_prompt_bytes(ctx.get("current_task_description", ""))
            + measure_prompt_bytes(ctx.get("acceptance_criteria", ""))
            + measure_prompt_bytes(ctx.get("open_findings", ""))
            + measure_prompt_bytes(ctx.get("commit_diff", ""))
        )
        assert content_total <= PROMPT_CONTENT_BUDGET
        assert content_total < LEGACY_REVIEW_PROMPT_BASELINE_BYTES
        assert ctx.get("acceptance_criteria")
        assert "Finding 1" in ctx.get("open_findings", "")
        assert ctx.get("current_task_description")

        rendered = render_prompt(
            "apply-review",
            metadata={
                "spec_content_concise": ctx.get("spec_content_concise", ""),
                "current_task_description": ctx.get(
                    "current_task_description", "",
                ),
                "acceptance_criteria": ctx.get("acceptance_criteria", ""),
                "open_findings": ctx.get("open_findings", ""),
                "commit_diff": ctx.get("commit_diff", ""),
                "commit_sha": "abc1234",
                "review_round": 1,
                "review_file": "/tmp/review-step-8.json",
                "step_id": "step-8",
                "spex_skill_dir": "/tmp/fake-skill",
                "spec_name": "integ",
                "review_mode": "full",
                "mode": "full",
                "check_evidence_reusable": False,
            },
        )
        rendered_bytes = measure_prompt_bytes(rendered)
        assert rendered_bytes <= PROMPT_SIZE_REGRESSION_CEILING
        assert rendered_bytes < LEGACY_REVIEW_PROMPT_BASELINE_BYTES
        assert "Review Checklist" in rendered

    def test_default_cap_below_legacy_baseline(self):
        """Hard cap is ~16KiB (not 30KiB/2); content budget reserves template."""
        assert DEFAULT_REVIEW_PROMPT_MAX_BYTES == 16_384
        assert DEFAULT_REVIEW_PROMPT_MAX_BYTES < LEGACY_REVIEW_PROMPT_BASELINE_BYTES
        assert PROMPT_CONTENT_BUDGET == (
            DEFAULT_REVIEW_PROMPT_MAX_BYTES - _TEMPLATE_HEADROOM_BYTES
        )
        assert PROMPT_SIZE_REGRESSION_CEILING == DEFAULT_REVIEW_PROMPT_MAX_BYTES
        assert PROMPT_SIZE_REGRESSION_CEILING < LEGACY_REVIEW_PROMPT_BASELINE_BYTES


class TestFullRoundCap:
    def test_max_round_delta_complete_skips_fourth_full(
        self, integ, monkeypatch, capsys,
    ):
        """At max full round, major complete-batch must not await delta/R4."""
        path = integ / "review-step-8.json"
        review_helper.main([
            "--name", "integ", "init",
            "--step", "step-8", "--commit", "base0001",
        ])
        # Force round to max with mode=delta (post-fix at hard cap).
        data = json.loads(path.read_text(encoding="utf-8"))
        data["round"] = review_helper.MAX_REVIEW_ROUND
        data["mode"] = "delta"
        data["commit_sha"] = "base0001"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        _append("step-8", "r3-f1", "major", "Last major")
        capsys.readouterr()

        review_helper.main([
            "--name", "integ", "set-pending",
            "--step", "step-8",
            "--ids", "r3-f1",
            "--base-commit", "base0001",
        ])
        capsys.readouterr()
        _patch_git(monkeypatch, "fix0002", clean=True)
        review_helper.main([
            "--name", "integ", "complete-batch",
            "--step", "step-8",
            "--ids", "r3-f1",
            "--base-commit", "base0001",
            "--new-commit", "fix0002",
            "--evidence", _evidence("fix0002"),
        ])
        out = json.loads(capsys.readouterr().out)
        assert out["awaiting_delta"] is False
        status = _status(capsys)
        assert status["round"] == review_helper.MAX_REVIEW_ROUND
        assert status["awaiting_delta"] is False
        assert status["done"] is True
        with pytest.raises(SystemExit):
            review_helper.main([
                "--name", "integ", "bump-round",
                "--step", "step-8", "--commit", "fix0002",
            ])
