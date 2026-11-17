"""Tests for scoped Git configuration snapshots."""

import os
import subprocess

import git_config
import pytest


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
