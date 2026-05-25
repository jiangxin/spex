#!/usr/bin/env python3
"""Create a topic directory under the spex root."""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from common import get_specs_dir, local_iso_timestamp

SUPPORTED_GET_KEYS = {
    "spex_root": "get_spex_root",
    "specs_dir": "get_specs_dir",
    "archives_dir": "get_archives_dir",
}

TOPIC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
DATE_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-")
MAX_TOPIC_BYTES = 64


def create_topic(topic, specs_dir, auto_prefix=True):
    """Create a topic directory under specs_dir.

    Returns (topic_name, topic_dir) tuple.
    Raises ValueError on invalid input, FileExistsError if topic exists.
    """
    specs_dir = Path(specs_dir)

    if not DATE_PREFIX_PATTERN.match(topic) and auto_prefix:
        prefix = datetime.now().strftime("%Y-%m-%d-%H-%M")
        topic = f"{prefix}-{topic}"

    if not TOPIC_PATTERN.match(topic):
        raise ValueError(
            f"invalid topic name '{topic}'. "
            "Must match YYYY-MM-DD-HH-MM-<name> with [a-z0-9-]."
        )

    if len(topic.encode("utf-8")) > MAX_TOPIC_BYTES:
        raise ValueError(f"topic name '{topic}' exceeds {MAX_TOPIC_BYTES} bytes.")

    topic_dir = specs_dir / topic
    if topic_dir.exists():
        raise FileExistsError(f"'{topic}' already exists, use a different name.")

    specs_dir.mkdir(parents=True, exist_ok=True)
    topic_dir.mkdir()
    return (topic, topic_dir)


def _get_git_info():
    """Retrieve git repository metadata via subprocess calls."""
    commands = {
        "workdir": ["git", "rev-parse", "--show-toplevel"],
        "remote_url": ["git", "remote", "get-url", "origin"],
        "branch": ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        "user_name": ["git", "config", "user.name"],
        "user_email": ["git", "config", "user.email"],
    }
    info = {}
    for key, cmd in commands.items():
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            info[key] = result.stdout.strip()
        else:
            info[key] = ""
    return info


def _write_meta(topic_dir, git_info, prompt, timestamp):
    """Write meta.json into topic_dir with git info and prompt."""
    meta = {
        "workdir": git_info.get("workdir", ""),
        "remote_url": git_info.get("remote_url", ""),
        "branch": git_info.get("branch", ""),
        "user_name": git_info.get("user_name", ""),
        "user_email": git_info.get("user_email", ""),
        "created_at": timestamp,
        "prompts": [prompt] if prompt else [],
    }
    meta_path = Path(topic_dir) / "meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(
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
    args = parser.parse_args()

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

    specs_dir = Path(get_specs_dir())
    prompt = "" if sys.stdin.isatty() else sys.stdin.read().strip()

    try:
        topic_name, topic_dir = create_topic(args.topic, specs_dir)
    except (ValueError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    git_info = _get_git_info()
    timestamp = local_iso_timestamp()
    _write_meta(topic_dir, git_info, prompt, timestamp)

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
