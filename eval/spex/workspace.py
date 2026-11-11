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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]*")
SANDBOX_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}(?:-\d+)?$")
SKILL_PATH = "skills/spex"
TRIAL_TMP = ".spex-eval-tmp"
WORKSPACE_NAME = "workspace"


def saved_run_id(value: str) -> bool:
    return bool(SANDBOX_NAME.fullmatch(value) or re.fullmatch(r"[a-f0-9]{32}", value))


def saved_trial_paths(directory: Path) -> set[Path]:
    return {path for pattern in ("trial.json", "*/*/trial.json", "*/*/*/trial.json")
            for path in directory.glob(pattern)}


def sandbox_timestamp(now: datetime | None = None) -> str:
    """Return a filesystem-safe local timestamp for sandbox directory names."""
    stamp = now or datetime.now().astimezone()
    return stamp.strftime("%Y-%m-%d-%H-%M-%S")


SANDBOX_TOML = (
    "[spex]\n"
    'spex_root = ".spex"\n'
    "use_git_worktree = false\n"
    "debug = true\n"
)


def allocate_sandbox(runs_root: Path, *, now: datetime | None = None) -> Path:
    """Create `runs/YYYY-MM-DD-HH-MM-SS` (with -2, -3… on clash) and git-init it.

    Writes a sandbox-local ``.spex.toml`` and ``.spex/`` so Spex config and
    roots stay inside the sandbox instead of inheriting host-level trees.
    """
    root = Path(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    base = sandbox_timestamp(now)
    path = root / base
    suffix = 2
    while path.exists():
        path = root / f"{base}-{suffix}"
        suffix += 1
    path.mkdir(parents=True, exist_ok=False)
    try:
        git(path, "init", "--template=", "--initial-branch=main")
        (path / "_handoff").mkdir()
        (path / ".spex.toml").write_text(SANDBOX_TOML, encoding="utf-8")
        spex_root = path / ".spex"
        spex_root.mkdir()
        for subdir in ("specs", "archives", "hooks"):
            (spex_root / subdir).mkdir()
    except BaseException:
        shutil.rmtree(path)
        raise
    return path.resolve()


def case_dir(
    sandbox: Path, suite: str, case_id: str, repeat: int | None = None
) -> Path:
    """Return the evidence directory for one case under a sandbox."""
    if not IDENTIFIER.fullmatch(suite) or not IDENTIFIER.fullmatch(case_id):
        raise ValueError(f"Invalid suite or case id: {suite}/{case_id}")
    path = Path(sandbox) / suite / case_id
    if repeat is not None:
        if repeat < 1:
            raise ValueError("Repeat must be a positive integer")
        path = path / str(repeat)
    return path


def verify_sandbox(sandbox: Path, source: Path) -> None:
    """Ensure the sandbox git toplevel is itself and not the Spex source repo."""
    sandbox = Path(sandbox).resolve()
    source = Path(source).resolve()
    if not SANDBOX_NAME.fullmatch(sandbox.name):
        raise ValueError(f"Unexpected sandbox directory name: {sandbox.name}")
    if not (sandbox / ".git").is_dir() or (sandbox / ".git").is_symlink():
        raise ValueError(f"Sandbox is missing a real git directory: {sandbox}")
    sand_top = Path(
        os.fsdecode(git(sandbox, "rev-parse", "--show-toplevel").rstrip(b"\n"))
    ).resolve()
    source_top = Path(
        os.fsdecode(git(source, "rev-parse", "--show-toplevel").rstrip(b"\n"))
    ).resolve()
    if sand_top != sandbox:
        raise ValueError(f"Sandbox git toplevel differs from sandbox: {sand_top}")
    if sand_top == source_top:
        raise ValueError("Sandbox git toplevel must not be the Spex source repository")


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
    setup = definition.get("setup")
    if setup is not None and (not isinstance(setup, str) or not IDENTIFIER.fullmatch(setup)):
        raise ValueError(f"Invalid setup selector in {manifest}: {definition['id']}")
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
            TMPDIR=str(self.repo / TRIAL_TMP),
            TMPPREFIX=str(self.repo / TRIAL_TMP / "zsh"),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_ATTR_NOSYSTEM="1",
            SPEX_CONFIG_FILE=str(self.repo / ".spex.toml"),
            PYTHONNOUSERSITE="1",
        )
        env.pop("PYTHONPATH", None)
        # Keep the runner's interpreter first on PATH for Python shebangs in the trial.
        python_bin = Path(sys.executable).parent
        if python_bin.is_dir():
            current = env.get("PATH", os.defpath)
            env["PATH"] = str(python_bin) + os.pathsep + current
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


def verify_trial_workspace(trial: Trial) -> None:
    git_dir = trial.repo / ".git"
    if (
        trial.repo.resolve() != trial.repo
        or git_dir.is_symlink()
        or not git_dir.is_dir()
        or (git_dir / "commondir").exists()
        or (git_dir / "commondir").is_symlink()
    ):
        raise ValueError("Expected a standalone Git repository in the trial workspace")
    top = git(trial.repo, "rev-parse", "--show-toplevel", env=trial.env)
    if Path(os.fsdecode(top.rstrip(b"\n"))).resolve() != trial.repo:
        raise ValueError("Git worktree root differs from the trial workspace")

    verify_spex_roots(trial)


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


def probe_spex(trial: Trial) -> None:
    """Fail fast when the pinned Spex CLI cannot start in the trial env."""
    spex = trial.skill / "scripts" / "spex"
    if not spex.is_file() or spex.is_symlink():
        raise ValueError(f"Pinned Spex CLI missing: {spex}")
    help_run = subprocess.run(
        [sys.executable, "-I", str(spex), "--help"],
        cwd=trial.repo, env=trial.env, capture_output=True, text=True, timeout=30,
        check=False,
    )
    if help_run.returncode != 0:
        detail = (help_run.stderr or help_run.stdout or "").strip()
        raise ValueError(f"Spex --help probe failed: {detail}")
    import_run = subprocess.run(
        [sys.executable, "-I", "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); import template; import prompt",
         str(trial.skill / "scripts")],
        cwd=trial.repo, env=trial.env, capture_output=True, text=True, timeout=30,
        check=False,
    )
    if import_run.returncode != 0:
        detail = (import_run.stderr or import_run.stdout or "").strip()
        raise ValueError(f"Spex import probe failed: {detail}")


def copy_fixture(case: Case, repo: Path) -> None:
    for path in case.fixture.rglob("*"):
        relative = path.relative_to(case.fixture)
        if (
            path.is_symlink()
            or not (path.is_dir() or path.is_file())
            or any(part.casefold() == ".git" for part in relative.parts)
            or relative.parts[0].casefold() in {".agents", ".spex.toml", TRIAL_TMP}
        ):
            raise ValueError(f"Unsupported fixture path: {path}")
    shutil.copytree(case.fixture, repo)


def prepare_trial(source: Path, case: Case, ref: str = "HEAD", *, parent: Path) -> Trial:
    """Create a trial under ``parent/workspace``. Lifetime is owned by the caller."""
    if parent is None:
        raise TypeError("prepare_trial requires parent= under an eval sandbox case directory")
    commit = git(source, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    parent = Path(parent).resolve()
    directory = (parent / WORKSPACE_NAME).resolve()
    if directory.exists():
        raise ValueError(f"Trial workspace already exists: {directory}")
    if not directory.is_relative_to(parent):
        raise ValueError("Trial workspace escaped the case directory")
    directory.mkdir(parents=True, exist_ok=False)
    trial = Trial(directory, commit.decode("ascii").strip())
    try:
        (directory / "home").mkdir()
        copy_fixture(case, trial.repo)
        (trial.repo / TRIAL_TMP).mkdir()
        (trial.repo / ".spex.toml").write_text(
            '[spex]\nspex_root = ".spex"\nuse_git_worktree = false\ndebug = true\n',
            encoding="utf-8",
        )
        initialize_repo(trial)
        install_skill(source, trial)
        # HEAD pins install the committed skill; overlay worktree config.py so
        # uncommitted isolation fixes still apply during local eval.
        head = git(source, "rev-parse", "HEAD").decode("ascii").strip()
        if trial.ref == head:
            src_config = source / SKILL_PATH / "scripts" / "config.py"
            dst_config = trial.skill / "scripts" / "config.py"
            if src_config.is_file() and dst_config.is_file():
                dst_config.write_bytes(src_config.read_bytes())
        if "setup" in case.definition:
            script = case.fixture.parents[1] / "setup.py"
            if not script.is_file() or script.is_symlink():
                raise ValueError(f"Expected a real suite setup script: {script}")
            subprocess.run(
                [sys.executable, "-I", str(script), str(trial.repo), case.definition["setup"]],
                cwd=trial.repo, env=trial.env, capture_output=True, check=True, timeout=30,
            )
        verify_trial_workspace(trial)
        probe_spex(trial)
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
        f"/.agents/\n/.spex/\n/.spex.toml\n/{TRIAL_TMP}/\n", encoding="utf-8"
    )
    git(trial.repo, "add", "--all", env=env)
    timestamp = "2000-01-01T00:00:00+00:00"
    commit_env = dict(env, GIT_AUTHOR_DATE=timestamp, GIT_COMMITTER_DATE=timestamp)
    git(trial.repo, "commit", "--allow-empty", "-m", "Initialize eval fixture", env=commit_env)
