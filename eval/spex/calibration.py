"""Load gold evidence and measure agreement with its expected judgments."""

from __future__ import annotations

import json
from pathlib import Path

from evidence import digest, encode
from judge import PROMPT, PROMPT_VERSION, required_refs, rubric_for
from workspace import IDENTIFIER


def load_samples(path: Path, suites: Path) -> dict:
    raw = path.read_bytes()
    dataset = json.loads(raw)
    rubric_hashes = {}
    samples = []
    seen = set()
    for item in dataset["samples"]:
        identifier, suite, case = (item[key] for key in ("id", "suite", "case"))
        if identifier in seen or not all(
            IDENTIFIER.fullmatch(value) for value in (identifier, suite, case)
        ):
            raise ValueError("Invalid or duplicate calibration sample ID")
        seen.add(identifier)
        rubric = suites / suite / "rubrics.json"
        rubric_hashes[suite] = digest(rubric.read_bytes())
        _, criteria = rubric_for(rubric, case)
        gold, evidence = item["gold"], item["evidence"]
        if set(gold) != {criterion["id"] for criterion in criteria}:
            raise ValueError(f"Gold labels do not cover rubric for {identifier}")
        for criterion in criteria:
            label = gold[criterion["id"]]
            verdict = label["verdict"]
            refs = set(label["evidence_refs"])
            missing_required = verdict != "insufficient_evidence" and not (
                required_refs(criterion) <= refs
            )
            if (verdict not in ("pass", "fail", "insufficient_evidence")
                    or type(label.get("critical", False)) is not bool
                    or not refs <= evidence.keys()
                    or any(not ref.startswith(f"turn-{criterion['turn']}:") for ref in refs)
                    or missing_required):
                raise ValueError(f"Invalid gold label in {identifier}")
        samples.append({**item, "packet": {"criteria": criteria, "evidence": evidence}})
    if not samples or type(dataset["version"]) is not int:
        raise ValueError("Empty or invalid calibration dataset")
    return {
        "version": dataset["version"], "dataset_hash": digest(raw),
        "rubric_hashes": rubric_hashes, "samples": samples,
    }


def evaluate(calibration: dict, grades: list[dict], model: str, split: str) -> dict:
    if len(grades) != len(calibration["samples"]):
        raise ValueError("Expected one grade per calibration sample")
    agreement = {}
    results = []
    matched = total = critical_misses = invalid_references = errors = 0
    for sample, grade in zip(calibration["samples"], grades):
        rows = {row["criterion_id"]: row for row in grade["results"]}
        for identifier, label in sample["gold"].items():
            actual = rows.get(identifier, {}).get("verdict")
            expected = label["verdict"]
            correct = actual == expected
            matched += correct
            total += 1
            key = f"{sample['suite']}/{sample['case']}/{identifier}"
            tally = agreement.setdefault(key, {"matched": 0, "total": 0})
            tally["matched"] += correct
            tally["total"] += 1
            critical_misses += expected == "fail" and label.get("critical", False) and not correct
        invalid_references += grade.get("invalid_reference_attempts", 0)
        errors += bool(grade.get("error"))
        results.append({
            "sample": sample["id"], "expected": sample["gold"],
            "evidence_hash": digest(encode(sample["packet"]["evidence"])), **grade,
        })
    return {
        "model": model, "split": split, "version": calibration["version"],
        "dataset_hash": calibration["dataset_hash"], "rubric_hashes": calibration["rubric_hashes"],
        "prompt_version": PROMPT_VERSION, "prompt_hash": digest(PROMPT.encode()),
        "matched": matched, "total": total, "agreement": matched / total,
        "by_criterion": agreement, "critical_misses": critical_misses,
        "invalid_reference_attempts": invalid_references, "judge_errors": errors,
        "calibrated": (split == "frozen" and matched * 10 >= total * 9
                       and critical_misses == invalid_references == errors == 0),
        "samples": results,
    }
