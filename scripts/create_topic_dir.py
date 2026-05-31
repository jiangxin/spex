#!/usr/bin/env python3
"""Create a topic directory under the spex root.

DEPRECATED: This module is a thin wrapper around create_helper.
Use create_helper.create_topic and create_helper._write_meta instead.
"""

from __future__ import annotations

import json
import sys

import common
import config as cfg
from cli import ArgumentParser
from common import get_git_info, get_specs_dir, local_iso_timestamp
from create_helper import _write_meta, create_topic

SUPPORTED_GET_KEYS = {
    "spex_root": "get_spex_root",
    "specs_dir": "get_specs_dir",
    "archives_dir": "get_archives_dir",
}


def main(argv=None):
    parser = ArgumentParser(
        prog="spex create-topic",
        description="Create a topic directory. Reads requirement from stdin "
        "and saves it to meta.json prompts field."
    )
    parser.add_argument("topic", help="Topic name")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON format (topic_name and topic_path)"
    )
    parser.add_argument(
        "--get",
        help="Comma-separated keys to include in JSON output "
        f"(supported: {', '.join(sorted(SUPPORTED_GET_KEYS))})"
    )
    parser.add_argument(
        "--get-prompt",
        help="Comma-separated template names to render and include in JSON output"
    )
    parser.add_argument(
        "--description",
        default="",
        help="Brief description of the topic (saved to meta.json)"
    )
    args = parser.parse(argv)

    if args.get and not args.json:
        print("Error: --get requires --json", file=sys.stderr)
        sys.exit(1)
    if args.get_prompt and not args.json:
        print("Error: --get-prompt requires --json", file=sys.stderr)
        sys.exit(1)

    get_keys = []
    if args.get:
        get_keys = [k.strip() for k in args.get.split(",")]
        invalid = [k for k in get_keys if k not in SUPPORTED_GET_KEYS]
        if invalid:
            print(
                f"Error: unsupported --get key(s): {', '.join(invalid)}. "
                f"Supported: {', '.join(sorted(SUPPORTED_GET_KEYS))}",
                file=sys.stderr,
            )
            sys.exit(1)

    prompt_keys = []
    if args.get_prompt:
        prompt_keys = [k.strip() for k in args.get_prompt.split(",")]

    specs_dir = get_specs_dir()
    prompt = "" if sys.stdin.isatty() else sys.stdin.read().strip()

    try:
        topic_name, topic_dir = create_topic(args.topic, specs_dir)
    except (ValueError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    git_info = get_git_info()
    ctx = cfg.get_context()
    timestamp = local_iso_timestamp()
    _write_meta(topic_dir, git_info, ctx, prompt, timestamp, args.description)

    if args.json:
        result = {
            "topic_name": topic_name,
            "topic_path": str(topic_dir),
        }
        for key in get_keys:
            result[key] = getattr(common, SUPPORTED_GET_KEYS[key])()
        if prompt_keys:
            import prompt as prompt_mod
            for key in prompt_keys:
                json_key = key.replace("-", "_")
                result[json_key] = prompt_mod.render_prompt(key, topic_name)
        print(json.dumps(result, indent=2))
    else:
        print(str(topic_dir))


if __name__ == "__main__":
    main()
