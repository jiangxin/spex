"""Behavioral coverage for the standalone git-commit skill scripts."""

import hashlib
import importlib.util
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/git-commit/scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signature_filter = load_script("filter_agent_signature")


@pytest.fixture(autouse=True)
def isolate_git_config(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setattr(signature_filter, "is_merge_commit", lambda path: False)


def supports_config_hooks(version):
    match = re.match(r"git version (\d+)\.(\d+)\.(\d+)", version)
    return bool(match and tuple(map(int, match.groups())) >= (2, 54, 0))


def native_commit(script=SCRIPTS / "filter_agent_signature.py"):
    command = subprocess.check_output([sys.executable, str(script), "--command"], text=True).strip()
    return ["git", "-c", "hook.spex.event=commit-msg", "-c",
            "hook.spex.command=" + command,
            "commit"]


@pytest.fixture
def filter_only(monkeypatch):
    monkeypatch.setattr(signature_filter, "read_settings", lambda: {
        "gitcommit.removeAgentSignature": True,
        "gitcommit.addSignature": False,
        "gitcommit.addChangeId": False,
    })


@pytest.mark.parametrize("status, output, expected", [
    (1, b"", (b"#", b":")),
    (0, b"core.commentchar\n;\0", (b";", b":")),
    (0, b"core.commentchar\n;\0core.commentstring\n//\0trailer.separators\n:=\0",
     (b"//", b":=")),
    (0, b"core.commentstring\n#\0core.commentchar\n;\0", (b"#", b":")),
    (0, b"core.commentstring\n//\0core.commentstring\n; \0", (b"; ", b":")),
    (0, b"core.commentstring\nline1\nline2\0", (b"line1\nline2", b":")),
    (0, b"core.commentstring\n\0", (b"", b":")),
])
def test_batch_parser_config(monkeypatch, status, output, expected):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert "--null" in command and "--get-regexp" in command
        return SimpleNamespace(returncode=status, stdout=output, stderr=b"")

    monkeypatch.setattr(signature_filter.subprocess, "run", run)
    assert signature_filter.read_config() == expected
    assert len(calls) == 1


def test_batch_parser_config_failure(monkeypatch):
    monkeypatch.setattr(
        signature_filter.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=128, stdout=b"", stderr=b"bad config"),
    )
    with pytest.raises(OSError, match="bad config"):
        signature_filter.read_config()


@pytest.mark.parametrize("remove, sign, change", [
    (True, True, False), (False, True, False), (True, False, False),
    (True, True, True), (False, False, True),
])
@pytest.mark.parametrize("explicit", [None, True, False])
def test_boolean_defaults_are_independent(monkeypatch, remove, sign, change, explicit):
    defaults = dict(zip(signature_filter.CONFIG_DEFAULTS, (remove, sign, change)))
    monkeypatch.setattr(signature_filter, "CONFIG_DEFAULTS", defaults)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert "--null" in command and "--type=bool" in command
        output = b"" if explicit is None else b"".join(
            key.lower().encode() + b"\n" + str(explicit).lower().encode() + b"\0"
            for key in defaults
        )
        return SimpleNamespace(returncode=1 if explicit is None else 0, stdout=output, stderr=b"")

    monkeypatch.setattr(signature_filter.subprocess, "run", run)
    assert signature_filter.read_settings() == {
        key: default if explicit is None else explicit for key, default in defaults.items()
    }
    assert len(calls) == 1


def test_boolean_duplicate_keys_and_partial_configuration(monkeypatch):
    monkeypatch.setattr(signature_filter.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout=(
                            b"gitcommit.addsignature\nfalse\0gitcommit.addsignature\ntrue\0"
                            b"gitcommit.removeagentsignature\nfalse\0"
                        )))
    assert signature_filter.read_settings() == {
        "gitcommit.removeAgentSignature": False,
        "gitcommit.addSignature": True,
        "gitcommit.addChangeId": False,
    }


def test_boolean_error_stops_processing(tmp_path, monkeypatch, caplog):
    path = tmp_path / "message"
    path.write_bytes(b"Subject\n")
    monkeypatch.setattr(signature_filter.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=128, stdout=b"", stderr=b"invalid boolean"))
    assert signature_filter.main([str(path)]) == 1
    assert path.read_bytes() == b"Subject\n"
    assert "invalid boolean" in caplog.text


def test_two_configuration_calls_per_hook(tmp_path, monkeypatch):
    path = tmp_path / "message"
    path.write_bytes(b"Subject\n")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[1] == "config"
        output = b"".join(key.lower().encode() + b"\nfalse\0"
                          for key in signature_filter.CONFIG_DEFAULTS)
        return SimpleNamespace(returncode=0, stdout=output, stderr=b"")

    monkeypatch.setattr(signature_filter.subprocess, "run", run)
    assert signature_filter.main([str(path)]) == 0
    assert len(calls) == 2


def test_hook_command_quoting(monkeypatch, capsys):
    path = "/tmp/skill's directory/filter script.py"
    monkeypatch.setattr(signature_filter, "__file__", path)
    assert signature_filter.main(["--command"]) == 0
    assert shlex.split(capsys.readouterr().out) == [sys.executable, str(Path(path).resolve())]


def test_change_id_virtual_commit_hash(monkeypatch):
    payloads = []

    def run(command, **kwargs):
        if command[1] == "write-tree":
            output = b"a" * 40
        elif command[1] == "rev-parse":
            output = b"b" * 40
        elif command[1] == "var":
            output = b"Test <test@example.com> 1700000000 +0800"
        else:
            payload = kwargs["input"]
            payloads.append(payload)
            output = hashlib.sha1(
                b"commit " + str(len(payload)).encode() + b"\0" + payload
            ).hexdigest().encode()
        return SimpleNamespace(returncode=0, stdout=output, stderr=b"")

    monkeypatch.setattr(signature_filter.subprocess, "run", run)
    digest = signature_filter.generate_change_id(b"Subject")
    assert re.fullmatch(rb"I[0-9a-f]{40}", digest)
    assert payloads == [
        b"tree " + b"a" * 40 + b"\nparent " + b"b" * 40
        + b"\nauthor Test <test@example.com> 1700000000 +0800"
        + b"\ncommitter Test <test@example.com> 1700000000 +0800\n\nSubject"
    ]


@pytest.fixture
def change_id_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    for key, value in [("user.name", "Test"), ("user.email", "test@example.com"),
                       ("commit.gpgsign", "false")]:
        subprocess.run(["git", "config", key, value], check=True)
    return tmp_path


def test_merge_message_is_untouched(tmp_path, monkeypatch, caplog, capsys):
    module = load_script("filter_agent_signature")
    path = tmp_path / "MERGE_MSG"
    content = b"Merge topic\r\n\r\nCo-authored-by: Agent <noreply@example.com>\r\n"
    path.write_bytes(content)

    def unexpected(*args, **kwargs):
        pytest.fail("A merge message must bypass configuration and processing")

    monkeypatch.setattr(module.subprocess, "run", unexpected)
    monkeypatch.setattr(Path, "write_bytes", unexpected)
    assert module.main([str(path)]) == 0
    assert path.read_bytes() == content
    assert not caplog.records
    assert capsys.readouterr().out == ""


@pytest.mark.slow
def test_real_merge_bypasses_all_processing(change_id_repo):
    if not supports_config_hooks(subprocess.check_output(["git", "--version"], text=True)):
        pytest.skip("Config-defined hooks require Git 2.54+")

    def git(*args):
        return subprocess.check_output(["git", *args], text=True)

    git("commit", "--allow-empty", "-m", "base")
    main_branch = git("branch", "--show-current").strip()
    git("checkout", "-b", "topic")
    git("commit", "--allow-empty", "-m", "topic")
    git("checkout", main_branch)
    git("commit", "--allow-empty", "-m", "main")
    message = "Combine topic\n\nCo-authored-by: Agent <noreply@example.com>"
    command = native_commit()
    command[-1] = "merge"
    command[1:1] = ["-c", "gitcommit.addChangeId=true", "-c", "gitcommit.addSignature=invalid"]
    result = subprocess.run(
        [*command, "--no-ff", "topic", "-m", message], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert git("log", "-1", "--format=%B").rstrip() == message
    assert len(git("rev-list", "--parents", "-1", "HEAD").split()) == 3
    assert "Removed agent signature" not in result.stderr


@pytest.mark.slow
def test_normal_subject_named_merge_is_processed(change_id_repo):
    module = load_script("filter_agent_signature")
    path = change_id_repo / "COMMIT_EDITMSG"
    path.write_bytes(b"Merge documentation examples\n\nCo-authored-by: Agent <noreply@x>\n")
    assert module.main([str(path)]) == 0
    result = path.read_bytes()
    assert b"noreply@" not in result
    assert b"Signed-off-by: Test <test@example.com>" in result


@pytest.mark.slow
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
@pytest.mark.parametrize("body, count", [
    (b"Subject", 1),
    (b"Subject\n\nBody.\n", 1),
    (b"Subject\n\nSigned-off-by: Test <test@example.com>\n", 1),
    (b"Subject\n\nSIGNED-OFF-BY: Test\n <test@example.com>\n", 1),
    (b"Subject\n\nSigned-off-by: Other <other@example.com>\n", 2),
    (b"Subject\n\nSigned-off-by: Test <test@example.com>\n\nMore prose\n", 2),
    (b"Subject\n\n# ---------------- >8 ----------------\n\n"
     b"Signed-off-by: Test <test@example.com>\n", 2),
])
def test_signoff_deduplicates_only_trailers(change_id_repo, newline, body, count):
    content = body.replace(b"\n", newline)
    result = signature_filter.add_signature(content)
    assert result.lower().count(b"signed-off-by:") == count
    assert signature_filter.add_signature(result) == result
    if b">8" in content:
        marker = b"# ----------------"
        assert result[result.index(marker):] == content[content.index(marker):]


@pytest.mark.slow
def test_signoff_alias_and_separator(change_id_repo):
    subprocess.run(["git", "config", "trailer.sob.key", "Signed-off-by"], check=True)
    message = b"Subject\n\nSob= Test <test@example.com>\n"
    assert signature_filter.add_signature(message, separators=b"=") == message


@pytest.mark.slow
@pytest.mark.parametrize("flag", ["-s", "--no-signoff"])
def test_native_identity_overrides_and_no_signoff(change_id_repo, flag):
    if not supports_config_hooks(subprocess.check_output(["git", "--version"], text=True)):
        pytest.skip("Config-defined hooks require Git 2.54+")
    command = native_commit()
    command[1:1] = ["-c", "user.name=Override", "-c", "user.email=override@example.com"]
    result = subprocess.run(
        [*command, "--author=Author <author@example.com>", flag, "--allow-empty", "-F-"],
        input="feat: native options\n", text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    message = subprocess.check_output(["git", "log", "-1", "--format=%B"], text=True)
    assert message.count("Signed-off-by: Override <override@example.com>") == 1
    assert "Signed-off-by: Author" not in message
    assert subprocess.check_output(["git", "config", "user.name"], text=True).strip() == "Test"


@pytest.mark.slow
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
@pytest.mark.parametrize("body", [
    b"Subject", b"Subject\n\nBody.\n",
    b"Subject\n\nSigned-off-by: Human <human@example.com>\n",
    b"Subject\n\nCo-authored-by: Agent\n <noreply@example.com>\n",
])
def test_change_id_insertion(change_id_repo, newline, body):
    content = body.replace(b"\n", newline)
    suffix = newline * 2 + b"# ---------------- >8 ----------------" + newline + b"sample"
    result = signature_filter.add_change_id(content + suffix)
    assert result.endswith(suffix)
    assert re.search(rb"Change-Id: I[0-9a-f]{40}", result)
    if b"Signed-off-by:" in result:
        assert result.index(b"Change-Id:") < result.index(b"Signed-off-by:")
    assert signature_filter.add_change_id(result) == result


@pytest.mark.slow
@pytest.mark.parametrize("content", [
    b"", b"# comment\n", b"Signed-off-by: Human <human@example.com>\n",
    b"fixup! Subject\n\nBody\n", b"squash! Subject\n\nBody\n",
])
def test_change_id_skips_temporary_and_empty(content):
    assert signature_filter.add_change_id(content) == content


@pytest.mark.slow
def test_existing_change_id_moves_to_first_trailer():
    content = b"Subject\n\nSigned-off-by: Human <human@example.com>\nChange-Id: I1234"
    assert signature_filter.add_change_id(content) == (
        b"Subject\n\nChange-Id: I1234\nSigned-off-by: Human <human@example.com>\n"
    )


@pytest.mark.slow
@pytest.mark.parametrize("remove", ["true", "false"])
def test_change_id_real_commit(change_id_repo, remove):
    version = subprocess.check_output(["git", "--version"], text=True)
    if not supports_config_hooks(version):
        pytest.skip("Config-defined hooks require Git 2.54+")
    for key, value in [("gitcommit.addChangeId", "true"),
                       ("gitcommit.removeAgentSignature", remove)]:
        subprocess.run(["git", "config", key, value], check=True)
    message = "feat: change id\n\nCo-authored-by: Agent <noreply@example.com>\n"
    for _ in range(2):
        result = subprocess.run(
            [*native_commit(), "--allow-empty", "-F-"],
            input=message, text=True, capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        message = subprocess.check_output(["git", "log", "-1", "--format=%B"], text=True)
        assert re.search(r"\n\nChange-Id: I[0-9a-f]{40}\n", message)
        assert message.count("Change-Id:") == 1
        assert ("noreply@" not in message) == (remove == "true")
        assert "Signed-off-by: Test <test@example.com>" in message


@pytest.mark.slow
def test_change_id_failure_preserves_message(change_id_repo, monkeypatch, caplog):
    path = change_id_repo / "message"
    original = b"Subject\n\nCo-authored-by: Agent <noreply@example.com>\n"
    path.write_bytes(original)

    def fail(message):
        raise OSError("hash generation failed")

    monkeypatch.setattr(signature_filter, "generate_change_id", fail)
    subprocess.run(["git", "config", "gitcommit.addChangeId", "true"], check=True)
    assert signature_filter.main([str(path)]) == 1
    assert path.read_bytes() == original
    assert "hash generation failed" in caplog.text
    assert "Removed agent signature" not in caplog.text


@pytest.mark.slow
@pytest.mark.parametrize("trailer", [
    b"Co-authored-by: Claude <noreply@anthropic.com>",
    b"Signed-off-by: CURSOR <CURSORAGENT@CURSOR.COM>",
    b"Reviewed-by: Agent <NOREPLY@example.com>",
    b"Co-authored-by: Claude\n <noreply@anthropic.com>",
])
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_filter_preserves_other_content(trailer, newline):
    trailer = trailer.replace(b"\n", newline)
    prefix = newline.join([b"feat: example", b"", b"Body text.", b"", b""])
    human = b"Signed-off-by: Human <human@example.com>" + newline
    content = prefix + trailer + newline + human
    filtered, removed = signature_filter.filter_message(content)
    assert filtered == prefix + human
    assert removed == [trailer + newline]
    assert signature_filter.filter_message(filtered) == (filtered, [])


@pytest.mark.slow
@pytest.mark.parametrize("content", [
    b"Subject\n\nBody mentions Agent <noreply@example.com>.\n",
    b"Subject\n\nCo-authored-by: Agent <noreply@example.com>\n\nMore prose.\n",
    b"Subject\n\nCo-authored-by: Human <123+noreply@example.com>\n",
    b"Subject\n\nCo-authored-by: Other <cursoragent@cursor.com>\n",
    b"Subject\n\nNo trailers\n", b"", b"Co-authored-by: A <noreply@x>\n",
])
def test_unmatched_messages_unchanged(content):
    assert signature_filter.filter_message(content) == (content, [])


@pytest.mark.slow
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
@pytest.mark.parametrize("prefix", [b"#", b";", b"//"])
@pytest.mark.parametrize("attachment", ["comment", "scissors", "reverse", "diff", "patch"])
def test_preserve_message_attachments(newline, prefix, attachment):
    agent = b"Co-authored-by: Agent <noreply@example.com>" + newline
    subject = b"Subject" + newline * 2
    if attachment == "comment":
        suffix = newline + prefix + b" Please enter the commit message" + newline
    elif attachment in ("scissors", "reverse"):
        marker = b">8" if attachment == "scissors" else b"8<"
        suffix = newline + prefix + b" ---------------- " + marker + b" ----------------" + newline
        suffix += newline + agent
    elif attachment == "diff":
        suffix = newline + b"diff --git a/f b/f" + newline + b"+" + agent
    else:
        suffix = newline + b"---" + newline + b" f | 1 +" + newline
    filtered, removed = signature_filter.filter_message(subject + agent + suffix, prefix)
    assert filtered == subject + suffix
    assert removed == [agent]


@pytest.mark.slow
def test_comments_between_identity_continuations():
    message = (
        b"Subject\n\nCo-authored-by: Agent\n# keep this comment\n"
        b" <noreply@example.com>\nSigned-off-by: Human <human@example.com>\n"
    )
    filtered, removed = signature_filter.filter_message(message)
    assert filtered == (
        b"Subject\n\n# keep this comment\nSigned-off-by: Human <human@example.com>\n"
    )
    assert removed == [b"Co-authored-by: Agent\n <noreply@example.com>\n"]


@pytest.mark.slow
def test_mixed_trailers_follow_git_rules():
    agent = b"Co-authored-by: Agent <noreply@example.com>\n"
    tail = b"explanation\nSigned-off-by: Human <human@example.com>\n"
    filtered, removed = signature_filter.filter_message(b"Subject\n\n" + agent + tail)
    assert filtered == b"Subject\n\n" + tail
    assert removed == [agent]
    prose = b"Subject\n\nExample: Agent <noreply@example.com>\nSome prose\nMore prose\n"
    assert signature_filter.filter_message(prose) == (prose, [])


@pytest.mark.slow
@pytest.mark.parametrize("subject", [b"Subject", b"fixup! Subject", b"squash! Subject"])
def test_custom_separators(subject):
    agent = b"Co-authored-by= Agent <noreply@example.com>\n"
    human = b"Signed-off-by: Human <human@example.com>\n"
    filtered, removed = signature_filter.filter_message(
        subject + b"\n\n" + agent + human, separators=b":="
    )
    assert filtered == subject + b"\n\n" + human
    assert removed == [agent]


@pytest.mark.slow
def test_hook_reads_comment_and_separator_config(tmp_path, monkeypatch, filter_only):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    for key, value in [("core.commentChar", ";"), ("core.commentString", "//"),
                       ("trailer.separators", "="), ("trailer.bot.key", "Co-authored-by")]:
        subprocess.run(["git", "config", key, value], check=True)
    path = tmp_path / "message"
    agent = b"Bot= Agent <noreply@example.com>\n"
    tail = b"\n// ---------------- >8 ----------------\n\n" + agent
    path.write_bytes(b"Subject\n\n" + agent + tail)
    assert signature_filter.main([str(path)]) == 0
    assert path.read_bytes() == b"Subject\n\n" + tail


@pytest.mark.slow
def test_git_parser_failure_leaves_file_unchanged(tmp_path, monkeypatch, caplog):
    path = tmp_path / "message"
    original = b"Subject\n\nCo-authored-by: Agent <noreply@example.com>\n"
    path.write_bytes(original)

    def run(command, **kwargs):
        if "config" in command:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
        return SimpleNamespace(returncode=128, stdout=b"", stderr=b"parser failed")

    monkeypatch.setattr(signature_filter.subprocess, "run", run)
    assert signature_filter.main([str(path)]) == 1
    assert path.read_bytes() == original
    assert "parser failed" in caplog.text
    assert "Removed agent signature" not in caplog.text


def test_automatic_comment_prefix_fails_safely():
    with pytest.raises(OSError, match="core.commentChar=auto"):
        signature_filter.filter_message(b"Subject\n\nBody\n", comment_prefix=b"auto")


@pytest.mark.slow
def test_filter_output_and_noop(tmp_path, caplog, capsys, monkeypatch, filter_only):
    path = tmp_path / "message"
    trailers = ["Co-authored-by: A <noreply@x>", "Signed-off-by: Cursor <cursoragent@cursor.com>"]
    path.write_text("Subject\n\n" + "\n".join(trailers) + "\n")
    with caplog.at_level(logging.INFO):
        assert signature_filter.main([str(path)]) == 0
    assert path.read_text() == "Subject\n\n"
    assert [record.message for record in caplog.records] == [
        "Removed agent signature: " + trailer for trailer in trailers
    ]
    caplog.clear()

    def unexpected_write(*args):
        pytest.fail("No-op filtering must not write")

    monkeypatch.setattr(Path, "write_bytes", unexpected_write)
    assert signature_filter.main([str(path)]) == 0
    assert not caplog.records
    assert capsys.readouterr().out == ""


@pytest.mark.slow
def test_write_failure_no_success_message(tmp_path, monkeypatch, caplog, filter_only):
    path = tmp_path / "message"
    path.write_text("Subject\n\nCo-authored-by: A <noreply@x>\n")

    def fail(*args):
        raise OSError("write failed")

    monkeypatch.setattr(Path, "write_bytes", fail)
    with caplog.at_level(logging.INFO):
        assert signature_filter.main([str(path)]) == 1
    assert "Removed agent signature" not in caplog.text
    assert "write failed" in caplog.text
    assert signature_filter.main([str(tmp_path / "missing")]) == 1


@pytest.mark.slow
@pytest.mark.parametrize("setting", [None, "true", "yes", "1", "false", "no", "0", "", "invalid"])
@pytest.mark.parametrize("signature", [None, "true", "false", "invalid"])
def test_real_commit(tmp_path, setting, signature):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args, check=True):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, env=env,
            capture_output=True, text=True, check=check,
        )

    if not supports_config_hooks(git("--version").stdout):
        pytest.skip("Config-defined hooks require Git 2.54+")
    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    git("config", "commit.gpgsign", "false")
    if setting is not None:
        git("config", "--add", "gitcommit.removeAgentSignature", "false")
        git("config", "--add", "gitcommit.removeAgentSignature", setting)
    if signature is not None:
        git("config", "--add", "gitcommit.addSignature", "false")
        git("config", "--add", "gitcommit.addSignature", signature)
    hooks = tmp_path / "existing hooks"
    hooks.mkdir()
    hook = hooks / "commit-msg"
    hook.write_text('#!/bin/sh\nprintf "existing hook ran\\n" >&2\n')
    hook.chmod(0o755)
    git("config", "core.hooksPath", str(hooks))
    scripts = tmp_path / "skill's scripts"
    shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns("__pycache__"))
    message = "feat: test\n\nCo-authored-by: Agent <noreply@example.com>\n"
    result = subprocess.run(
        [*native_commit(scripts / "filter_agent_signature.py"), "--allow-empty", "-F-"],
        input=message, text=True, capture_output=True, cwd=tmp_path, env=env,
    )
    if setting == "invalid" or signature == "invalid":
        assert result.returncode != 0
        assert git("rev-parse", "--verify", "HEAD", check=False).returncode != 0
        return
    assert result.returncode == 0, result.stderr
    enabled = setting not in ("false", "no", "0", "")
    committed_message = git("log", "-1", "--format=%B").stdout
    assert "Change-Id:" not in committed_message
    assert ("noreply@" not in committed_message) == enabled
    assert ("Signed-off-by: Test <test@example.com>" in committed_message) == (
        signature != "false"
    )
    assert ("Removed agent signature:" in result.stderr) == enabled
    assert "existing hook ran" in result.stderr
    assert "Removed agent signature:" not in result.stdout
    assert git("config", "--get", "hook.spex.command", check=False).returncode == 1
    hook.write_text("#!/bin/sh\necho 'existing hook rejected commit' >&2\nexit 1\n")
    previous_head = git("rev-parse", "HEAD").stdout
    rejected = subprocess.run(
        [*native_commit(scripts / "filter_agent_signature.py"), "--allow-empty", "-F-"],
        input=message, text=True, capture_output=True, cwd=tmp_path, env=env,
    )
    assert rejected.returncode != 0
    assert "existing hook rejected commit" in rejected.stderr
    assert git("rev-parse", "HEAD").stdout == previous_head
