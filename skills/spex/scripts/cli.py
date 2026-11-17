#!/usr/bin/env python3
"""Centralized argument parser wrapper for spex CLI scripts."""

from __future__ import annotations

import argparse
import json


class ArgumentParser(argparse.ArgumentParser):
    """Thin wrapper around argparse.ArgumentParser.

    Usage::

        parser = ArgumentParser(prog="spex todo-helper")
        parser.add_argument("--todo-file")
        parser.add_argument("-a", "--append", action="store_true")
        args = parser.parse()  # defaults to sys.argv[1:]
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def parse(self, argv=None):
        """Parse arguments from a list, defaulting to sys.argv[1:]."""
        return self.parse_args(argv)

    def parse_known(self, argv=None):
        """Parse known arguments, returning (args, remaining)."""
        return self.parse_known_args(argv)


def nonempty_spec_name(name: str) -> str:
    """Reject an explicitly empty spec argument."""
    if not name:
        raise argparse.ArgumentTypeError("Spec name must not be empty")
    return name


def parse_run_hook_args(argv=None, usage=None):
    """Parse the hook invocation without dispatching or resolving a spec."""
    parser = ArgumentParser(prog="spex run-hook", usage=usage)
    parser.add_argument("hook_name", metavar="<hook-name>")
    parser.add_argument("name", nargs="?", type=nonempty_spec_name, metavar="<spec-name>")
    parser.add_argument("--event-type")
    parser.add_argument("--json-payload")
    parser.add_argument("--workdir")
    args = parser.parse(argv)
    if not args.event_type:
        parser.exit(1, "Error: --event-type is required\n")
    try:
        args.payload = json.loads(args.json_payload or "{}")
    except json.JSONDecodeError as exc:
        parser.error(f"Invalid --json-payload: {exc}")
    if args.name and not isinstance(args.payload, dict):
        parser.error("--json-payload must be a JSON object when a spec name is provided")
    return args
