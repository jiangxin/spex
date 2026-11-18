"""Tests for scoped Git configuration snapshots."""

import os
import subprocess
import sys
from pathlib import Path

import git_config
import pytest
from branch import create_and_switch_branch, set_branch_description, switch_branch
from config import clear_config_cache, get_project_context
from worktree import checkout_commit


@pytest.fixture(autouse=True)
def reset_snapshot():
    git_config.clear_cache()
    yield
    git_config.clear_cache()


def test_snapshot_value_distinctions_and_cache(tmp_path, monkeypatch):
    calls = []
    output = (
        b"system\0sample.Name\n base = \t\0"
        b"local\0sample.name\n\0"
        b"command\0sample.name\0"
        b"local\0sample.Mixed.Case.Value\nfirst\nsecond\0"
    )

    def run(args, **kwargs):
        calls.append(kwargs["cwd"])
        return subprocess.CompletedProcess(args, 0, output)

    monkeypatch.setattr(git_config.subprocess, "run", run)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    assert git_config.get_all("SAMPLE.NAME", alias) == [" base = \t", "", None]
    git_config.get_all("sample.name").clear()
    assert git_config.get("sample.name", ".", default="missing") is None
    assert git_config.get("SAMPLE.Mixed.Case.VALUE") == "first\nsecond"
    assert git_config.get("sample.mixed.Case.value", default="missing") == "missing"
    assert len(calls) == 1
    git_config.clear_cache()
    git_config.get_all("sample.name")
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["startup", "exit", "truncated", "missing"])
def test_failed_snapshot_is_redacted_and_retried(failure, tmp_path, monkeypatch, capsys):
    secret = b"synthetic-secret"
    failures = {
        "exit": (128, b"local\0sample.key\n" + secret + b"\0", secret),
        "truncated": (0, b"local\0sample.key\n" + secret, b""),
        "missing": (0, b"local\0\0", b""),
    }

    def fail(args, **kwargs):
        if failure == "startup":
            raise OSError(secret.decode())
        return subprocess.CompletedProcess(args, *failures[failure])

    monkeypatch.setattr(git_config.subprocess, "run", fail)
    with pytest.raises(git_config.GitConfigError) as error:
        git_config.get("sample.key", tmp_path)
    assert secret.decode() not in str(error.value) + capsys.readouterr().err
    monkeypatch.setattr(
        git_config.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, b"")
    )
    assert git_config.get_all("sample.key", tmp_path) == []


@pytest.fixture
def isolated_git(tmp_path, monkeypatch):
    for key in os.environ.copy():
        if key.startswith("GIT_") or key == "EMAIL":
            monkeypatch.delenv(key)
    home, xdg = tmp_path / "home", tmp_path / "xdg"
    home.mkdir()
    (xdg / "git").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "system"))

    def git(*args, cwd=tmp_path, check=True):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=check)

    return git


def assert_git_parity(git, cwd, key):
    all_values = git_config.get_all(key, cwd)

    def values(flag):
        result = git("config", "--includes", "--null", flag, key, cwd=cwd, check=False)
        assert result.returncode == (0 if all_values else 1)
        return list(map(os.fsdecode, result.stdout.split(b"\0")[:-1]))

    assert [value if value is not None else "" for value in all_values] == values("--get-all")
    single = git_config.get(key, cwd, default="missing")
    assert (["" if single is None else single] if all_values else []) == values("--get")
    if not all_values:
        assert single == "missing"


@pytest.mark.slow
def test_scopes_and_environment(tmp_path, monkeypatch, isolated_git):
    git = isolated_git
    git("init", "-q", "repo")
    repo = tmp_path / "repo"
    for path, value in (
        ("system", "system"), ("xdg/git/config", "xdg"), ("home/.gitconfig", "home"),
    ):
        (tmp_path / path).write_text(f"[sample]\n key = {value}\n", encoding="utf-8")
    git("config", "--add", "sample.key", "home", cwd=repo)
    git("config", "--add", "sample.key", "local", cwd=repo)
    git("config", "--bool", "extensions.worktreeConfig", "true", cwd=repo)
    git("config", "--worktree", "sample.key", "worktree", cwd=repo)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    for index, value in enumerate(("command", "")):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{index}", "sample.key")
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{index}", value)
    assert git_config.get_all("sample.key", repo) == [
        "system", "xdg", "home", "home", "local", "worktree", "command", "",
    ]
    assert_git_parity(git, repo, "sample.key")
    assert_git_parity(git, tmp_path, "sample.key")
    git("config", "--bool", "extensions.worktreeConfig", "false", cwd=repo)
    git_config.clear_cache()
    assert_git_parity(git, repo, "sample.key")
    assert "worktree" not in git_config.get_all("sample.key", repo)
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'sample.key'='parameters'")
    (tmp_path / "replacement").write_text("[sample]\n key = replacement\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "replacement"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    git_config.clear_cache()
    assert git_config.get_all("sample.key", tmp_path) == [
        "replacement", "command", "", "parameters",
    ]
    assert_git_parity(git, tmp_path, "sample.key")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    git_config.clear_cache()
    assert git_config.get_all("sample.key", tmp_path) == ["replacement", "parameters"]
    monkeypatch.setenv("GIT_CONFIG_COUNT", "3")
    git_config.clear_cache()
    with pytest.raises(git_config.GitConfigError):
        git_config.get("sample.key", tmp_path)


@pytest.mark.slow
def test_includes_and_worktree_states(tmp_path, isolated_git):
    git = isolated_git
    git("init", "-q", "-b", "main", "repo")
    git("init", "-q", "-b", "other", "other")
    repo, other, linked = (tmp_path / name for name in ("repo", "other", "linked"))
    rules = [
        ("gitdir:" + str(repo / ".git"), "directory"),
        ("gitdir/i:" + str(repo / ".git").upper(), "insensitive"),
        ("onbranch:topic", "branch"),
    ]
    git("config", "remote.origin.url", "https://example.invalid/repo", cwd=repo)
    home = tmp_path / "home"
    remote_condition = "hasconfig:remote.*.url:https://example.invalid/**"
    probe_file = home / "remote-probe"
    probe_file.write_text("[sample]\n probe = supported\n", encoding="utf-8")
    probe = git(
        "-c", f"includeIf.{remote_condition}.path={probe_file}",
        "config", "--includes", "--get", "sample.probe", cwd=repo, check=False,
    )
    assert probe.returncode in (0, 1)
    has_remote_include = probe.returncode == 0
    if has_remote_include:
        assert probe.stdout == b"supported\n"
        rules.append((remote_condition, "remote"))
    (home / "nested").write_text("[sample]\n key = nested\n flag\n", encoding="utf-8")
    (home / "ordinary").write_text("[include]\n path = nested\n", encoding="utf-8")
    config = '[include]\n path = ordinary\n'
    for condition, name in rules:
        (home / name).write_text(f"[sample]\n key = {name}\n", encoding="utf-8")
        config += f'[includeIf "{condition}"]\n path = {name}\n'
    config += '[sample "Mixed.Case"]\n Value = " ü=\\t\\n "\n'
    (home / ".gitconfig").write_text(config, encoding="utf-8")
    assert_git_parity(git, repo, "sample.key")
    (repo / "subdirectory").mkdir()
    assert_git_parity(git, repo / "subdirectory", "sample.key")
    assert_git_parity(git, other, "sample.key")
    assert git_config.get_all("sample.key", other) == ["nested"]
    expected_repo_values = ["nested", "directory", "insensitive"]
    if has_remote_include:
        expected_repo_values.append("remote")
    assert git_config.get_all("sample.key", repo) == expected_repo_values
    assert git_config.get_all("sample.flag", repo) == [None]
    assert_git_parity(git, repo, "sample.Mixed.Case.Value")
    assert_git_parity(git, repo, "sample.mixed.Case.Value")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Initial", "--allow-empty", cwd=repo)
    git("worktree", "add", "-qb", "topic", str(linked), cwd=repo)
    assert_git_parity(git, linked, "sample.key")
    assert "branch" in git_config.get_all("sample.key", linked)
    git("checkout", "-q", "--detach", cwd=linked)
    git_config.clear_cache()
    assert_git_parity(git, linked, "sample.key")
    assert "branch" not in git_config.get_all("sample.key", linked)


@pytest.mark.slow
def test_real_configuration_syntax_error_then_repair(tmp_path, isolated_git):
    config = tmp_path / "home" / ".gitconfig"
    config.write_text("[broken synthetic-secret\n", encoding="utf-8")
    with pytest.raises(git_config.GitConfigError, match="Git configuration query failed") as error:
        git_config.get("sample.key", tmp_path)
    assert "synthetic-secret" not in str(error.value)
    config.write_text("[sample]\n key = repaired\n", encoding="utf-8")
    assert git_config.get("sample.key", tmp_path) == "repaired"


_CONFIG_LIST = ["--null", "--show-scope", "--includes", "--list"]


def test_local_refresh_retries_and_replaces_with_empty_layer(tmp_path, monkeypatch):
    replies = iter([
        (0, b"global\0sample.key\nglobal\0local\0sample.key\nlocal\0"),
        (1, b"local\0sample.key\npartial\0"),
        (0, b""),
        (0, b"local\0sample.key\nnew\0"),
    ])
    calls = []

    def run(command, **kwargs):
        calls.append(command[2:])
        status, output = next(replies)
        return subprocess.CompletedProcess(command, status, output)

    monkeypatch.setattr(git_config.subprocess, "run", run)
    assert git_config.get("sample.key", tmp_path) == "local"
    git_config.invalidate_local(tmp_path)
    with pytest.raises(git_config.GitConfigError):
        git_config.get("sample.key", tmp_path)
    assert git_config.get_all("sample.key", tmp_path) == ["global"]
    git_config.invalidate_local(tmp_path)
    assert git_config.get_all("sample.key", tmp_path) == ["global", "new"]
    assert calls == [_CONFIG_LIST] + [["--local", *_CONFIG_LIST]] * 3


@pytest.mark.slow
def test_branch_description_refresh_preserves_other_layers(tmp_path, isolated_git, monkeypatch):
    git = isolated_git
    repo = tmp_path / "repo"
    git("init", "-q", "-b", "main", str(repo))
    git("config", "user.name", "Fixture", cwd=repo)
    git("config", "user.email", "fixture@example.invalid", cwd=repo)
    git("commit", "-qm", "Initial", "--allow-empty", cwd=repo)
    git("config", "extensions.worktreeConfig", "true", cwd=repo)
    linked = tmp_path / "linked"
    git("worktree", "add", "-qb", "topic", str(linked), cwd=repo)
    key = "branch.main.description"
    for location, scope in [(repo, "local"), (repo, "worktree"), (linked, "worktree")]:
        git("config", f"--{scope}", key, scope, cwd=location)
    (tmp_path / "system").write_text('[branch "main"]\n description = system\n')
    (tmp_path / "home" / ".gitconfig").write_text('[branch "main"]\n description = global\n')
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", key)
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "command")
    assert git_config.get_all(key, tmp_path) == ["system", "global", "command"]
    assert git_config.get_all(key, repo) == ["system", "global", "local", "worktree", "command"]
    assert_git_parity(git, linked, key)

    set_branch_description("main", "updated", cwd=repo)
    with monkeypatch.context() as patch:
        original = git_config.subprocess.run
        calls = []

        def run(command, **kwargs):
            calls.append(command[2:])
            return original(command, **kwargs)

        patch.setattr(git_config.subprocess, "run", run)
        assert git_config.get_all(key, tmp_path) == ["system", "global", "command"]
        for directory in (repo, linked):
            assert git_config.get_all(key, directory) == [
                "system", "global", "updated", "worktree", "command",
            ]
        with pytest.raises(subprocess.CalledProcessError):
            set_branch_description("main", "bad", cwd=tmp_path)
        assert git_config.get(key, repo) == "command"
        assert calls == [["--local", *_CONFIG_LIST]] * 2 + [["--local", key, "bad"]]
    assert_git_parity(git, linked, key)


@pytest.mark.slow
@pytest.mark.parametrize("change", ["existing", "introduced", "worktree", "remote"])
def test_local_refresh_falls_back_for_context_dependent_config(
    change, tmp_path, isolated_git, monkeypatch,
):
    git = isolated_git
    repo = tmp_path / "repo"
    git("init", "-q", "-b", "main", str(repo))
    key = "sample.key"
    included = tmp_path / "included"
    included.write_text("[sample]\n key = conditional\n")
    condition = "includeIf.onbranch:main.path"
    if change == "existing":
        git("config", "--global", condition, str(included), cwd=repo)
    if change == "remote":
        git(
            "config", "--system", "includeIf.hasconfig:remote.*.url:https://example.invalid/**.path",
            str(included), cwd=repo,
        )
        git("config", "--global", "remote.fixture.url", "https://example.invalid/project")
        if git("config", "--includes", "--get", key, cwd=repo, check=False).returncode:
            pytest.skip("Git does not support hasconfig:remote.*.url includes")
    git_config.get(key, repo)
    if change == "introduced":
        git("config", "--local", condition, str(included), cwd=repo)
    if change == "worktree":
        git("config", "extensions.worktreeConfig", "true", cwd=repo)
        git("config", "--worktree", key, "worktree", cwd=repo)
    set_branch_description("main", "updated", cwd=repo)
    with monkeypatch.context() as patch:
        original = git_config.subprocess.run
        calls = []

        def run(command, **kwargs):
            calls.append(command[2:])
            return original(command, **kwargs)

        patch.setattr(git_config.subprocess, "run", run)
        assert git_config.get(key, repo) == (
            "worktree" if change == "worktree" else "conditional"
        )
        expected = [] if change in {"existing", "remote"} else [["--local", *_CONFIG_LIST]]
        assert calls == [*expected, _CONFIG_LIST]
    assert_git_parity(git, repo, key)


@pytest.mark.slow
def test_empty_local_snapshot_refreshes_other_directories(tmp_path, isolated_git):
    git = isolated_git
    repo = tmp_path / "repo"
    git("init", "-q", "-b", "main", str(repo))
    subdirectory = repo / "subdir"
    subdirectory.mkdir()
    (repo / ".git" / "config").write_text("")
    key = "branch.main.description"
    assert git_config.get(key, subdirectory) is None
    set_branch_description("main", "updated", cwd=repo)
    assert git_config.get(key, subdirectory) == "updated"


@pytest.mark.slow
def test_project_identity_refreshes_after_git_changes(tmp_path, isolated_git):
    git = isolated_git
    git("init", "-q", "-b", "main", "project")
    repo = tmp_path / "project"
    git("config", "user.name", "  Fixture  ", cwd=repo)
    git("config", "user.email", "fixture@example.invalid", cwd=repo)
    git("commit", "-qm", "Initial", "--allow-empty", cwd=repo)
    git("config", "--unset", "user.email", cwd=repo)
    (tmp_path / "home" / "alternate").write_text(
        "[user]\n name = Alternate\n", encoding="utf-8",
    )
    (tmp_path / "home" / ".gitconfig").write_text(
        '[includeIf "onbranch:topic"]\n path = alternate\n', encoding="utf-8",
    )
    git("config", "--unset", "user.name", cwd=repo)
    git("remote", "add", "backup", "example:repo", cwd=repo)
    git("config", "url.https://example.invalid/.insteadOf", "example:", cwd=repo)
    ctx = get_project_context(repo)
    assert (ctx.user_name, ctx.user_email, ctx.remote_url) == (
        "", "", "https://example.invalid/repo",
    )
    git("config", "user.name", "  Fixture  ", cwd=repo)
    assert get_project_context(repo) is ctx
    clear_config_cache()
    assert get_project_context(repo).user_name == "Fixture"
    git("config", "--unset", "user.name", cwd=repo)
    create_and_switch_branch("topic", cwd=repo)
    assert get_project_context(repo).user_name == "Alternate"
    assert git_config.get("branch.topic.description", repo) is None
    set_branch_description("topic", "Test description", cwd=repo)
    assert git_config.get("branch.topic.description", repo) == "Test description"
    commit = git("rev-parse", "HEAD", cwd=repo).stdout.decode().strip()
    checkout_commit(repo, commit)
    assert get_project_context(repo).user_name == ""
    switch_branch("topic", cwd=repo)
    assert get_project_context(repo).user_name == "Alternate"


@pytest.mark.slow
def test_cli_uses_topology_for_list_and_reads_one_snapshot_for_identity(tmp_path, isolated_git):
    git = isolated_git
    git("init", "-q", "project")
    repo = tmp_path / "project"
    (repo / ".spex.toml").write_text('[spex]\n spex_root = ".spex"\n', encoding="utf-8")
    scripts = Path(git_config.__file__).resolve().parent
    instrument = """
import runpy
import subprocess
import sys

script, scripts, kind, *args = sys.argv[1:]
sys.path.insert(0, scripts)
run = subprocess.run
queries = []

def traced(command, *args, **kwargs):
    if command[0] == "git":
        queries.append(command[1:])
    return run(command, *args, **kwargs)

subprocess.run = traced
sys.argv = [script, *args]
try:
    runpy.run_path(script, run_name="__main__")
finally:
    if args[0] == "list":
        expected = [["rev-parse", "--show-toplevel"]]
        if kind == "linked":
            expected.extend([
                ["rev-parse", "--show-superproject-working-tree"],
                ["worktree", "list", "--porcelain"],
            ])
        assert queries == expected, queries
    else:
        assert [q for q in queries if q[0] == "config"] == [
            ["config", "--null", "--show-scope", "--includes", "--list"],
        ], queries
"""

    def spex(*args, cwd=repo, kind="regular"):
        return subprocess.run(
            [
                sys.executable, "-c", instrument,
                str(scripts / "spex"), str(scripts), kind, *args,
            ],
            cwd=cwd, capture_output=True, text=True,
        )

    listed = spex("list", "--json")
    assert (listed.returncode, listed.stdout.strip()) == (0, "[]"), listed.stderr
    git("config", "user.name", "First", cwd=repo)
    first = spex("config", "user_name")
    assert first.returncode == 0 and "First" in first.stdout, first.stderr
    git("config", "user.name", "Second", cwd=repo)
    second = spex("config", "user_name")
    assert second.returncode == 0 and "Second" in second.stdout, second.stderr

    git("config", "user.email", "fixture@example.invalid", cwd=repo)
    git("commit", "-qm", "Initial", "--allow-empty", cwd=repo)
    linked = tmp_path / "linked"
    git("worktree", "add", "-qb", "linked", str(linked), cwd=repo)
    (repo / ".spex.toml").write_text(
        '[spex]\n spex_root = ".spex"\n debug = true\n', encoding="utf-8",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".spex.toml").write_text('[spex]\n spex_root = ".spex"\n', encoding="utf-8")
    for directory, kind in ((repo, "regular"), (linked, "linked"), (outside, "outside")):
        listed = spex("list", "--json", cwd=directory, kind=kind)
        assert (listed.returncode, listed.stdout.strip()) == (0, "[]"), listed.stderr
