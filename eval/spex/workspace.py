"""Discover eval cases and prepare reproducible Spex trial repositories."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]*")
SKILL_PATH = "skills/spex"


@dataclass(frozen=True)
class Case:
    suite: str
    definition: dict
    fixture: Path

    @property
    def id(self) -> str:
        return self.definition["id"]


def select_cases(
    suites: Path, *, suite: str = "", case_id: str = "", tag: str = ""
) -> list[Case]:
    """Select from validated manifests using exact suite, case and tag filters."""
    cases = []
    for manifest in sorted(suites.glob("*/cases.json")):
        name = manifest.parent.name
        if suite and name != suite:
            continue
        if manifest.parent.is_symlink() or manifest.is_symlink():
            raise ValueError(f"Expected a real suite manifest: {manifest}")
        definitions = json.loads(manifest.read_text(encoding="utf-8"))
        if not IDENTIFIER.fullmatch(name) or not isinstance(definitions, list):
            raise ValueError(f"Invalid suite manifest: {manifest}")
        seen = set()
        for definition in definitions:
            case = load_case(manifest, definition)
            if case.id in seen:
                raise ValueError(f"Duplicate case {name}/{case.id}")
            seen.add(case.id)
            if (not case_id or case_id == case.id) and (not tag or tag in definition["tags"]):
                cases.append(case)
    return cases


def load_case(manifest: Path, definition: dict) -> Case:
    if not isinstance(definition, dict) or any(
        not isinstance(definition.get(key), str) or not IDENTIFIER.fullmatch(definition[key])
        for key in ("id", "fixture")
    ):
        raise ValueError(f"Invalid case or fixture identifier in {manifest}")
    tags = definition.get("tags")
    turns = definition.get("turns")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError(f"Invalid tags in {manifest}: {definition['id']}")
    if not isinstance(turns, list) or not turns or any(
        not isinstance(turn, dict)
        or not isinstance(turn.get("input"), str)
        or not turn["input"].strip()
        or not isinstance(turn.get("checks"), list)
        for turn in turns
    ):
        raise ValueError(f"Invalid turns in {manifest}: {definition['id']}")
    fixtures = manifest.parent / "fixtures"
    fixture = fixtures / definition["fixture"]
    if fixtures.is_symlink() or fixture.is_symlink() or not fixture.is_dir():
        raise ValueError(f"Expected a real fixture directory: {fixture}")
    return Case(manifest.parent.name, definition, fixture)


@dataclass(frozen=True)
class Trial:
    directory: Path
    ref: str

    @property
    def repo(self) -> Path:
        return self.directory / "repo"

    @property
    def skill(self) -> Path:
        return self.repo / ".agents" / "skills" / "spex"

    @property
    def env(self) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(
            HOME=str(self.directory / "home"),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_ATTR_NOSYSTEM="1",
            SPEX_CONFIG_FILE=str(self.repo / ".spex.toml"),
            PYTHONNOUSERSITE="1",
        )
        env.pop("PYTHONPATH", None)
        return env


def git(repo: Path, *args: str, env: dict | None = None) -> bytes:
    if env is None:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=env, capture_output=True, check=True
    ).stdout


def install_skill(source: Path, trial: Trial) -> None:
    archive = git(source, "archive", "--format=tar", trial.ref, SKILL_PATH)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for member in bundle:
            if member.name == "skills":
                continue
            relative = Path(member.name).relative_to(SKILL_PATH)
            if ".." in relative.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsupported Spex archive member: {member.name}")
            target = trial.skill / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.extractfile(member).read())
                target.chmod(member.mode & 0o777)
    if not (trial.skill / "SKILL.md").is_file():
        raise ValueError(f"Spex skill missing at {trial.ref}")


def verify_spex_roots(trial: Trial) -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c",
         "import sys,json; sys.path.insert(0,sys.argv[1]); "
         "from config import get_project_context; "
         "ctx=get_project_context(); print(json.dumps([ctx.spex_root,ctx.spex_roots]))",
         str(trial.skill / "scripts")],
        cwd=trial.repo, env=trial.env, capture_output=True, text=True, check=True,
    )
    primary, roots = json.loads(result.stdout)
    expected = trial.repo / ".spex"
    if (
        expected.is_symlink()
        or Path(primary).resolve() != expected.resolve()
        or any(not Path(root).resolve().is_relative_to(trial.directory) for root in roots)
    ):
        raise ValueError(f"Spex roots escape the trial or differ from {expected}: {roots}")


def copy_fixture(case: Case, repo: Path) -> None:
    for path in case.fixture.rglob("*"):
        relative = path.relative_to(case.fixture)
        if (
            path.is_symlink()
            or not (path.is_dir() or path.is_file())
            or any(part.casefold() == ".git" for part in relative.parts)
            or relative.parts[0].casefold() in {".agents", ".spex.toml"}
        ):
            raise ValueError(f"Unsupported fixture path: {path}")
    shutil.copytree(case.fixture, repo)


def prepare_trial(source: Path, case: Case, ref: str = "HEAD", *, parent=None) -> Trial:
    """Create a trial whose lifetime is owned by the caller."""
    commit = git(source, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    directory = Path(tempfile.mkdtemp(prefix="spex-eval-", dir=parent)).resolve()
    trial = Trial(directory, commit.decode("ascii").strip())
    try:
        (directory / "home").mkdir()
        copy_fixture(case, trial.repo)
        (trial.repo / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\nuse_git_worktree = false\ndebug = true\n',
            encoding="utf-8",
        )
        initialize_repo(trial)
        install_skill(source, trial)
        verify_spex_roots(trial)
    except BaseException:
        shutil.rmtree(directory)
        raise
    return trial


def initialize_repo(trial: Trial) -> None:
    env = trial.env
    git(trial.repo, "init", "--template=", "--initial-branch=main", env=env)
    for key, value in (("user.name", "Spex Eval"), ("user.email", "eval@example.invalid")):
        git(trial.repo, "config", key, value, env=env)
    (trial.repo / ".git" / "info").mkdir(exist_ok=True)
    (trial.repo / ".git" / "info" / "exclude").write_text(
        "/.agents/\n/.spex/\n/.spex.toml\n", encoding="utf-8"
    )
    git(trial.repo, "add", "--all", env=env)
    timestamp = "2000-01-01T00:00:00+00:00"
    commit_env = dict(env, GIT_AUTHOR_DATE=timestamp, GIT_COMMITTER_DATE=timestamp)
    git(trial.repo, "commit", "--allow-empty", "-m", "Initialize eval fixture", env=commit_env)
