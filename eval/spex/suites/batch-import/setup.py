"""Seed a committed checkpoint compatibility step for the resume case."""

import argparse
import json
import os
import subprocess
from pathlib import Path

SPEC = Path(".spex/specs/2000-01-01-00-00-batch-import")
BRANCH = "spex/batch-import"
SEED_TAG = "eval-batch-step-1"
SEED_TIME = "2000-01-02T00:00:00+00:00"

CHECKPOINT_CODE = '''
def read_checkpoint(connection):
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'import_checkpoint'"
    ).fetchone()
    if not table:
        return None
    row = connection.execute("SELECT data FROM import_checkpoint WHERE id = 1").fetchone()
    if not row:
        return None
    value = json.loads(row[0])
    version = value.get("version", 1)
    if version == 1:
        return dict(value, version=1, complete=False)
    if version != 2:
        raise ValueError(f"unknown checkpoint version {version}")
    return value


def write_checkpoint(connection, *, committed_rows, sha256, complete):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS import_checkpoint "
        "(id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)"
    )
    data = json.dumps(dict(version=2, committed_rows=committed_rows, sha256=sha256, complete=complete))
    connection.execute(
        "INSERT INTO import_checkpoint VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET data=excluded.data", (data,)
    )
'''

CHECKPOINT_TESTS = '''import sqlite3
import unittest
from contextlib import closing

from checkpoint import read_checkpoint, seed_legacy_checkpoint, write_checkpoint


class CheckpointTests(unittest.TestCase):
    def test_legacy_read_and_rollback_of_versioned_write(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            self.assertIsNone(read_checkpoint(connection))
            seed_legacy_checkpoint(connection, 2, "a" * 64)
            self.assertEqual(read_checkpoint(connection), {
                "version": 1, "committed_rows": 2, "sha256": "a" * 64, "complete": False,
            })
            connection.execute("BEGIN")
            write_checkpoint(connection, committed_rows=3, sha256="a" * 64, complete=True)
            self.assertEqual(read_checkpoint(connection), {
                "version": 2, "committed_rows": 3, "sha256": "a" * 64, "complete": True,
            })
            connection.rollback()
            self.assertEqual(read_checkpoint(connection)["committed_rows"], 2)

    def test_rejects_unknown_version(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            seed_legacy_checkpoint(connection, 2, "a" * 64)
            connection.execute(
                "UPDATE import_checkpoint SET data = ?", ('{"version": 99}',)
            )
            with self.assertRaisesRegex(ValueError, "version"):
                read_checkpoint(connection)
'''


def seed_resume(repo):
    env = dict(os.environ, GIT_AUTHOR_DATE=SEED_TIME, GIT_COMMITTER_DATE=SEED_TIME)

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, env=env, text=True).strip()

    git("switch", "-c", BRANCH)
    checkpoint = repo / "checkpoint.py"
    checkpoint.write_text(
        checkpoint.read_text(encoding="utf-8") + "\n" + CHECKPOINT_CODE,
        encoding="utf-8",
    )
    (repo / "test_checkpoint.py").write_text(CHECKPOINT_TESTS, encoding="utf-8")
    git("add", "--", "checkpoint.py", "test_checkpoint.py")
    git("commit", "-m", "Support legacy and versioned import checkpoints")
    git("tag", SEED_TAG)

    meta_path = repo / SPEC / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["spex_branch"] = BRANCH
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    todo_path = repo / SPEC / "todo.json"
    tasks = json.loads(todo_path.read_text(encoding="utf-8"))
    tasks[0].update(completed_at=SEED_TIME, commit_title=git("log", "-1", "--format=%h: %s"))
    todo_path.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("scenario", choices=("checkpoint-completed",))
    args = parser.parse_args()
    seed_resume(args.repo)
