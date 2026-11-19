"""Verify recoverable revision snapshots."""

import json
from io import StringIO
from pathlib import Path

import create_helper
import hooks
import meta_helper
import modify_session as session
import pytest


@pytest.fixture
def spec_dir(tmp_path):
    spec = tmp_path / "specs" / "example"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_bytes(b"# Original\r\n")
    (spec / "todo.json").write_bytes(b"[]\n")
    (spec / "meta.json").write_text('{"custom": true}', encoding="utf-8")
    return spec


def _meta(spec_dir):
    return json.loads((spec_dir / "meta.json").read_text(encoding="utf-8"))


def _contents(directory):
    return {
        path.relative_to(directory): None if path.is_dir() else path.read_bytes()
        for path in directory.rglob("*")
    }


def test_consecutive_revisions_preserve_legacy_snapshot(spec_dir):
    for version in (1, 2):
        before = {path: (spec_dir / path).read_bytes() for path in session.SNAPSHOT_FILES}
        session.begin(spec_dir)
        assert _meta(spec_dir) == {"version": version + 1, "custom": True}
        assert _contents(spec_dir / "versions" / str(version)) == {
            Path(name): data for name, data in before.items()
        }
        (spec_dir / "spec.md").write_bytes(b"# Revised\n")
    assert (spec_dir / "versions/1/spec.md").read_bytes() == b"# Original\r\n"


@pytest.mark.parametrize("after_bump", [False, True])
def test_recovers_process_interruption(spec_dir, monkeypatch, after_bump):
    bump = session._bump

    def interrupt(*args):
        if after_bump:
            bump(*args)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(session, "_bump", interrupt)
        with pytest.raises(KeyboardInterrupt):
            session.begin(spec_dir)

    snapshot = spec_dir / "versions/1"
    original = _contents(snapshot), snapshot.stat().st_ino
    session.begin(spec_dir)
    assert _meta(spec_dir)["version"] == (3 if after_bump else 2)
    assert (_contents(snapshot), snapshot.stat().st_ino) == original
    assert not (spec_dir / session.PENDING_NAME).exists()


def test_recovers_when_unpublished_staging_was_removed(spec_dir, monkeypatch):
    pending = spec_dir / session.PENDING_NAME

    def interrupt(*_args):
        assert pending.is_file()
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", interrupt)
        with pytest.raises(KeyboardInterrupt):
            session.begin(spec_dir)

    assert not list((spec_dir / "versions").iterdir())
    assert "version" not in _meta(spec_dir)
    session.begin(spec_dir)
    assert _meta(spec_dir)["version"] == 2
    assert (spec_dir / "versions/1/spec.md").read_bytes() == b"# Original\r\n"
    assert not pending.exists()


@pytest.mark.parametrize("recovering", [False, True])
def test_rejects_symlinked_versions(spec_dir, tmp_path, monkeypatch, recovering):
    versions = spec_dir / "versions"
    external = tmp_path / "external"
    if recovering:
        def interrupt(*_args):
            raise KeyboardInterrupt

        with monkeypatch.context() as patch:
            patch.setattr(session, "_bump", interrupt)
            with pytest.raises(KeyboardInterrupt):
                session.begin(spec_dir)
        versions.rename(external)
    else:
        external.mkdir()
    versions.symlink_to(external, target_is_directory=True)
    before = _contents(external)

    with pytest.raises(ValueError, match="versions directory is a symlink"):
        session.begin(spec_dir)
    assert _contents(external) == before
    assert "version" not in _meta(spec_dir)


@pytest.mark.parametrize("version", [0, True, None, "1"])
def test_rejects_invalid_versions(spec_dir, version):
    (spec_dir / "meta.json").write_text(json.dumps({"version": version}))
    with pytest.raises(ValueError, match="Invalid spec version"):
        session.begin(spec_dir)
    assert not (spec_dir / "versions").exists()


@pytest.mark.parametrize("failure", ["copy", "write", "collision", "damaged"])
def test_snapshot_failures(spec_dir, monkeypatch, failure):
    snapshot = spec_dir / "versions/1"

    def fail(*_args):
        raise OSError("write error")

    def interrupt(*_args):
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        if failure == "copy":
            (spec_dir / "todo.json").unlink()
        elif failure == "write":
            patch.setattr(session, "_bump", fail)
        elif failure == "collision":
            snapshot.mkdir(parents=True)
        else:
            patch.setattr(session, "_bump", interrupt)
            with pytest.raises(KeyboardInterrupt):
                session.begin(spec_dir)
            (snapshot / "todo.json").write_bytes(b"damaged")
        with pytest.raises((OSError, ValueError)):
            session.begin(spec_dir)
    assert "version" not in _meta(spec_dir)
    assert snapshot.exists() == (failure in {"collision", "damaged"})
    assert (spec_dir / session.PENDING_NAME).exists() == (failure == "damaged")


@pytest.mark.parametrize("args", [[], ["--name", "example"]])
def test_begin_requires_positional_name(spec_dir, args, monkeypatch):
    monkeypatch.setattr(create_helper, "get_spex_root", lambda **_: str(spec_dir.parent.parent))
    with pytest.raises(SystemExit) as exc:
        create_helper.main(["begin-modify", *args])
    assert exc.value.code == 2
    assert not (spec_dir / "versions").exists()
    create_helper.main(["begin-modify", "example"])
    assert _meta(spec_dir)["version"] == 2


@pytest.fixture
def begin_with_request(spec_dir, monkeypatch):
    monkeypatch.setattr(create_helper, "get_spex_root", lambda **_: str(spec_dir.parent.parent))
    monkeypatch.setattr("sys.stdin", StringIO("Revise the spec\n"))
    return lambda: create_helper.main(["begin-modify", "example", "--stdin"])


@pytest.mark.parametrize("rejected", [False, True])
def test_begin_runs_pre_action_after_snapshot_before_append(
    spec_dir, begin_with_request, monkeypatch, rejected,
):
    workdir = str(spec_dir.parent)
    original = {"version": 1, "workdir": workdir, "spex_branch": "spex/example", "custom": True}
    (spec_dir / "meta.json").write_text(json.dumps(original), encoding="utf-8")
    calls = []

    def pre_action(event, payload, **kwargs):
        calls.append((event, payload, kwargs))
        assert _meta(spec_dir) == {**original, "version": 2}
        assert (spec_dir / "versions/1/spec.md").read_bytes() == b"# Original\r\n"
        if rejected:
            raise SystemExit(1)

    monkeypatch.setattr(hooks, "run_pre_action", pre_action)
    if rejected:
        with pytest.raises(SystemExit) as exc:
            begin_with_request()
        assert exc.value.code == 1
        assert "prompts" not in _meta(spec_dir)
    else:
        begin_with_request()
        assert _meta(spec_dir)["prompts"][0]["text"] == "Revise the spec\n"
    assert calls == [
        ("modify", {"spex_branch": "spex/example"}, {"workdir": workdir, "spec_name": "example"})
    ]
    assert _meta(spec_dir)["custom"] is True


@pytest.mark.parametrize("saved", [False, True])
def test_begin_preserves_snapshot_when_request_save_fails(
    spec_dir, begin_with_request, monkeypatch, saved,
):
    monkeypatch.setattr(hooks, "run_pre_action", lambda *_args, **_kwargs: None)
    write = meta_helper.atomic_write_json

    def fail(path, data):
        if saved:
            write(path, data)
            raise KeyboardInterrupt
        raise OSError("Cannot write request")

    monkeypatch.setattr(meta_helper, "atomic_write_json", fail)
    message = "Check the spec state" if saved else "Cannot write request"
    with pytest.raises(SystemExit, match=message):
        begin_with_request()
    assert (spec_dir / "versions/1/spec.md").read_bytes() == b"# Original\r\n"
    assert _meta(spec_dir)["version"] == 2
    assert ("prompts" in _meta(spec_dir)) is saved
    assert not (spec_dir / session.PENDING_NAME).exists()
