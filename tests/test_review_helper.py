"""Unit tests for review_helper.py."""

from __future__ import annotations

import json
import logging

import pytest
import review_helper


@pytest.fixture()
def spec_dir(tmp_path, monkeypatch):
    """Create a fake spec dir and patch resolve_spec_dir."""
    d = tmp_path / "my-topic"
    d.mkdir()
    monkeypatch.setattr(
        review_helper, "resolve_spec_dir",
        lambda name, **kw: d,
    )
    return d


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _last_json_line(capsys):
    """Parse the last non-empty stdout line as JSON (skip prior init paths)."""
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return json.loads(lines[-1])


class TestStepNumber:
    def test_step_1(self):
        assert review_helper.step_number("step-1") == "1"

    def test_step_12(self):
        assert review_helper.step_number("step-12") == "12"

    def test_invalid(self):
        with pytest.raises(SystemExit):
            review_helper.step_number("no-digits")


class TestInit:
    def test_creates_file(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc1234",
        ])
        path = spec_dir / "review-step-1.json"
        assert path.is_file()
        data = _read(path)
        assert data["step_id"] == "step-1"
        assert data["commit_sha"] == "abc1234"
        assert data["round"] == 1
        assert data["findings"] == []
        out = json.loads(capsys.readouterr().out)
        assert out["review_file"] == str(path)
        assert out["step_id"] == "step-1"
        assert out["commit_sha"] == "abc1234"
        assert out["round"] == 1

    def test_resets_existing(self, spec_dir):
        path = spec_dir / "review-step-1.json"
        path.write_text(json.dumps({
            "step_id": "step-1",
            "commit_sha": "old",
            "round": 3,
            "findings": [{"id": "f1"}],
        }), encoding="utf-8")

        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "newsha",
        ])
        data = _read(path)
        assert data["commit_sha"] == "newsha"
        assert data["round"] == 1
        assert data["findings"] == []


class TestAppend:
    def test_append_major(self, spec_dir):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f1", "--severity", "major",
            "--category", "tests",
            "--title", "Missing tests",
            "--details", "Add unit tests",
        ])
        data = _read(spec_dir / "review-step-1.json")
        assert len(data["findings"]) == 1
        f = data["findings"][0]
        assert f["id"] == "f1"
        assert f["severity"] == "major"
        assert f["category"] == "tests"
        assert f["title"] == "Missing tests"
        assert f["details"] == "Add unit tests"
        assert f["completed_at"] == ""

    def test_lazy_create_with_commit(self, spec_dir):
        """First append without init creates the review file."""
        path = spec_dir / "review-step-1.json"
        assert not path.exists()
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1", "--commit", "deadbeef",
            "--id", "r1-f1", "--severity", "major",
            "--category", "tests",
            "--title", "First finding",
        ])
        assert path.is_file()
        data = _read(path)
        assert data["step_id"] == "step-1"
        assert data["commit_sha"] == "deadbeef"
        assert data["round"] == 1
        assert len(data["findings"]) == 1
        assert data["findings"][0]["id"] == "r1-f1"

    def test_lazy_create_requires_commit(self, spec_dir, caplog):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc:
                review_helper.main([
                    "--name", "my-topic", "append",
                    "--step", "step-1",
                    "--id", "r1-f1", "--severity", "major",
                    "--category", "tests",
                    "--title", "First finding",
                ])
        assert exc.value.code == 1
        assert "pass --commit" in caplog.text
        assert not (spec_dir / "review-step-1.json").exists()

    def test_append_minor_round1(self, spec_dir):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-2", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-2",
            "--id", "f1", "--severity", "minor",
            "--category", "code-quality",
            "--title", "Rename helper",
        ])
        data = _read(spec_dir / "review-step-2.json")
        assert data["findings"][0]["severity"] == "minor"

    def test_reject_minor_round2(self, spec_dir, caplog):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        path = spec_dir / "review-step-1.json"
        data = _read(path)
        data["round"] = 2
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc:
                review_helper.main([
                    "--name", "my-topic", "append",
                    "--step", "step-1",
                    "--id", "f1", "--severity", "minor",
                    "--category", "other",
                    "--title", "Nit",
                ])
        assert exc.value.code == 1
        assert "only allows major" in caplog.text

    def test_allow_major_round2(self, spec_dir):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        path = spec_dir / "review-step-1.json"
        data = _read(path)
        data["round"] = 2
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")

        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f1", "--severity", "major",
            "--category", "security",
            "--title", "Injection risk",
        ])
        data = _read(path)
        assert data["findings"][0]["severity"] == "major"

    def test_duplicate_id(self, spec_dir):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f1", "--severity", "major",
            "--category", "lint", "--title", "A",
        ])
        with pytest.raises(SystemExit):
            review_helper.main([
                "--name", "my-topic", "append",
                "--step", "step-1",
                "--id", "f1", "--severity", "major",
                "--category", "lint", "--title", "B",
            ])

    def test_details_from_stdin(self, spec_dir, monkeypatch):
        import io

        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        monkeypatch.setattr(
            "sys.stdin", io.StringIO("Line one\nLine two\n"),
        )
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f1", "--severity", "major",
            "--category", "tests", "--title", "T",
            "--details-from-stdin",
        ])
        data = _read(spec_dir / "review-step-1.json")
        assert data["findings"][0]["details"] == "Line one\nLine two\n"


class TestEdit:
    def test_mark_complete(self, spec_dir):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f1", "--severity", "major",
            "--category", "tests", "--title", "T",
        ])
        review_helper.main([
            "--name", "my-topic", "edit",
            "--step", "step-1", "--id", "f1",
            "--completed-at", "now",
        ])
        data = _read(spec_dir / "review-step-1.json")
        assert data["findings"][0]["completed_at"]
        assert data["findings"][0]["completed_at"] != "now"

    def test_not_found(self, spec_dir):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        with pytest.raises(SystemExit):
            review_helper.main([
                "--name", "my-topic", "edit",
                "--step", "step-1", "--id", "missing",
                "--completed-at", "now",
            ])


class TestBumpRound:
    def test_increments_and_updates_commit(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "r1-f1", "--severity", "minor",
            "--category", "other", "--title", "Keep me",
        ])
        review_helper.main([
            "--name", "my-topic", "bump-round",
            "--step", "step-1", "--commit", "def456",
        ])
        out = _last_json_line(capsys)
        assert out["round"] == 2
        assert out["commit_sha"] == "def456"
        assert out["findings_count"] == 1
        data = _read(spec_dir / "review-step-1.json")
        assert data["round"] == 2
        assert data["commit_sha"] == "def456"
        assert len(data["findings"]) == 1
        assert data["findings"][0]["id"] == "r1-f1"

    def test_requires_commit(self, spec_dir):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        with pytest.raises(SystemExit):
            review_helper.main([
                "--name", "my-topic", "bump-round",
                "--step", "step-1",
            ])


class TestStatus:
    def test_needs_fix_when_only_minors(self, spec_dir, capsys):
        """Minor-only findings must still trigger the fix loop."""
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f1", "--severity", "minor",
            "--category", "other", "--title", "Nit",
        ])
        review_helper.main([
            "--name", "my-topic", "status",
            "--step", "step-1", "--json",
        ])
        payload = _last_json_line(capsys)
        assert payload["open_major"] == 0
        assert payload["open_minor"] == 1
        assert payload["needs_fix"] is True
        assert payload["ready_to_complete"] is True
        assert payload["done"] is False

    def test_needs_fix_with_open_major(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f1", "--severity", "major",
            "--category", "tests", "--title", "T",
        ])
        review_helper.main([
            "--name", "my-topic", "status",
            "--step", "step-1", "--json",
        ])
        payload = _last_json_line(capsys)
        assert payload["open_major"] == 1
        assert payload["needs_fix"] is True
        assert payload["ready_to_complete"] is False
        assert payload["done"] is False

    def test_done_when_all_findings_complete(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f1", "--severity", "major",
            "--category", "tests", "--title", "T",
        ])
        review_helper.main([
            "--name", "my-topic", "edit",
            "--step", "step-1", "--id", "f1",
            "--completed-at", "now",
        ])
        review_helper.main([
            "--name", "my-topic", "status",
            "--step", "step-1", "--json",
        ])
        payload = _last_json_line(capsys)
        assert payload["open_major"] == 0
        assert payload["open_minor"] == 0
        assert payload["needs_fix"] is False
        assert payload["ready_to_complete"] is True
        assert payload["done"] is True

    def test_no_findings_is_done(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "status",
            "--step", "step-1", "--json",
        ])
        payload = _last_json_line(capsys)
        assert payload["needs_fix"] is False
        assert payload["done"] is True
        assert payload["exists"] is True

    def test_missing_file_is_clean(self, spec_dir, capsys):
        """No review file means no findings — not an error."""
        review_helper.main([
            "--name", "my-topic", "status",
            "--step", "step-1", "--json",
        ])
        payload = json.loads(capsys.readouterr().out)
        assert payload["exists"] is False
        assert payload["needs_fix"] is False
        assert payload["done"] is True
        assert payload["open_major"] == 0
        assert payload["open_minor"] == 0
        assert not (spec_dir / "review-step-1.json").exists()


class TestShow:
    def test_show_open_only(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f1", "--severity", "major",
            "--category", "tests", "--title", "Open one",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "f2", "--severity", "minor",
            "--category", "other", "--title", "Done one",
        ])
        review_helper.main([
            "--name", "my-topic", "edit",
            "--step", "step-1", "--id", "f2",
            "--completed-at", "now",
        ])
        review_helper.main([
            "--name", "my-topic", "show",
            "--step", "step-1", "--open",
        ])
        out = capsys.readouterr().out
        assert "Open one" in out
        assert "Done one" not in out

    def test_show_json(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        capsys.readouterr()  # drain init JSON
        review_helper.main([
            "--name", "my-topic", "show",
            "--step", "step-1", "--json",
        ])
        data = json.loads(capsys.readouterr().out)
        assert data["step_id"] == "step-1"
        assert data["findings"] == []


class TestFormatOpenFindings:
    def test_markdown(self):
        text = review_helper._format_open_findings_markdown([
            {
                "id": "f1",
                "severity": "major",
                "category": "tests",
                "title": "Missing",
                "details": "Add coverage",
                "completed_at": "",
            },
            {
                "id": "f2",
                "severity": "minor",
                "category": "other",
                "title": "Done",
                "details": "",
                "completed_at": "2026-01-01T00:00:00Z",
            },
        ])
        assert "### f1: Missing" in text
        assert "Add coverage" in text
        assert "f2" not in text


class TestNext:
    def test_returns_first_open(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "r1-f1", "--severity", "minor",
            "--category", "other", "--title", "First",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "r1-f2", "--severity", "major",
            "--category", "tests", "--title", "Second",
        ])
        capsys.readouterr()
        review_helper.main([
            "--name", "my-topic", "next", "--step", "step-1",
        ])
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] == "r1-f1"
        assert payload["open_count"] == 2
        assert payload["title"] == "First"

    def test_skips_completed(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "r1-f1", "--severity", "minor",
            "--category", "other", "--title", "First",
        ])
        review_helper.main([
            "--name", "my-topic", "append",
            "--step", "step-1",
            "--id", "r1-f2", "--severity", "major",
            "--category", "tests", "--title", "Second",
        ])
        review_helper.main([
            "--name", "my-topic", "edit",
            "--step", "step-1", "--id", "r1-f1",
            "--completed-at", "now",
        ])
        capsys.readouterr()
        review_helper.main([
            "--name", "my-topic", "next", "--step", "step-1",
        ])
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] == "r1-f2"
        assert payload["open_count"] == 1

    def test_none_when_all_done(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "init",
            "--step", "step-1", "--commit", "abc",
        ])
        capsys.readouterr()
        review_helper.main([
            "--name", "my-topic", "next", "--step", "step-1",
        ])
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] is None
        assert payload["open_count"] == 0
        assert payload["exists"] is True

    def test_missing_file_returns_null(self, spec_dir, capsys):
        review_helper.main([
            "--name", "my-topic", "next", "--step", "step-1",
        ])
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] is None
        assert payload["open_count"] == 0
        assert payload["exists"] is False
        assert not (spec_dir / "review-step-1.json").exists()
