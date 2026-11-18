"""Validate evidence for successful general-task outcomes."""

_TEXT_FIELDS = {
    "command": ("criterion", "command"),
    "inspection": ("criterion", "location", "observation"),
}


def validate_acceptance_evidence(evidence):
    """Require a non-empty array of successful command or inspection records."""
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("acceptance_evidence must be a non-empty array")
    for index, entry in enumerate(evidence):
        label = f"acceptance_evidence[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be an object")
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in _TEXT_FIELDS:
            raise ValueError(f"{label}.kind must be command or inspection")
        for field in _TEXT_FIELDS[kind]:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label}.{field} must be a non-empty string")
        if kind == "command":
            code = entry.get("exit_code")
            if type(code) is not int or code != 0:
                raise ValueError(f"{label}.exit_code must be integer zero")
    return evidence
