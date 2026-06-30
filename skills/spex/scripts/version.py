#!/usr/bin/env python3
"""Version management utility for spex.

Reads, checks, and bumps the version stored in pyproject.toml and SKILL.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from common import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"
_SKILL_MD = _PROJECT_ROOT / "SKILL.md"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")


def get_pyproject_version() -> str | None:
    if not _PYPROJECT.is_file():
        return None
    for line in _PYPROJECT.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if m:
            return m.group(1)
    return None


def get_skill_version() -> str | None:
    if not _SKILL_MD.is_file():
        return None
    for line in _SKILL_MD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^version:\s*(.+)", line)
        if m:
            return m.group(1).strip().strip("\"'")
    return None


def check_versions() -> bool:
    pyproject_ver = get_pyproject_version()
    skill_ver = get_skill_version()

    if pyproject_ver is None:
        logger.error("Error: cannot read version from pyproject.toml")
        return False
    if skill_ver is None:
        logger.error("Error: cannot read version from SKILL.md")
        return False
    if pyproject_ver != skill_ver:
        logger.error(
            "Error: version mismatch\n"
            "  pyproject.toml: %s\n"
            "  SKILL.md:       %s",
            pyproject_ver, skill_ver,
        )
        return False
    return True


def bump_version(new_version: str) -> bool:
    if not _SEMVER_RE.match(new_version):
        logger.error("Error: invalid semver format: %s", new_version)
        return False

    # Update pyproject.toml
    content = _PYPROJECT.read_text(encoding="utf-8")
    new_content = re.sub(
        r'^(version\s*=\s*")[^"]+"',
        rf'\g<1>{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if new_content == content:
        logger.error("Error: could not find version in pyproject.toml")
        return False
    _PYPROJECT.write_text(new_content, encoding="utf-8")

    # Update SKILL.md
    content = _SKILL_MD.read_text(encoding="utf-8")
    new_content = re.sub(
        r"^(version:\s*).+",
        rf"\g<1>{new_version}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if new_content == content:
        logger.error("Error: could not find version in SKILL.md")
        return False
    _SKILL_MD.write_text(new_content, encoding="utf-8")

    print(f"{new_version}")
    return True


def main(argv=None):
    from cli import ArgumentParser

    usage = """\
Usage: spex version [--check | --bump <version>]

Show, check, or bump the project version.

Options:
  --check         Exit 1 if pyproject.toml and SKILL.md versions differ
  --bump <ver>    Update version in both files (semver format)
  -h, --help      Show this help message and exit
"""
    parser = ArgumentParser(prog="spex version", usage=usage)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--bump", metavar="VERSION")
    args = parser.parse(argv)

    if args.check:
        if not check_versions():
            sys.exit(1)
        ver = get_pyproject_version()
        logger.info("OK: %s", ver)
    elif args.bump:
        if not bump_version(args.bump):
            sys.exit(1)
    else:
        ver = get_pyproject_version()
        if ver is None:
            logger.error("Error: cannot read version")
            sys.exit(1)
        print(ver)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
