"""Tests for create_helper.py — spec creation and branch validation."""

import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import config as cfg
import create_helper
import pytest
from config import ProjectContext, clear_config_cache
from create_helper import (
    cli_create_validate,
    cli_prepare_spec,
    create_spec,
    validate_create_branch,
    validate_create_name,
)


def _fake_project_context(**overrides):
    """Build a ProjectContext with sensible defaults, overriding as needed."""
    defaults = {
        "cwd": Path("."),
        "top_workdir": None,
        "main_worktree": None,
        "remote_url": "",
        "branch": "",
        "user_name": "",
        "user_email": "",
        "spex_tomls": [],
        "config": {},
        "spex_root": "",
        "spex_roots": [],
    }
    defaults.update(overrides)
    return ProjectContext(**defaults)


def _mock_ctx(
    top_workdir=None,
    main_worktree=None,
    remote_url="",
    branch="",
    user_name="",
    user_email="",
    config=None,
):
    """Build a ProjectContext for _write_meta tests."""
    return ProjectContext(
        cwd=top_workdir or Path("."),
        top_workdir=top_workdir,
        main_worktree=main_worktree,
        remote_url=remote_url,
        branch=branch,
        user_name=user_name,
        user_email=user_email,
        config=config if config is not None else {},
    )


class TestCreateTopic:
    def test_creates_directory(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        spec_name, spec_dir = create_spec(
            "2026-05-20-14-30-hello", specs_dir
        )

        assert spec_name == "2026-05-20-14-30-hello"
        assert spec_dir == specs_dir / "2026-05-20-14-30-hello"
        assert spec_dir.is_dir()


class TestDiscardIncompleteSpec:
    def test_removes_meta_only_stub(self, tmp_path):
        from create_helper import (
            discard_incomplete_spec,
            is_incomplete_spec_dir,
            is_incomplete_spec_stub,
        )

        specs = tmp_path / "specs"
        specs.mkdir()
        stub = specs / "2026-05-20-14-30-orphan"
        stub.mkdir()
        (stub / "meta.json").write_text("{}", encoding="utf-8")
        assert is_incomplete_spec_dir(stub) is True
        assert is_incomplete_spec_stub(stub, specs_dir=specs) is True
        assert discard_incomplete_spec(stub, specs_dir=specs) is True
        assert not stub.exists()

    def test_removes_empty_prepare_dir(self, tmp_path):
        from create_helper import discard_incomplete_spec

        specs = tmp_path / "specs"
        specs.mkdir()
        stub = specs / "2026-05-20-14-30-empty"
        stub.mkdir()
        assert discard_incomplete_spec(stub, specs_dir=specs) is True
        assert not stub.exists()

    def test_nested_logs_are_allowed_in_incomplete_spec(self, tmp_path):
        stub = tmp_path / "specs" / "2026-05-20-14-30-test"
        logs = stub / "logs"
        logs.mkdir(parents=True)
        (stub / "meta.json").write_text("{}")
        (logs / "trace.jsonl").touch()
        assert create_helper.is_incomplete_spec_stub(stub)
        (logs / "notes.txt").touch()
        assert not create_helper.is_incomplete_spec_stub(stub)

    def test_refuses_complete_spec(self, tmp_path):
        from create_helper import discard_incomplete_spec

        specs = tmp_path / "specs"
        specs.mkdir()
        spec = specs / "2026-05-20-14-30-done"
        spec.mkdir()
        (spec / "spec.md").write_text("# ok\n", encoding="utf-8")
        with pytest.raises(ValueError, match="spec.md already exists"):
            discard_incomplete_spec(spec, specs_dir=specs)
        assert spec.is_dir()

    def test_refuses_todo_without_spec(self, tmp_path):
        from create_helper import discard_incomplete_spec, is_incomplete_spec_stub

        specs = tmp_path / "specs"
        specs.mkdir()
        stub = specs / "2026-05-20-14-30-partial"
        stub.mkdir()
        (stub / "meta.json").write_text("{}", encoding="utf-8")
        (stub / "todo.json").write_text("[]", encoding="utf-8")
        assert is_incomplete_spec_stub(stub, specs_dir=specs) is False
        with pytest.raises(ValueError, match="not a prepare-spec stub"):
            discard_incomplete_spec(stub, specs_dir=specs)
        assert stub.is_dir()

    def test_refuses_outside_specs_dir(self, tmp_path):
        from create_helper import discard_incomplete_spec

        specs = tmp_path / "specs"
        other = tmp_path / "other"
        specs.mkdir()
        other.mkdir()
        stub = other / "2026-05-20-14-30-orphan"
        stub.mkdir()
        (stub / "meta.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="not a prepare-spec stub"):
            discard_incomplete_spec(stub, specs_dir=specs)
        assert stub.is_dir()

    def test_refuses_non_dated_name(self, tmp_path):
        from create_helper import discard_incomplete_spec

        specs = tmp_path / "specs"
        specs.mkdir()
        stub = specs / "not-a-spec-name"
        stub.mkdir()
        (stub / "meta.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="not a prepare-spec stub"):
            discard_incomplete_spec(stub, specs_dir=specs)
        assert stub.is_dir()

    def test_creates_specs_dir_if_missing(self, tmp_path):
        specs_dir = tmp_path / "specs"

        spec_name, spec_dir = create_spec(
            "2026-05-20-14-30-new-topic", specs_dir
        )

        assert specs_dir.is_dir()
        assert spec_dir.is_dir()

    def test_invalid_name_no_date(self, tmp_path):
        with pytest.raises(ValueError, match="invalid spec name"):
            create_spec("no-date-prefix", tmp_path, auto_prefix=False)

    def test_invalid_name_uppercase(self, tmp_path):
        with pytest.raises(ValueError, match="invalid spec name"):
            create_spec("2026-05-20-14-30-UpperCase", tmp_path)

    def test_invalid_name_spaces(self, tmp_path):
        with pytest.raises(ValueError, match="invalid spec name"):
            create_spec("2026-05-20-14-30-has space", tmp_path)

    def test_exceeds_max_bytes(self, tmp_path):
        long_name = "2026-05-20-14-30-" + "a" * 54
        with pytest.raises(ValueError, match="exceeds 64 bytes"):
            create_spec(long_name, tmp_path)

    def test_already_exists(self, tmp_path):
        specs_dir = tmp_path / "specs"
        (specs_dir / "2026-05-20-14-30-existing").mkdir(parents=True)

        with pytest.raises(FileExistsError, match="already exists"):
            create_spec("2026-05-20-14-30-existing", specs_dir)

    def test_valid_name_with_numbers(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        spec_name, spec_dir = create_spec(
            "2026-01-01-09-15-add-v2-api", specs_dir
        )

        assert spec_dir.is_dir()

    def test_auto_prefix_adds_date(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        with patch.object(
            create_helper, "datetime"
        ) as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-05-24-20-00"
            spec_name, spec_dir = create_spec("my-topic", specs_dir)

        assert spec_name == "2026-05-24-20-00-my-topic"
        assert spec_dir == specs_dir / "2026-05-24-20-00-my-topic"
        assert spec_dir.is_dir()

    def test_explicit_prefix_kept(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()

        spec_name, spec_dir = create_spec(
            "2026-05-20-14-30-hello", specs_dir
        )

        assert spec_name == "2026-05-20-14-30-hello"
        assert spec_dir.is_dir()

    def test_auto_prefix_false_no_prefix_fails(self, tmp_path):
        with pytest.raises(ValueError, match="invalid spec name"):
            create_spec("my-topic", tmp_path, auto_prefix=False)


class TestValidateCreateName:
    """Unit tests for create-helper validate-name rules."""

    def test_valid_name_and_description(self):
        result = validate_create_name(
            "add-login-api",
            "Add user login API with JWT authentication",
        )
        assert result == {
            "name": "add-login-api",
            "description": "Add user login API with JWT authentication",
        }

    def test_strips_whitespace(self):
        result = validate_create_name(
            "  add-login-api  ",
            "  Brief summary  ",
        )
        assert result["name"] == "add-login-api"
        assert result["description"] == "Brief summary"

    def test_rejects_empty_name(self):
        with pytest.raises(ValueError, match="name is required"):
            validate_create_name("", "ok description")

    def test_rejects_empty_description(self):
        with pytest.raises(ValueError, match="description is required"):
            validate_create_name("add-login-api", "   ")

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError, match="invalid name"):
            validate_create_name("Add-Login", "desc")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="invalid name"):
            validate_create_name("add login", "desc")

    def test_rejects_leading_hyphen(self):
        with pytest.raises(ValueError, match="invalid name"):
            validate_create_name("-add-login", "desc")

    def test_rejects_date_prefix(self):
        with pytest.raises(ValueError, match="date prefix"):
            validate_create_name(
                "2026-05-24-10-30-add-login",
                "desc",
            )

    def test_rejects_name_too_long(self):
        long_name = "a" * 32
        with pytest.raises(ValueError, match="at most 31 bytes"):
            validate_create_name(long_name, "desc")

    def test_accepts_name_at_max_bytes(self):
        name = "a" * 31
        result = validate_create_name(name, "desc")
        assert result["name"] == name

    def test_rejects_name_32_bytes_message(self, caplog):
        """32-byte name fails with the ≤31 wording (not '<32 bytes')."""
        import logging

        long_name = "a" * 32
        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc:
                create_helper.main(
                    [
                        "validate-name",
                        "--name", long_name,
                        "--description", "desc",
                    ]
                )
        assert exc.value.code == 1
        assert "at most 31 bytes" in caplog.text
        assert "<32 bytes" not in caplog.text

    def test_rejects_multiline_description(self):
        with pytest.raises(ValueError, match="single line"):
            validate_create_name("add-login-api", "line1\nline2")

    def test_cli_success_prints_json(self, capsys):
        create_helper.main(
            [
                "validate-name",
                "--name", " add-login-api ",
                "--description", " Add login API ",
            ]
        )
        out = json.loads(capsys.readouterr().out)
        assert out["name"] == "add-login-api"
        assert out["description"] == "Add login API"

    def test_cli_failure_exits_nonzero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            create_helper.main(
                [
                    "validate-name",
                    "--name", "BAD Name",
                    "--description", "desc",
                ]
            )
        assert exc.value.code == 1
        err = capsys.readouterr()
        # logging goes to stderr via logger; message may be in caplog
        # Ensure non-zero exit is the contract under test.
        assert err.out == ""


class TestWriteMeta:
    def test_meta_with_prompt(self, tmp_path):
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
            remote_url="git@github.com:user/project.git",
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "fix the login bug",
            "2026-05-24T20:00:00+08:00"
        )

        meta_path = spec_dir / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["workdir"] == "/home/user/project"
        assert meta["main_worktree"] == "/home/user/project"
        assert meta["remote_url"] == "git@github.com:user/project.git"
        assert meta["branch"] == "main"
        assert meta["user_name"] == "Alice"
        assert meta["user_email"] == "alice@example.com"
        assert meta["created_at"] == "2026-05-24T20:00:00+08:00"
        assert meta["version"] == 1
        assert meta["prompts"] == [
            {"text": "fix the login bug",
             "timestamp": "2026-05-24T20:00:00+08:00"},
        ]

    def test_meta_with_empty_prompt(self, tmp_path):
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "", "2026-05-24T20:00:00+08:00"
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        assert meta["prompts"] == []
        assert meta["remote_url"] == ""

    def test_worktree_main_worktree_points_to_main(self, tmp_path):
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project-wt"),
            main_worktree=Path("/home/user/project"),
            remote_url="git@github.com:user/project.git",
            branch="feature",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "add feature",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        assert meta["workdir"] == "/home/user/project-wt"
        assert meta["main_worktree"] == "/home/user/project"

    def test_ctx_none_workdir_is_empty(self, tmp_path):
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=None,
            main_worktree=None,
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "",
            "2026-05-29T10:00:00+08:00"
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        assert meta["workdir"] == ""
        assert meta["main_worktree"] == ""

    def test_json_field_order_without_description(self, tmp_path):
        """Verify task mode and version follow the legacy metadata fields."""
        spec_dir = tmp_path / "2026-01-01-10-00-order-test"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/work"),
            main_worktree=Path("/work"),
            remote_url="git@example.com:r.git",
            branch="main",
            user_name="Alice",
            user_email="a@e.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "hello",
            "2026-01-01T10:00:00+08:00",
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        keys = list(meta.keys())
        expected_keys = [
            "name", "workdir", "main_worktree", "remote_url",
            "branch", "user_name", "user_email", "created_at",
            "prompts", "use_git_worktree", "task_mode", "version",
        ]
        assert keys == expected_keys
        assert meta["use_git_worktree"] is False
        assert "description" not in meta
        assert "spex_branch" not in meta
        assert "spex_worktree" not in meta

    def test_json_field_order_with_description(self, tmp_path):
        """Verify description appears in correct position."""
        spec_dir = tmp_path / "2026-01-01-10-00-desc-order"
        spec_dir.mkdir()

        ctx = _mock_ctx(
            top_workdir=Path("/work"),
            main_worktree=Path("/work"),
            branch="main",
            user_name="Alice",
            user_email="a@e.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "",
            "2026-01-01T10:00:00+08:00",
            description="My feature desc",
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        keys = list(meta.keys())
        assert "description" in keys
        assert keys.index("description") == keys.index("prompts") + 1
        assert keys.index("use_git_worktree") == keys.index("description") + 1

    def test_write_meta_snapshots_use_git_worktree_false(self, tmp_path):
        """Create meta snapshots use_git_worktree=false by default."""
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()
        ctx = _mock_ctx(
            top_workdir=Path("/work"),
            main_worktree=Path("/work"),
            branch="main",
            user_name="Alice",
            user_email="a@e.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "", "2026-01-01T10:00:00+08:00",
        )
        meta = json.loads((spec_dir / "meta.json").read_text())
        assert meta["use_git_worktree"] is False
        assert "spex_worktree" not in meta

    def test_write_meta_snapshots_use_git_worktree_true(self, tmp_path):
        """Create meta snapshots use_git_worktree from ctx.config."""
        spec_dir = tmp_path / "topic"
        spec_dir.mkdir()
        ctx = _mock_ctx(
            top_workdir=Path("/work"),
            main_worktree=Path("/work"),
            branch="main",
            user_name="Alice",
            user_email="a@e.com",
            config={"use_git_worktree": True},
        )
        create_helper._write_meta(
            spec_dir, ctx, "", "2026-01-01T10:00:00+08:00",
        )
        meta = json.loads((spec_dir / "meta.json").read_text())
        assert meta["use_git_worktree"] is True
        assert "spex_worktree" not in meta


class TestCliPrepareSpec:
    def test_missing_topic_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with pytest.raises(SystemExit) as exc_info:
            cli_prepare_spec([])
        assert exc_info.value.code == 2

    def test_invalid_topic_exits(self, monkeypatch, tmp_path):
        import common
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            common, "get_specs_dir", return_value=str(tmp_path)
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli_prepare_spec(
                    ["--name", "INVALID", "--description", "desc"],
                )
            assert exc_info.value.code == 1

    def test_existing_topic_exits(self, monkeypatch, tmp_path):
        import common
        (tmp_path / "2026-05-20-14-30-existing").mkdir()
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with (
            patch.object(
                common, "get_specs_dir", return_value=str(tmp_path),
            ),
            patch.object(create_helper, "datetime") as mock_dt,
        ):
            mock_dt.now.return_value.strftime.return_value = (
                "2026-05-20-14-30"
            )
            with pytest.raises(SystemExit) as exc_info:
                cli_prepare_spec(
                    ["--name", "existing", "--description", "desc"],
                )
            assert exc_info.value.code == 1

    def test_rejects_name_too_long_for_validate_name(
        self, monkeypatch, tmp_path,
    ):
        """prepare-spec must reject names validate-name would reject."""
        import common
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            common, "get_specs_dir", return_value=str(tmp_path),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli_prepare_spec(
                    ["--name", "a" * 40, "--description", "desc"],
                )
            assert exc_info.value.code == 1

    def test_rejects_empty_description(self, monkeypatch, tmp_path):
        import common
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            common, "get_specs_dir", return_value=str(tmp_path),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli_prepare_spec(["--name", "add-login-api"])
            assert exc_info.value.code == 1

    def test_rejects_multiline_description(self, monkeypatch, tmp_path):
        import common
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            common, "get_specs_dir", return_value=str(tmp_path),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli_prepare_spec(
                    [
                        "--name", "add-login-api",
                        "--description", "line1\nline2",
                    ],
                )
            assert exc_info.value.code == 1

    def test_rejects_date_prefixed_name(self, monkeypatch, tmp_path):
        import common
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        with patch.object(
            common, "get_specs_dir", return_value=str(tmp_path),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli_prepare_spec(
                    [
                        "--name", "2026-05-20-14-30-new-topic",
                        "--description", "Test desc",
                    ],
                )
            assert exc_info.value.code == 1

    def test_success_outputs_json(self, monkeypatch, tmp_path, capsys):
        import common
        monkeypatch.setattr(sys, "stdin", io.StringIO("hello prompt"))

        mock_ctx = _mock_ctx(
            top_workdir=Path("/tmp/proj"),
            main_worktree=Path("/tmp/proj"),
            branch="main",
            user_name="Test",
            user_email="test@test.com",
        )

        import prompt as prompt_mod

        with (
            patch.object(
                common, "get_specs_dir",
                return_value=str(tmp_path)),
            patch.object(
                common, "local_iso_timestamp",
                return_value="2026-05-24T20:00:00+08:00"),
            patch.object(
                cfg, "get_project_context",
                return_value=mock_ctx),
            patch.object(
                prompt_mod, "render_prompt",
                return_value="# Rendered Template"),
            patch("hooks.run_pre_action"),
            patch.object(create_helper, "datetime") as mock_dt,
        ):
            mock_dt.now.return_value.strftime.return_value = (
                "2026-05-20-14-30"
            )
            cli_prepare_spec(
                ["--name", "new-topic",
                 "--description", "Test desc"])

        output = json.loads(capsys.readouterr().out.strip())
        assert output["spec_name"] == "2026-05-20-14-30-new-topic"
        assert output["spec_path"] == str(
            tmp_path / "2026-05-20-14-30-new-topic"
        )
        assert output["spec_template"] == "# Rendered Template"
        assert output["spec_prompt"] == "# Rendered Template"

        meta_path = tmp_path / "2026-05-20-14-30-new-topic" / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["prompts"] == [
            {"text": "hello prompt",
             "timestamp": "2026-05-24T20:00:00+08:00"},
        ]
        assert meta["description"] == "Test desc"


@pytest.fixture
def create_template_root(tmp_path, monkeypatch):
    import common

    specs = tmp_path / "specs"
    specs.mkdir()
    (tmp_path / "templates").mkdir()
    ctx = _fake_project_context(spex_root=str(tmp_path))
    monkeypatch.setattr(cfg, "get_project_context", lambda: ctx)
    monkeypatch.setattr(common, "get_project_storage", lambda _workdir: ctx)
    monkeypatch.setattr(common, "get_spex_root", lambda _workdir: str(tmp_path))
    monkeypatch.setattr(common, "get_specs_dir", lambda: specs)
    monkeypatch.setattr(sys, "stdin", io.StringIO("Retain recovery behavior."))
    return tmp_path


@pytest.mark.parametrize(("custom_prompt", "custom_skeleton"), [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
])
def test_prepare_renders_independent_templates(
    create_template_root, capsys, custom_prompt, custom_skeleton,
):
    templates = create_template_root / "templates"
    if custom_skeleton:
        (templates / "spec-template.md").write_text("# Custom skeleton", encoding="utf-8")
    if custom_prompt:
        (templates / "create-spec.md").write_text(
            "Custom {{ spec_name }}: {{ prompt_context }}", encoding="utf-8",
        )
    with patch("hooks.run_pre_action") as hook:
        cli_prepare_spec(["--name", "template-demo", "--description", "Test templates"])

    result = json.loads(capsys.readouterr().out)
    assert result["task_mode"] == "software"
    assert "Retain recovery behavior." in result["spec_prompt"]
    assert result["spec_name"] in result["spec_prompt"]
    assert result["spec_prompt"].startswith("Custom ") is custom_prompt
    assert (result["spec_template"] == "# Custom skeleton") is custom_skeleton
    if not custom_prompt:
        assert "implementation-critical facts" in result["spec_prompt"]
        assert "any deferred scope" in result["spec_prompt"]
        assert "any state that must be preserved" in result["spec_prompt"]
    if not custom_skeleton:
        assert "confirmed decisions, their rationale, and deferred scope" in result["spec_template"]
        assert "Give reproducible setup" in result["spec_template"]
    assert (templates / "examples" / "create-spec.md").is_file()
    hook.assert_called_once()


@pytest.mark.parametrize("custom", [False, True])
def test_prepare_and_render_general_templates(
    create_template_root, capsys, monkeypatch, custom,
):
    from prompt import main

    templates = create_template_root / "templates"
    for name in ("create-spec", "spec-template", "create-todo"):
        (templates / f"{name}.md").write_text("Software override", encoding="utf-8")
        if custom:
            (templates / f"general-{name}.md").write_text(
                f"General override for {name}", encoding="utf-8",
            )

    with patch("hooks.run_pre_action"):
        cli_prepare_spec([
            "--name", "general-demo", "--description", "General deliverables",
            "--mode", "general",
        ])
    prepared = json.loads(capsys.readouterr().out)
    spec_dir = Path(prepared["spec_path"])
    meta = json.loads((spec_dir / "meta.json").read_text(encoding="utf-8"))
    assert prepared["task_mode"] == meta["task_mode"] == "general"
    assert prepared["spec_template"].startswith("General override") is custom
    assert prepared["spec_prompt"].startswith("General override") is custom
    assert "Software override" not in prepared["spec_template"] + prepared["spec_prompt"]

    (spec_dir / "spec.md").write_text("# Local deliverables", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"task_mode": "software"}'))
    main(["create-todo", spec_dir.name])
    rendered = capsys.readouterr().out
    assert rendered.startswith("General override") is custom
    assert "Software override" not in rendered
    if not custom:
        assert "# Local deliverables" in rendered
        assert "resume from verified artifacts" in prepared["spec_prompt"]
        assert "confirmed decisions, their rationale, and deferred scope" in (
            prepared["spec_template"]
        )
        assert "output paths, observable acceptance criteria" in rendered
        assert "Spec sections: <heading>" in rendered
        assert "规格章节：<标题>" in rendered
    assert not (spec_dir / "todo.json").exists()


def test_prepare_anchor_failure_restores_logs_before_hook(
    create_template_root, capsys, caplog,
):
    log_id = "a" * 32
    logs = create_template_root / "tmp" / f"log-{log_id}"
    logs.mkdir(parents=True)
    debug_log = logs / "debug.log"
    debug_log.write_text("Existing history\n", encoding="utf-8")

    with (
        patch("debug_log.debug_enabled", return_value=True),
        patch(
            "create_helper._append_create_debug_anchor", side_effect=OSError("Anchor write failed"),
        ),
        patch("hooks.run_pre_action") as hook,
        pytest.raises(SystemExit) as failure,
    ):
        cli_prepare_spec([
            "--name", "anchor-failure", "--description", "Test anchor rollback",
            "--log-id", log_id,
        ])

    assert failure.value.code == 3
    hook.assert_not_called()
    assert capsys.readouterr().out == ""
    assert "Anchor write failed" in caplog.text
    assert f"--log-id {log_id}" in caplog.text
    assert debug_log.read_text(encoding="utf-8") == "Existing history\n"
    assert list((create_template_root / "specs").iterdir()) == []


def test_prepare_rejects_invalid_mode_before_storage_or_hooks(capsys):
    with (
        patch("common.get_specs_dir") as storage,
        patch("hooks.run_pre_action") as hook,
        pytest.raises(SystemExit) as failure,
    ):
        cli_prepare_spec(["--name", "mode-demo", "--mode", "unknown"])

    assert failure.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    storage.assert_not_called()
    hook.assert_not_called()


def test_spec_metadata_validates_explicit_modes_and_preserves_extensions(tmp_path, caplog):
    from common import Spec, SpecMeta, load_meta
    from task_mode import TaskModeError

    legacy = SpecMeta.from_dict({"extension": {"key": "value"}})
    assert legacy.task_mode == "software"
    assert legacy.to_dict()["extension"] == {"key": "value"}
    (tmp_path / "meta.json").write_text('{"task_mode": null}', encoding="utf-8")
    with pytest.raises(TaskModeError, match=r"meta\.json: Invalid task mode"):
        load_meta(tmp_path)
    assert Spec.from_dir(tmp_path) is None
    assert "meta.json: Invalid task mode" in caplog.text


@pytest.mark.parametrize(("mode", "template", "diagnostic"), [
    ("software", None, "Built-in template not found"),
    ("software", b"{% if prompt_context %}", "Unclosed if block"),
    ("software", b"---\nrequired:\n  - unknown\n---\nPrompt", "missing required metadata"),
    ("software", b"\n", "Rendered prompt is empty"),
    ("general", b"\n", "Rendered prompt is empty"),
    ("software", b"\xff", "invalid start byte"),
    ("software", b"Unreadable prompt", "Permission denied"),
])
def test_prepare_spec_prompt_failure_rolls_back_before_handoff(
    create_template_root, monkeypatch, capsys, caplog, mode, template, diagnostic,
):
    import common

    log_id = "a" * 32
    logs = create_template_root / "tmp" / f"log-{log_id}"
    logs.mkdir(parents=True)
    (logs / "debug.log").write_text("Preserve log history.\n")
    filename = "general-create-spec.md" if mode == "general" else "create-spec.md"
    if template is None:
        monkeypatch.setattr(common, "_get_skill_path", lambda: create_template_root / "missing")
    else:
        custom = create_template_root / "templates" / filename
        custom.write_bytes(template)
        if template == b"Unreadable prompt":
            read_text = Path.read_text

            def read_template(path, *args, **kwargs):
                if path == custom:
                    raise PermissionError("Permission denied")
                return read_text(path, *args, **kwargs)

            monkeypatch.setattr(Path, "read_text", read_template)
    with (
        patch("hooks.run_pre_action") as hook,
        patch("debug_log.TemporaryLogRoute.handoff") as handoff,
        pytest.raises(SystemExit) as failure,
    ):
        cli_prepare_spec([
            "--name", "bad-template", "--description", "Test rollback", "--mode", mode,
            "--log-id", log_id,
        ])

    assert failure.value.code == 2
    assert filename in caplog.text
    assert diagnostic in caplog.text
    assert not capsys.readouterr().out
    assert not list((create_template_root / "specs").iterdir())
    handoff.assert_not_called()
    assert (logs / "debug.log").read_text() == "Preserve log history.\n"
    hook.assert_not_called()


@pytest.mark.parametrize("failure", [PermissionError("meta denied"), SystemExit(1)])
def test_prepare_unexpected_failure_does_not_retry_name(
    create_template_root, capsys, caplog, failure,
):
    with (
        patch.object(create_helper, "_write_meta", side_effect=failure),
        pytest.raises(SystemExit) as result,
    ):
        cli_prepare_spec(["--name", "template-demo", "--description", "Test failure"])

    assert result.value.code == 3
    assert "Error preparing spec" in caplog.text
    assert not capsys.readouterr().out
    assert not list((create_template_root / "specs").iterdir())


@pytest.fixture
def create_todo_spec(create_template_root, monkeypatch):
    spec_dir = create_template_root / "specs" / "2026-05-20-14-30-todo"
    spec_dir.mkdir()
    (spec_dir / "todo.json").write_bytes(b"[null]\n")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    return spec_dir


def test_create_todo_uses_latest_saved_spec_and_its_canonical_name(
    create_template_root, create_todo_spec, capsys, monkeypatch,
):
    from prompt import main

    spec = create_todo_spec / "spec.md"
    initial = b"# First specification\n\nPreserve failure behavior.\n"
    spec.write_bytes(initial)
    main(["create-todo", "14-30-todo"])
    captured = capsys.readouterr().out
    assert create_todo_spec.name in captured
    assert "Spec sections: <heading>" in captured
    assert "规格章节：<标题>" in captured
    assert initial.decode() in captured
    assert spec.read_bytes() == initial
    assert (create_todo_spec / "todo.json").read_bytes() == b"[null]\n"

    updated = b"---\r\ndescription: Preserve this header\r\n---\r\n# Latest version\r\n"
    spec.write_bytes(updated)
    custom = create_template_root / "templates" / "create-todo.md"
    custom.write_text(
        "---\nrequired:\n  - spec_content\n---\n"
        "{{ spec_content }}\nPlan for {{ spec_name }}.",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "spec_content": "Stale specification", "spec_name": "Other name",
    })))
    main(["create-todo", "14-30-todo"])
    assert capsys.readouterr().out == f"{updated.decode()}\nPlan for {create_todo_spec.name}.\n"
    assert spec.read_bytes() == updated
    assert (create_todo_spec / "todo.json").read_bytes() == b"[null]\n"


@pytest.mark.parametrize(("option", "filename"), [
    ("--output", "spec.md"),
    ("-o", "todo.json"),
])
def test_create_todo_rejects_output_option_without_overwriting_inputs(
    create_todo_spec, capsys, caplog, option, filename,
):
    from prompt import main

    spec = create_todo_spec / "spec.md"
    spec_content = b"# Specification\n"
    spec.write_bytes(spec_content)

    with pytest.raises(SystemExit) as failure:
        main(["create-todo", create_todo_spec.name, option, str(create_todo_spec / filename)])

    assert failure.value.code == 1
    assert "create-todo writes to stdout" in caplog.text
    assert capsys.readouterr().out == ""
    assert spec.read_bytes() == spec_content
    assert (create_todo_spec / "todo.json").read_bytes() == b"[null]\n"


@pytest.mark.parametrize(("spec_content", "custom_prompt", "diagnostic"), [
    (None, None, "spec.md"),
    (b" \n", None, "requires a non-empty spec.md"),
    (b"\xff", None, "invalid start byte"),
    (b"# Spec\n", b"{% if spec_content %}", "Unclosed if block"),
    (b"# Spec\n", b"---\nrequired:\n  - unknown\n---\nPrompt", "missing required metadata"),
    (b"# Spec\n", b" \n", "rendered an empty prompt"),
    (b"# Spec\n", b"\xff", "invalid start byte"),
])
def test_create_todo_reports_input_errors_without_writing(
    create_template_root, create_todo_spec, capsys, caplog,
    spec_content, custom_prompt, diagnostic,
):
    from prompt import main

    spec = create_todo_spec / "spec.md"
    if spec_content is not None:
        spec.write_bytes(spec_content)
    if custom_prompt is not None:
        (create_template_root / "templates" / "create-todo.md").write_bytes(custom_prompt)

    with pytest.raises(SystemExit) as failure:
        main(["create-todo", create_todo_spec.name])

    assert failure.value.code == 1
    assert diagnostic in caplog.text
    assert capsys.readouterr().out == ""
    assert (spec.read_bytes() if spec.exists() else None) == spec_content
    assert (create_todo_spec / "todo.json").read_bytes() == b"[null]\n"


class TestValidateCreateBranch:
    @patch("branch.get_current_branch", return_value="main")
    def test_returns_current_branch(self, _mock):
        result = validate_create_branch(
            {"branch_management": True, "main_branch_name": "",
             "submit_method": "merge"})
        assert result == "main"

    @patch("branch.get_current_branch", return_value="main")
    def test_disabled_returns_current_branch(self, _mock):
        result = validate_create_branch(
            {"branch_management": False, "main_branch_name": "",
             "submit_method": "merge"})
        assert result == "main"

    @patch("branch.get_current_branch",
           side_effect=subprocess.CalledProcessError(1, "git"))
    def test_git_error_exits(self, _mock):
        try:
            validate_create_branch({"branch_management": True})
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1

    @patch("create_helper.list_working_tree_dirty_paths", return_value=[])
    @patch("branch.switch_branch")
    @patch("branch.get_current_branch", return_value="develop")
    def test_wrong_main_branch_auto_switches(self, _curr, _switch, _dirty):
        result = validate_create_branch({"branch_management": True,
                                         "main_branch_name": "main"})
        assert result == "main"
        _switch.assert_called_once_with("main", None)

    @patch("create_helper.list_working_tree_dirty_paths", return_value=[])
    @patch("branch.switch_branch")
    @patch("branch.get_current_branch", return_value="develop")
    def test_auto_switch_success_output(
        self, _curr, _switch, _dirty, caplog,
    ):
        import logging
        with caplog.at_level(logging.INFO):
            result = validate_create_branch({"branch_management": True,
                                             "main_branch_name": "main"})
        assert result == "main"
        assert "Warning" in caplog.text
        assert "Switching" in caplog.text
        assert "Switched to branch" in caplog.text

    @patch("create_helper.list_working_tree_dirty_paths", return_value=[])
    @patch("branch.switch_branch",
           side_effect=subprocess.CalledProcessError(
               1, "git", stderr="error: pathspec"))
    @patch("branch.get_current_branch", return_value="develop")
    def test_auto_switch_failure_exits(
        self, _curr, _switch, _dirty, caplog,
    ):
        import logging
        with caplog.at_level(logging.ERROR):
            try:
                validate_create_branch({"branch_management": True,
                                        "main_branch_name": "main"})
                assert False, "Should have called sys.exit(-1)"
            except SystemExit as e:
                assert e.code == -1
        assert "failed to switch" in caplog.text

    @patch("branch.switch_branch")
    @patch("branch.get_current_branch", return_value="feature")
    def test_dirty_tree_refuses_switch(self, _curr, _switch, caplog):
        import logging
        with (
            patch(
                "create_helper.list_working_tree_dirty_paths",
                return_value=["dirty.txt", "other.py"],
            ),
            caplog.at_level(logging.ERROR),
        ):
            try:
                validate_create_branch({
                    "branch_management": True,
                    "main_branch_name": "main",
                })
                assert False, "Should have called sys.exit(1)"
            except SystemExit as e:
                assert e.code == 1
        _switch.assert_not_called()
        assert "dirty.txt" in caplog.text
        assert "other.py" in caplog.text
        assert "refusing to switch" in caplog.text
        assert "Commit or stash" in caplog.text

    @patch("branch.get_current_branch", return_value="spex/feature")
    def test_spex_prefix_exits(self, _mock):
        try:
            validate_create_branch(
                {"branch_management": True, "main_branch_name": "",
                 "submit_method": "merge"})
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1

    @patch("branch.get_current_branch", return_value="spex/feature")
    def test_spex_prefix_error_includes_hint(self, _mock, caplog):
        import logging
        with caplog.at_level(logging.ERROR):
            try:
                validate_create_branch(
                    {"branch_management": True, "main_branch_name": "",
                     "submit_method": "merge"})
            except SystemExit:
                pass
        assert "main_branch_name" in caplog.text
        assert "Hint" in caplog.text


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with user config and an initial commit."""
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=str(path), capture_output=True, check=True,
    )
    (path / "README").write_text("init\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "."], cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path), capture_output=True, check=True,
    )


class TestValidateCreateBranchDirtyIntegration:
    """Real-git coverage for dirty-tree guard before auto-switch."""

    def test_dirty_feature_branch_refuses_and_stays(self, tmp_path, caplog):
        import logging

        _init_git_repo(tmp_path)
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(tmp_path), capture_output=True, check=True,
        )
        (tmp_path / "dirty.txt").write_text("dirty\n", encoding="utf-8")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc:
                validate_create_branch(
                    {"branch_management": True, "main_branch_name": "main"},
                    cwd=str(tmp_path),
                )
        assert exc.value.code == 1
        assert "dirty.txt" in caplog.text
        assert "refusing to switch" in caplog.text
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(tmp_path), capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert branch == "feature"

    def test_clean_feature_branch_switches_to_main(self, tmp_path):
        _init_git_repo(tmp_path)
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(tmp_path), capture_output=True, check=True,
        )

        result = validate_create_branch(
            {"branch_management": True, "main_branch_name": "main"},
            cwd=str(tmp_path),
        )
        assert result == "main"
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(tmp_path), capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert branch == "main"


class TestCliPostAction:
    def _setup_topic(self, tmp_path, name, todo_data):
        spec_dir = tmp_path / name
        spec_dir.mkdir()
        (spec_dir / "todo.json").write_text(
            json.dumps(todo_data, indent=2), encoding="utf-8",
        )
        meta = {"name": name, "workdir": str(tmp_path)}
        (spec_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )
        return spec_dir

    def test_validates_json(self, tmp_path, monkeypatch):
        """post-action validates todo.json successfully."""
        todo = [{"id": "step-1", "name": "First",
                 "details": "D", "completed_at": "",
                 "commit_title": ""}]
        spec_dir = self._setup_topic(
            tmp_path, "my-topic", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--name", "my-topic"],
            )

        assert (spec_dir / "todo.json").is_file()

    def test_allows_optional_skip_commit(self, tmp_path, monkeypatch):
        """post-action accepts optional skip_commit on todo items."""
        todo = [{"id": "step-1", "name": "First",
                 "details": "D", "completed_at": "",
                 "commit_title": "", "skip_commit": "auto"}]
        spec_dir = self._setup_topic(
            tmp_path, "my-topic", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--name", "my-topic"],
            )

    def test_rejects_invalid_skip_commit(self, tmp_path, monkeypatch):
        """post-action rejects unknown skip_commit values."""
        todo = [{"id": "step-1", "name": "First",
                 "details": "D", "completed_at": "",
                 "commit_title": "", "skip_commit": "yes"}]
        spec_dir = self._setup_topic(
            tmp_path, "my-topic", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with pytest.raises(SystemExit) as exc:
            create_helper.cli_post_action(
                ["--name", "my-topic"],
            )
        assert exc.value.code == 1

    def test_missing_json_fails(self, tmp_path, monkeypatch):
        """post-action errors when todo.json does not exist."""
        spec_dir = tmp_path / "no-json"
        spec_dir.mkdir()
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--name", "no-json"],
            )

    def test_missing_required_field_fails(
        self, tmp_path, monkeypatch,
    ):
        """post-action fails when a required field is missing."""
        todo = [{"id": "step-1", "name": "First"}]
        spec_dir = self._setup_topic(
            tmp_path, "bad-field", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--name", "bad-field"],
            )

    def test_duplicate_id_fails(self, tmp_path, monkeypatch):
        """post-action fails when step IDs are duplicated."""
        todo = [
            {"id": "step-1", "name": "A", "details": "D",
             "completed_at": "", "commit_title": ""},
            {"id": "step-1", "name": "B", "details": "D",
             "completed_at": "", "commit_title": ""},
        ]
        spec_dir = self._setup_topic(
            tmp_path, "dup-id", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )
        with pytest.raises(SystemExit):
            create_helper.cli_post_action(
                ["--name", "dup-id"],
            )

    def test_default_event_type_is_create(
        self, tmp_path, monkeypatch,
    ):
        """post-action defaults event-type to 'create'."""
        todo = [{"id": "s1", "name": "N", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        spec_dir = self._setup_topic(
            tmp_path, "evt-topic", todo,
        )
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with patch("hooks.run_post_action") as mock_hook:
            create_helper.cli_post_action(
                ["--name", "evt-topic"],
            )
            mock_hook.assert_called_once()
            assert mock_hook.call_args[0][0] == "create"


class TestCliFinalize:
    def _setup_finalize(self, tmp_path, name, todo_data=None):
        spec_dir = tmp_path / name
        spec_dir.mkdir()
        if todo_data is None:
            todo_data = [{
                "id": "s1", "name": "Step 1", "details": "D",
                "completed_at": "", "commit_title": "",
            }]
        todo_path = spec_dir / "todo.json"
        todo_path.write_text(json.dumps(todo_data), encoding="utf-8")
        (todo_path.with_name("todo.json.lock")).write_text(
            json.dumps(todo_data), encoding="utf-8",
        )
        (spec_dir / "meta.json").write_text(json.dumps({
            "name": name,
            "workdir": str(tmp_path),
            "description": "Before",
        }), encoding="utf-8")
        return spec_dir

    def _patch_spec_resolution(self, monkeypatch, spec_dir):
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir", lambda _name: spec_dir,
        )

    def test_requires_name(self):
        with pytest.raises(SystemExit) as exc:
            create_helper.cli_finalize([])
        assert exc.value.code == 2

    def test_missing_backup_warns_and_runs_post_action(
        self, tmp_path, monkeypatch, caplog,
    ):
        spec_dir = self._setup_finalize(tmp_path, "missing-backup")
        (spec_dir / "todo.json.lock").unlink()
        self._patch_spec_resolution(monkeypatch, spec_dir)

        with patch("hooks.run_post_action") as hook:
            create_helper.cli_finalize(["missing-backup"])

        hook.assert_called_once()
        assert "not found; skipping commit" in caplog.text

    def test_invalid_todo_fails_before_post_action(
        self, tmp_path, monkeypatch,
    ):
        invalid = [{"id": "s1", "name": "Step 1"}]
        spec_dir = self._setup_finalize(tmp_path, "invalid-todo", invalid)
        self._patch_spec_resolution(monkeypatch, spec_dir)

        with patch("hooks.run_post_action") as hook, pytest.raises(SystemExit):
            create_helper.cli_finalize(["invalid-todo"])

        hook.assert_not_called()
        assert (spec_dir / "todo.json.lock").is_file()

    def test_description_write_failure_prevents_hook_and_commit(
        self, tmp_path, monkeypatch,
    ):
        spec_dir = self._setup_finalize(tmp_path, "description-failure")
        (spec_dir / "spec.md").write_text(
            "---\ndescription: Updated description\n---\n\n# Spec\n",
            encoding="utf-8",
        )
        self._patch_spec_resolution(monkeypatch, spec_dir)
        monkeypatch.setattr(
            create_helper, "atomic_write_json",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read-only")),
        )

        with patch("hooks.run_post_action") as hook, pytest.raises(OSError):
            create_helper.cli_finalize(["description-failure"])

        hook.assert_not_called()
        assert (spec_dir / "todo.json.lock").is_file()

    def test_missing_hook_still_commits_transaction(
        self, tmp_path, monkeypatch,
    ):
        spec_dir = self._setup_finalize(tmp_path, "no-hook")
        self._patch_spec_resolution(monkeypatch, spec_dir)

        with patch("hooks.find_hook", return_value=None), patch(
            "hooks.get_project_context", return_value=_fake_project_context(),
        ):
            create_helper.cli_finalize(["no-hook"])

        assert not (spec_dir / "todo.json.lock").exists()

    def test_runs_post_action_before_transaction_commit(
        self, tmp_path, monkeypatch,
    ):
        spec_dir = self._setup_finalize(tmp_path, "ordered-finalize")
        (spec_dir / "spec.md").write_text(
            "---\ndescription: Updated description\n---\n\n# Spec\n",
            encoding="utf-8",
        )
        self._patch_spec_resolution(monkeypatch, spec_dir)

        import todo_helper

        events = []
        original_validate = todo_helper.validate_todo
        original_atomic_write = create_helper.atomic_write_json
        original_transaction = todo_helper.cmd_transaction

        def record_validate(path, **kwargs):
            events.append("validate")
            return original_validate(path, **kwargs)

        def record_metadata_write(path, data):
            events.append("description")
            return original_atomic_write(path, data)

        def record_anchor(_path, _line):
            events.append("anchor")

        def record_hook(*args):
            events.append("hook")

        def record_transaction(path, action):
            events.append("commit")
            return original_transaction(path, action)

        monkeypatch.setattr(todo_helper, "validate_todo", record_validate)
        monkeypatch.setattr(create_helper, "atomic_write_json", record_metadata_write)
        monkeypatch.setattr(create_helper, "_append_create_debug_anchor", record_anchor)
        monkeypatch.setattr("debug_log.debug_enabled", lambda _argv: True)
        monkeypatch.setattr("debug_log.prepare_spec_log_parent", lambda _path: True)
        monkeypatch.setattr(todo_helper, "cmd_transaction", record_transaction)
        with patch("hooks.run_post_action", side_effect=record_hook) as hook:
            create_helper.cli_finalize(["ordered-finalize"])

        assert events == [
            "validate", "description", "anchor", "hook", "commit", "validate",
        ]
        hook.assert_called_once_with(
            "create",
            {"spex_branch": "", "done": 0, "undone": 1},
            str(tmp_path),
            "ordered-finalize",
        )
        meta = json.loads((spec_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["description"] == "Updated description"
        assert not (spec_dir / "todo.json.lock").exists()

    def test_commit_failure_reports_commit_only_recovery_and_hook_runs_once(
        self, tmp_path, monkeypatch, caplog,
    ):
        spec_dir = self._setup_finalize(tmp_path, "commit-recovery")
        self._patch_spec_resolution(monkeypatch, spec_dir)
        import todo_helper

        hook_calls = []
        real_atomic_write = todo_helper.atomic_write_json
        with patch("hooks.run_post_action", side_effect=lambda *args: hook_calls.append(args)):
            monkeypatch.setattr(
                todo_helper, "atomic_write_json",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
            )
            with pytest.raises(SystemExit) as exc:
                create_helper.cli_finalize(["commit-recovery"])
            assert exc.value.code == 1
            assert (spec_dir / "todo.json.lock").is_file()
            assert "spex todo-helper transaction commit commit-recovery" in caplog.text
            assert "create-helper finalize" not in caplog.text

            monkeypatch.setattr(todo_helper, "atomic_write_json", real_atomic_write)
            todo_helper.cmd_transaction(spec_dir / "todo.json", "commit")

        assert len(hook_calls) == 1
        assert not (spec_dir / "todo.json.lock").exists()

    def test_nonzero_hook_does_not_prevent_transaction_commit(
        self, tmp_path, monkeypatch, caplog,
    ):
        spec_dir = self._setup_finalize(tmp_path, "hook-failure")
        self._patch_spec_resolution(monkeypatch, spec_dir)

        monkeypatch.setattr(
            "hooks._build_event_data", lambda *_args: {"event_type": "create"},
        )

        hook = spec_dir / "post-action"
        monkeypatch.setattr("hooks.find_hook", lambda *_args: hook)
        monkeypatch.setattr("hooks._is_safe_to_execute", lambda *_args: True)
        monkeypatch.setattr(
            "hooks.subprocess.run",
            lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, stderr="hook failed"),
        )
        create_helper.cli_finalize(["hook-failure"])

        assert "exited with code 1" in caplog.text
        assert not (spec_dir / "todo.json.lock").exists()


class TestCliCreateValidate:
    @patch("branch.get_current_branch", return_value="develop")
    @patch("config.get_project_context", return_value=_fake_project_context(
        config={
            "branch_management": True, "main_branch_name": "",
            "submit_method": "merge", "spex_root": ".spex"}))
    def test_outputs_success(self, _ctx, _branch, caplog):
        import logging
        with caplog.at_level(logging.INFO):
            cli_create_validate()
        assert "develop" in caplog.text
        assert "Valid" in caplog.text



class TestDescriptionWrapping:
    def test_write_meta_wraps_long_description(self, tmp_path):
        """_write_meta wraps descriptions longer than 68 chars."""
        spec_dir = tmp_path / "2026-01-01-10-00-wrap-test"
        spec_dir.mkdir()

        long_desc = (
            "This is a very long description that should definitely "
            "exceed the sixty-eight character limit and be wrapped "
            "into multiple lines by the wrap_text function"
        )
        ctx = _mock_ctx(
            top_workdir=Path("/home/user/project"),
            main_worktree=Path("/home/user/project"),
            branch="main",
            user_name="Alice",
            user_email="alice@example.com",
        )
        create_helper._write_meta(
            spec_dir, ctx, "",
            "2026-01-01T10:00:00+08:00", long_desc,
        )

        meta = json.loads((spec_dir / "meta.json").read_text())
        desc = meta["description"]
        assert "\n" in desc
        for line in desc.splitlines():
            assert len(line) <= 68

    def test_post_action_updates_description_from_spec(
        self, tmp_path, monkeypatch,
    ):
        """post-action updates meta.json description from spec.md."""
        spec_dir = tmp_path / "desc-topic"
        spec_dir.mkdir()

        # Write spec.md with front-matter description
        spec_content = (
            "---\n"
            "description: >\n"
            "  This is a long description from the spec front-matter"
            " that should be wrapped properly when saved to meta\n"
            "---\n"
            "\n# Spec content\n"
        )
        (spec_dir / "spec.md").write_text(
            spec_content, encoding="utf-8",
        )

        # Write valid todo.json
        todo = [{"id": "s1", "name": "Step 1", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        (spec_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )

        # Write initial meta.json
        meta = {"name": "desc-topic", "workdir": str(tmp_path)}
        (spec_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )

        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--name", "desc-topic"],
            )

        updated_meta = json.loads(
            (spec_dir / "meta.json").read_text(),
        )
        assert "description" in updated_meta
        assert updated_meta["description"] != ""

    def test_post_action_no_description_leaves_meta_unchanged(
        self, tmp_path, monkeypatch,
    ):
        """post-action leaves meta.json unchanged if no description."""
        spec_dir = tmp_path / "no-desc-topic"
        spec_dir.mkdir()

        # Write spec.md without description in front-matter
        spec_content = (
            "---\n"
            "title: My Spec\n"
            "---\n"
            "\n# Spec content\n"
        )
        (spec_dir / "spec.md").write_text(
            spec_content, encoding="utf-8",
        )

        # Write valid todo.json
        todo = [{"id": "s1", "name": "Step 1", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        (spec_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )

        # Write initial meta.json with existing description
        meta = {
            "name": "no-desc-topic",
            "workdir": str(tmp_path),
            "description": "original description",
        }
        (spec_dir / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )

        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with patch("hooks.run_post_action"):
            create_helper.cli_post_action(
                ["--name", "no-desc-topic"],
            )

        updated_meta = json.loads(
            (spec_dir / "meta.json").read_text(),
        )
        assert updated_meta["description"] == "original description"


class TestPostActionDebugAnchors:
    """Tests for post-action debug anchors."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_config_cache()
        yield
        clear_config_cache()

    def _ctx(self, tmp_path, *, debug=False):
        spex_root = tmp_path / ".spex"
        (spex_root / "specs").mkdir(parents=True, exist_ok=True)
        return ProjectContext(
            cwd=tmp_path,
            top_workdir=tmp_path,
            main_worktree=tmp_path,
            remote_url="",
            branch="main",
            user_name="Test",
            user_email="test@test.com",
            spex_tomls=[],
            config={"debug": debug},
            spex_root=str(spex_root),
            spex_roots=[str(spex_root)],
        )

    def test_post_action_writes_anchor_when_debug_enabled(
        self, tmp_path, monkeypatch,
    ):
        todo = [
            {"id": "step-1", "name": "First", "details": "D",
             "completed_at": "", "commit_title": ""},
            {"id": "step-2", "name": "Second", "details": "D",
             "completed_at": "", "commit_title": ""},
        ]
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "2026-08-04-15-50-post"
        spec_dir.mkdir(parents=True)
        (spec_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "post", "workdir": str(tmp_path)}),
            encoding="utf-8",
        )
        ctx = self._ctx(tmp_path, debug=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("config.get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=True),
            patch("hooks.run_post_action"),
        ):
            create_helper.cli_post_action(
                ["--name", "2026-08-04-15-50-post"],
            )

        content = (spec_dir / "logs" / "debug.log").read_text(encoding="utf-8")
        assert content == (
            "===== CREATE post-action ok "
            "name=2026-08-04-15-50-post steps=2 =====\n"
        )

    def test_post_action_skips_anchor_when_debug_disabled(
        self, tmp_path, monkeypatch,
    ):
        todo = [{"id": "s1", "name": "N", "details": "D",
                 "completed_at": "", "commit_title": ""}]
        spex_root = tmp_path / ".spex"
        spec_dir = spex_root / "specs" / "2026-08-04-15-50-quiet"
        spec_dir.mkdir(parents=True)
        (spec_dir / "todo.json").write_text(
            json.dumps(todo, indent=2), encoding="utf-8",
        )
        (spec_dir / "meta.json").write_text(
            json.dumps({"name": "quiet", "workdir": str(tmp_path)}),
            encoding="utf-8",
        )
        ctx = self._ctx(tmp_path, debug=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "create_helper.resolve_spec_dir",
            lambda _name: spec_dir,
        )

        with (
            patch.object(cfg, "get_project_context", return_value=ctx),
            patch("config.get_project_context", return_value=ctx),
            patch("debug_log.debug_enabled", return_value=False),
            patch("hooks.run_post_action"),
        ):
            create_helper.cli_post_action(
                ["--name", "2026-08-04-15-50-quiet"],
            )

        assert not (spec_dir / "logs" / "debug.log").exists()
