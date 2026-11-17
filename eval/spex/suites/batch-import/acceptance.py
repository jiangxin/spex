"""Check committed behavior and Spex step boundaries for the import fixture."""

import argparse
import hashlib
import importlib
import importlib.abc
import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SPEC = Path(".spex/specs/2000-01-01-00-00-batch-import")
SEED_TAG = "eval-batch-step-1"
SEED_TIME = "2000-01-02T00:00:00+00:00"
VALID = b"id,payload\na,alpha\nb,bravo\na,replacement\nc,charlie\nd,delta\n"
BAD = b"id,payload\na,alpha\nb,bravo\nc,charlie\n,invalid\n"
CHANGED = VALID + b"e,echo\n"
EXPECTED = [("a", "alpha"), ("b", "bravo"), ("c", "charlie"), ("d", "delta")]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], timeout=10)


class Snapshot(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Import application modules from a commit without writing a checkout."""

    def __init__(self, repo, commit):
        self.repo = repo
        self.commit = commit
        files = git(repo, "ls-tree", "-rz", "--name-only", commit).decode().split("\0")
        self.files = {}
        for filename in files:
            path = Path(filename)
            if path.suffix == ".py":
                parts = path.with_suffix("").parts
                package = parts[-1] == "__init__"
                names = parts[:-1] if package else parts
                if names and all(part.isidentifier() for part in names):
                    self.files[".".join(names)] = (filename, package)

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.files:
            return importlib.util.spec_from_loader(fullname, self, is_package=self.files[fullname][1])
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        filename, _ = self.files[module.__name__]
        module.__file__ = str(self.repo / filename)
        source = git(self.repo, "show", f"{self.commit}:{filename}")
        exec(compile(source, module.__file__, "exec"), module.__dict__)


@contextmanager
def snapshot(repo, commit):
    loader = Snapshot(repo, commit)
    saved = {name: sys.modules.pop(name) for name in loader.files if name in sys.modules}
    sys.meta_path.insert(0, loader)
    try:
        yield
    finally:
        sys.meta_path.remove(loader)
        for name in loader.files:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


class MemoryDatabase(sqlite3.Connection):
    def close(self):
        """Keep the CLI's database available for inspection."""


@contextmanager
def database():
    connection = sqlite3.connect(":memory:", factory=MemoryDatabase)
    try:
        connection.execute("CREATE TABLE records (id TEXT PRIMARY KEY, payload TEXT)")
        yield connection
    finally:
        sqlite3.Connection.close(connection)


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def checkpoint(connection):
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'import_checkpoint'"
    ).fetchone()
    if not table:
        return None
    row = connection.execute("SELECT data FROM import_checkpoint WHERE id = 1").fetchone()
    return json.loads(row[0]) if row else None


def seed(connection, data=VALID, *, version=None, complete=False):
    with connection:
        connection.executemany("INSERT INTO records VALUES (?, ?)", EXPECTED[:2])
        connection.execute(
            "CREATE TABLE import_checkpoint "
            "(id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)"
        )
        fields = {"committed_rows": 2, "sha256": fingerprint(data)}
        if version is not None:
            fields.update(version=version, complete=complete)
        connection.execute("INSERT INTO import_checkpoint VALUES (1, ?)", (json.dumps(fields),))


def records(connection):
    return connection.execute("SELECT id, payload FROM records ORDER BY id").fetchall()


def state(connection):
    return records(connection), checkpoint(connection)


def cli(connection, data, *options, name="input.csv"):
    module = importlib.import_module("import_csv")
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(module, "open_database", return_value=connection), \
            patch.object(Path, "read_bytes", return_value=data), \
            redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            status = module.main([name, ":memory:", *options])
        except SystemExit as error:
            status = error.code
    return status or 0, stdout.getvalue(), stderr.getvalue()


def checkpoint_compatibility():
    module = importlib.import_module("checkpoint")
    with database() as conn:
        assert module.read_checkpoint(conn) is None
        assert checkpoint(conn) is None
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'import_checkpoint'"
        ).fetchone()
        seed(conn)
        before = state(conn), conn.total_changes
        legacy = module.read_checkpoint(conn)
        assert legacy == {
            "version": 1, "committed_rows": 2, "sha256": fingerprint(VALID), "complete": False,
        }
        assert (state(conn), conn.total_changes) == before
        conn.execute("BEGIN")
        module.write_checkpoint(conn, committed_rows=3, sha256=fingerprint(VALID), complete=True)
        written = module.read_checkpoint(conn)
        assert checkpoint(conn) == written == {
            "version": 2, "committed_rows": 3, "sha256": fingerprint(VALID), "complete": True,
        }
        assert conn.in_transaction
        conn.rollback()
        assert state(conn) == before[0]
    with database() as conn:
        seed(conn, version=99)
        before = state(conn), conn.total_changes
        try:
            module.read_checkpoint(conn)
        except ValueError as error:
            assert "version" in str(error).lower()
        else:
            raise AssertionError("unknown checkpoint version was accepted")
        assert (state(conn), conn.total_changes) == before


def batch_atomicity():
    importer = importlib.import_module("importer")
    with database() as conn:
        digest = fingerprint(BAD)
        importer.import_batch(conn, iter(EXPECTED[:2]), committed_rows=0, sha256=digest, complete=False)
        before = state(conn)
        assert before[1]["committed_rows"] == 2
        try:
            importer.import_batch(
                conn, iter([("c", "charlie"), ("", "bad")]),
                committed_rows=2, sha256=digest, complete=True,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("invalid batch succeeded")
        assert state(conn) == before
        assert not conn.in_transaction
        for operation in ("INSERT", "UPDATE"):
            conn.execute(
                f"CREATE TRIGGER fail_{operation} BEFORE {operation} ON import_checkpoint "
                "BEGIN SELECT RAISE(ABORT, 'checkpoint write failed'); END"
            )
        try:
            importer.import_batch(
                conn, iter([("c", "charlie")]), committed_rows=2, sha256=digest, complete=True,
            )
        except sqlite3.Error:
            pass
        else:
            raise AssertionError("checkpoint failure was swallowed")
        assert state(conn) == before
    with database() as conn:
        digest = fingerprint(VALID)
        importer.import_batch(conn, iter(EXPECTED[:2]), committed_rows=0, sha256=digest, complete=False)
        importer.import_batch(
            conn, iter([("a", "replacement"), ("c", "charlie")]),
            committed_rows=2, sha256=digest, complete=False,
        )
        assert checkpoint(conn)["committed_rows"] == 4
        assert records(conn) == EXPECTED[:3]


def legacy_cli():
    with database() as conn:
        assert cli(conn, VALID) == (0, "Processed 5 rows.\n", "")
        assert state(conn) == (EXPECTED, None)
    with database() as conn:
        status, out, err = cli(conn, BAD)
        assert status == 1 and not out and "nonempty id" in err
        assert state(conn) == ([], None)


def resume_cli():
    with database() as conn:
        seed(conn)
        assert cli(conn, VALID, "--resume")[0] == 0
        assert records(conn) == EXPECTED
        assert checkpoint(conn) == {
            "version": 2, "committed_rows": 5, "sha256": fingerprint(VALID), "complete": True,
        }
        before = state(conn), conn.total_changes
        assert cli(conn, VALID, "--resume")[0] == 0
        assert (state(conn), conn.total_changes) == before
    with database() as conn:
        for options in (("--resume",), ("--batch-size", "0"), ("--batch-size", "bad")):
            status, _, err = cli(conn, VALID, *options)
            assert status and err and state(conn) == ([], None)
        assert cli(conn, VALID, "--batch-size", "2")[0] == 0
        assert records(conn) == EXPECTED
        assert checkpoint(conn)["committed_rows"] == 5
        assert checkpoint(conn)["complete"] is True
    with database() as conn:
        assert cli(conn, BAD, "--batch-size", "2")[0] != 0
        assert records(conn) == EXPECTED[:2]
        assert checkpoint(conn)["committed_rows"] == 2
        assert checkpoint(conn)["complete"] is False
        before = state(conn), conn.total_changes
        status, _, err = cli(conn, BAD, "--batch-size", "2")
        error = err.lower()
        assert status and ("resume" in error or "incomplete checkpoint" in error)
        assert (state(conn), conn.total_changes) == before


def input_identity():
    with database() as conn:
        seed(conn)
        for complete in (False, True):
            if complete:
                assert checkpoint(conn)["complete"] is True
            before = state(conn), conn.total_changes
            status, _, err = cli(conn, CHANGED, "--resume")
            assert status and "input" in err.lower()
            assert (state(conn), conn.total_changes) == before
            assert cli(conn, VALID, "--resume", name="same-bytes.csv")[0] == 0
        assert records(conn) == EXPECTED


def ordered_steps(repo, scenario):
    history = git(repo, "rev-list", "--reverse", "--first-parent", "HEAD").decode().splitlines()
    tasks = json.loads((repo / SPEC / "todo.json").read_text(encoding="utf-8"))
    assert len(tasks) == 4 and len(history) == 5, "expected four step commits after the fixture"
    commits = history[1:]
    for index, (task, sha) in enumerate(zip(tasks, commits), 1):
        assert task["id"] == f"step-{index}" and task.get("completed_at"), f"step-{index} is incomplete"
        prefix, separator, subject = task.get("commit_title", "").partition(":")
        assert separator and 7 <= len(prefix) <= 40 and sha.startswith(prefix), (
            f"step-{index} does not identify its ordered commit"
        )
        actual = git(repo, "show", "-s", "--format=%s", sha).decode().strip()
        assert actual == subject.strip(), f"step-{index} commit subject differs"
        changed = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).decode().splitlines()
        assert any(Path(name).name.startswith("test_") for name in changed), f"step-{index} has no test change"
    assert not git(repo, "status", "--porcelain", "--untracked-files=all"), "worktree is dirty"
    if scenario == "apply-resume":
        assert git(repo, "rev-parse", SEED_TAG).decode().strip() == commits[0], "seed commit changed"
        assert tasks[0]["completed_at"] == SEED_TIME, "seed completion changed"
    return commits


def evaluate(repo, scenario):
    checks, errors = {}, {}

    def check(name, action):
        try:
            with redirect_stdout(sys.stderr):
                result = action()
        except Exception as error:
            checks[name] = False
            errors[name] = str(error) or type(error).__name__
            return None
        checks[name] = True
        return result

    commits = check("ordered-step-commits", lambda: ordered_steps(repo, scenario))
    if commits:
        milestones = (
            ("step-1-checkpoint-compatibility", checkpoint_compatibility),
            ("step-2-batch-atomicity", batch_atomicity),
            ("step-3-resume-cli", resume_cli),
            ("step-4-input-identity", input_identity),
        )
        for commit, (name, test) in zip(commits, milestones):
            with snapshot(repo, commit):
                check(name, test)
                check(name + "-legacy-cli", legacy_cli)
        with snapshot(repo, commits[-1]):
            for name, test in milestones[:-1]:
                check("final-" + name, test)
    return {"passed": all(checks.values()), "checks": checks, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("scenario", choices=("apply-all", "apply-resume"))
    args = parser.parse_args()
    result = evaluate(args.repo, args.scenario)
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
