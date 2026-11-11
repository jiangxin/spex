"""Shared configuration and ordered scheduling for evaluation batches."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor


def worker_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= 4:
        raise argparse.ArgumentTypeError("Choose between one and four workers")
    return count


def execution(jobs: int | None) -> dict:
    mode = "unknown" if jobs is None else "serial" if jobs == 1 else "parallel"
    return {"mode": mode, "jobs": jobs}


def execution_label(config: dict) -> str:
    jobs = config["jobs"]
    return "unknown" if jobs is None else f"{config['mode']} (max workers: {jobs})"


def ordered_map(function, items, jobs: int) -> list:
    if jobs == 1:
        return [function(item) for item in items]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(function, items))
