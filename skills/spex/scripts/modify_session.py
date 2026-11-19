"""Publish recoverable spec revision snapshots."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from common import atomic_write_json

PENDING_NAME = "modify-pending.json"
SNAPSHOT_FILES = ("spec.md", "todo.json")


def _read_record(path):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(record, dict):
        raise ValueError(f"Invalid record: {path}")
    return record


def _fingerprint(directory):
    return {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in SNAPSHOT_FILES
    }


def _identity(directory):
    stat = directory.lstat()
    return [stat.st_dev, stat.st_ino]


def _validated_snapshot(path, record):
    if not path.is_dir() or path.is_symlink() or (
        _identity(path) != record.get("identity")
        or _fingerprint(path) != record.get("files")
    ):
        raise ValueError(f"Cannot verify modify snapshot: {path}")


def _bump(meta_path, meta, version):
    atomic_write_json(meta_path, {**meta, "version": version + 1})


def _versions_path(spec_dir):
    versions = spec_dir / "versions"
    if versions.is_symlink():
        raise ValueError(f"Modify versions directory is a symlink: {versions}")
    return versions


def _recover(spec_dir, meta, version, record):
    pending = spec_dir / PENDING_NAME
    previous = record.get("version")
    staging_name = record.get("staging")
    if type(previous) is not int or previous < 1 or (
        version not in (previous, previous + 1)
    ) or not isinstance(staging_name, str) or (
        not staging_name.startswith(".modify-") or "/" in staging_name
    ):
        raise ValueError(f"Invalid modify recovery record: {pending}")

    versions = _versions_path(spec_dir)
    snapshot = versions / str(previous)
    if snapshot.exists() or snapshot.is_symlink():
        _validated_snapshot(snapshot, record)
        if version == previous:
            if _fingerprint(spec_dir) != record["files"]:
                raise ValueError(f"Spec files changed since snapshot: {snapshot}")
            _bump(spec_dir / "meta.json", meta, version)
        pending.unlink()
        return version == previous

    if version != previous:
        raise ValueError(f"Missing published modify snapshot: {snapshot}")
    staging = versions / staging_name
    if staging.exists() or staging.is_symlink():
        _validated_snapshot(staging, record)
        shutil.rmtree(staging)
    elif _fingerprint(spec_dir) != record.get("files"):
        raise ValueError(f"Spec files changed since staging snapshot: {staging}")
    pending.unlink()
    return False


def _publish_snapshot(spec_dir, meta, version):
    versions = _versions_path(spec_dir)
    versions.mkdir(exist_ok=True)
    snapshot = versions / str(version)
    if snapshot.exists() or snapshot.is_symlink():
        raise ValueError(f"Modify snapshot already exists: {snapshot}")

    pending = spec_dir / PENDING_NAME
    with tempfile.TemporaryDirectory(prefix=".modify-", dir=versions) as directory:
        staging = Path(directory)
        for name in SNAPSHOT_FILES:
            shutil.copyfile(spec_dir / name, staging / name)
        atomic_write_json(pending, {
            "version": version, "staging": staging.name,
            "identity": _identity(staging), "files": _fingerprint(staging),
        })
        try:
            staging.rename(snapshot)
        except OSError:
            pending.unlink()
            raise
        try:
            _bump(spec_dir / "meta.json", meta, version)
        except Exception:
            shutil.rmtree(snapshot)
            pending.unlink()
            raise
    pending.unlink()


def begin(spec_dir):
    """Save the original files and advance the spec version once."""
    todo_backup = spec_dir / "todo.json.lock"
    if todo_backup.exists():
        raise ValueError(f"Unfinished todo transaction: {todo_backup}")
    meta = _read_record(spec_dir / "meta.json")
    if meta is None:
        raise ValueError(f"Missing spec metadata: {spec_dir / 'meta.json'}")
    version = meta.get("version", 1)
    if type(version) is not int or version < 1:
        raise ValueError(f"Invalid spec version in {spec_dir / 'meta.json'}")
    record = _read_record(spec_dir / PENDING_NAME)
    if record is None or not _recover(spec_dir, meta, version, record):
        _publish_snapshot(spec_dir, meta, version)
