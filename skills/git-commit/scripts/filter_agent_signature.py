#!/usr/bin/env python3
"""Filter agent signatures and optionally add a Change-Id to commit trailers."""

import argparse
import logging
import os
import re
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path

logger = logging.getLogger("git-commit")
CONFIG_DEFAULTS = {
    "gitcommit.removeAgentSignature": True,
    "gitcommit.addSignature": True,
    "gitcommit.addChangeId": False,
}
IDENTITY = re.compile(rb"^\s*(.*?)\s*<([^<>\s]+)>\s*$", re.DOTALL)


def is_agent(value):
    identity = IDENTITY.fullmatch(value)
    if not identity:
        return False
    name, email = (part.strip().lower() for part in identity.groups())
    return (
        email.startswith(b"noreply@") and len(email) > len(b"noreply@")
    ) or (name == b"cursor" and email == b"cursoragent@cursor.com")


def read_config():
    """Read all parser settings once, preserving values and last-key precedence."""
    result = subprocess.run(
        ["git", "config", "--null", "--get-regexp",
         r"^(core\.(commentchar|commentstring)|trailer\.separators)$"],
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise OSError(result.stderr.decode("utf-8", errors="replace").strip())
    values = {}
    if result.returncode == 0:
        for record in result.stdout.split(b"\0"):
            if record:
                key, _, value = record.partition(b"\n")
                values[key.lower()] = value
    return (
        values.get(b"core.commentstring", values.get(b"core.commentchar", b"#")),
        values.get(b"trailer.separators", b":"),
    )


def read_settings():
    """Read independent boolean settings in one Git invocation."""
    result = subprocess.run(
        ["git", "config", "--null", "--type=bool", "--get-regexp",
         r"^gitcommit\.(removeagentsignature|addsignature|addchangeid)$"],
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise OSError(result.stderr.decode("utf-8", errors="replace").strip())
    values = {}
    if result.returncode == 0:
        for record in result.stdout.split(b"\0"):
            if record:
                key, _, value = record.partition(b"\n")
                values[key.decode().lower()] = value == b"true"
    return {key: values.get(key.lower(), default) for key, default in CONFIG_DEFAULTS.items()}


def is_merge_commit(message_file):
    """Detect merge state using Git metadata rather than the message subject."""
    if Path(message_file).name == "MERGE_MSG":
        return True
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "MERGE_HEAD"], capture_output=True,
    )
    return result.returncode == 0 and Path(os.fsdecode(result.stdout.rstrip(b"\n"))).is_file()


def message_context(content, comment_prefix):
    """Locate visible message lines without modifying comments or attachments."""
    if comment_prefix == b"auto":
        raise OSError(
            "Cannot determine core.commentChar=auto safely in a commit-msg hook; "
            "set core.commentChar or core.commentString to an explicit prefix"
        )
    lines = content.splitlines(keepends=True)
    visible = []
    for index, line in enumerate(lines):
        if comment_prefix and line.startswith(comment_prefix):
            marker = line[len(comment_prefix):].strip(b" \t\r\n-")
            if marker in (b">8", b"8<"):
                break
            continue
        if line.startswith(b"diff --git ") or line.rstrip(b"\r\n") == b"---":
            break
        visible.append(index)
    end = len(visible)
    while end and not lines[visible[end - 1]].strip():
        end -= 1
    start = end
    while start and lines[visible[start - 1]].strip():
        start -= 1
    return lines, visible, start, end


def parse_trailers(lines, visible, end, separators):
    """Ask Git to recognize the terminal trailer block."""
    if not separators:
        raise OSError("trailer.separators must not be empty")
    parsed = subprocess.run(
        ["git", "-c", "trailer.separators=" + separators.decode("utf-8", "surrogateescape"),
         "interpret-trailers", "--parse", "--no-divider"],
        input=b"".join(lines[i].rstrip(b"\r\n") + b"\n" for i in visible[:end]),
        capture_output=True,
    )
    if parsed.returncode:
        raise OSError(parsed.stderr.decode("utf-8", errors="replace").strip())
    trailer = re.compile(
        rb"^([A-Za-z0-9][A-Za-z0-9-]*)[ \t]*[" + re.escape(separators)
        + rb"][ \t]*(.*)$"
    )
    recognized = Counter()
    entries = []
    for line in parsed.stdout.splitlines():
        match = trailer.match(line)
        if match:
            # Git can canonicalize configured trailer aliases; values stay unchanged.
            recognized[match[2].strip()] += 1
            entries.append((match[1].lower(), match[2].strip()))
    return trailer, recognized, entries


def filter_message(content, comment_prefix=b"#", separators=b":"):
    """Use Git to recognize trailers, then remove only their original byte spans."""
    lines, visible, start, end = message_context(content, comment_prefix)
    # A subject without a separating blank line is not a trailer block.
    if start == 0:
        return content, []
    trailer, recognized, _ = parse_trailers(lines, visible, end, separators)
    entries = []
    current = None
    for index in visible[start:end]:
        line = lines[index]
        match = trailer.match(line.rstrip(b"\r\n"))
        if match:
            current = ([index], match[1].lower(), match[2].strip())
            entries.append(current)
        elif line.startswith((b" ", b"\t")) and current is not None:
            indices, key, value = current
            indices.append(index)
            current = (indices, key, value + b" " + line.strip())
            entries[-1] = current
        else:
            current = None
    deleted, removed = set(), []
    for indices, key, value in entries:
        if recognized[value]:
            recognized[value] -= 1
            if is_agent(value):
                deleted.update(indices)
                removed.append(b"".join(lines[i] for i in indices))
    return b"".join(line for i, line in enumerate(lines) if i not in deleted), removed


def git_output(*args, input=None):
    result = subprocess.run(["git", *args], input=input, capture_output=True)
    if result.returncode:
        raise OSError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout.strip()


def add_signature(content, comment_prefix=b"#", separators=b":"):
    """Append the committer's signoff unless that identity is already signed off."""
    lines, visible, start, end = message_context(content, comment_prefix)
    if not end:
        return content
    ident = git_output("var", "GIT_COMMITTER_IDENT").rsplit(b" ", 2)[0]
    if not IDENTITY.fullmatch(ident):
        raise OSError("Cannot parse GIT_COMMITTER_IDENT")
    _, recognized, entries = parse_trailers(lines, visible, end, separators)
    if any(key == b"signed-off-by" and value == ident for key, value in entries):
        return content
    newline = b"\r\n" if lines[visible[0]].endswith(b"\r\n") else b"\n"
    index = visible[end - 1] + 1
    if not lines[index - 1].endswith(b"\n"):
        lines[index - 1] += newline
    signoff = b"Signed-off-by" + separators[:1] + b" " + ident + newline
    lines.insert(index, signoff if start and recognized else newline + signoff)
    return b"".join(lines)


def generate_change_id(message):
    """Hash a virtual commit using the index, parent, identities, and message."""
    tree = git_output("write-tree")
    parent = subprocess.run(["git", "rev-parse", "--verify", "HEAD^0"], capture_output=True)
    headers = [b"tree " + tree]
    if parent.returncode == 0:
        headers.append(b"parent " + parent.stdout.strip())
    headers.extend([
        b"author " + git_output("var", "GIT_AUTHOR_IDENT"),
        b"committer " + git_output("var", "GIT_COMMITTER_IDENT"),
    ])
    digest = git_output(
        "hash-object", "-t", "commit", "--stdin",
        input=b"\n".join(headers) + b"\n\n" + message,
    )
    return b"I" + digest


def add_change_id(content, comment_prefix=b"#", separators=b":"):
    lines, visible, start, end = message_context(content, comment_prefix)
    if not end:
        return content
    subject = lines[visible[0]].strip()
    if subject.startswith((b"fixup!", b"squash!")):
        return content
    trailer, recognized, _ = parse_trailers(lines, visible, end, separators)
    candidates = []
    if start:
        for index in visible[start:end]:
            match = trailer.match(lines[index].rstrip(b"\r\n"))
            if match and recognized:
                candidates.append((index, match))
    existing = [
        (index, match) for index, match in candidates
        if match[1].lower() == b"change-id"
    ]
    # Preserve an existing ID, moving its line to the first trailer position.
    if existing:
        index, _ = existing[0]
        first = candidates[0][0]
        if index == first:
            return content
        line = lines.pop(index)
        if not line.endswith(b"\n"):
            line += b"\r\n" if lines[first].endswith(b"\r\n") else b"\n"
        lines.insert(first, line)
        return b"".join(lines)
    message = b"\n".join(lines[i].rstrip(b"\r\n") for i in visible[:end])
    # Do not turn an otherwise empty signoff-only message into a valid commit.
    if all(line.lower().startswith(b"signed-off-by:") or not line.strip()
           for line in message.splitlines()):
        return content
    newline = b"\r\n" if lines[visible[0]].endswith(b"\r\n") else b"\n"
    new_line = b"Change-Id" + separators[:1] + b" " + generate_change_id(message) + newline
    if candidates:
        lines.insert(candidates[0][0], new_line)
    else:
        index = visible[end - 1] + 1
        if not lines[index - 1].endswith(b"\n"):
            lines[index - 1] += newline
        lines.insert(index, newline + new_line)
    return b"".join(lines)


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", action="store_true", help="Print the quoted hook command")
    parser.add_argument("message_file", nargs="?")
    options = parser.parse_args(sys.argv[1:] if args is None else args)
    if options.command:
        print(shlex.join([sys.executable, str(Path(__file__).resolve())]))
        return 0
    if options.message_file is None:
        parser.error("a commit message file is required")
    try:
        path = Path(options.message_file)
        if is_merge_commit(path):
            return 0
        content = path.read_bytes()
        settings = read_settings()
        comment_prefix, separators = read_config()
        filtered, removed = content, []
        if settings["gitcommit.removeAgentSignature"]:
            filtered, removed = filter_message(content, comment_prefix, separators)
        if settings["gitcommit.addSignature"]:
            filtered = add_signature(filtered, comment_prefix, separators)
        if settings["gitcommit.addChangeId"]:
            filtered = add_change_id(filtered, comment_prefix, separators)
        if filtered != content:
            path.write_bytes(filtered)
    except OSError as exc:
        logger.error("Cannot process commit message: %s", exc)
        return 1
    for signature in removed:
        logger.info(
            "Removed agent signature: %s",
            signature.decode("utf-8", errors="replace").rstrip("\r\n"),
        )
    return 0


if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    sys.exit(main())
