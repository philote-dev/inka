# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Preference dataset emitter for foundry runs (WS8).

Chosen = panel accept. Rejected = panel reject with failing gates recorded.
Escalations are not preference pairs (human still owns them). Schema stays
stable so Tier 3 SFT/DPO can consume it later without rewriting the loop.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .foundry_loop import SlotResult

preference_schema_version = 1
BLUEPRINT_CATEGORIES = frozenset(
    {
        "mechanics",
        "electromagnetism",
        "quantum",
        "thermodynamics",
        "atomic",
        "optics_waves",
        "special_relativity",
        "lab",
        "specialized",
    }
)
TIER3_MIN_PAIRS = 1000
TIER3_MIN_CATEGORIES = 6

_PRIVATE_MARKER = re.compile(
    r"(?i)(?<![a-z0-9])(?:"
    r"(?:gold|heldout|ets|gr9677|gr1777)(?=$|[-_/:\\])"
    r"|tier[\s_-]*3(?=$|[\s_/:\\-])"
    r")"
)
_CORRECT_CHOICES = frozenset("ABCDE")


def _failing_gates(item: dict) -> list[str]:
    if item.get("refused") is True:
        return ["refusal"]
    panel = item.get("panel") or {}
    checks = panel.get("checks") or []
    return [
        c.get("name", "")
        for c in checks
        if isinstance(c, dict)
        and not c.get("passed", True)
        and c.get("severity") == "hard"
        and _non_empty_string(c.get("name"))
    ]


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _child_path(path: str, key: object) -> str:
    return f"{path}.{key}" if isinstance(key, str) else f"{path}[{key!r}]"


def _recursive_data_errors(value: object, path: str = "$") -> list[str]:
    errors: list[str] = []
    if value is None or type(value) in (bool, int):
        return errors
    if type(value) is float:
        if not math.isfinite(value):
            errors.append(f"{path}: non-finite numbers are not allowed")
    elif type(value) is str:
        if marker := _PRIVATE_MARKER.search(value):
            errors.append(f"{path}: private marker {marker.group(0)!r}")
    elif isinstance(value, dict):
        for key, nested in value.items():
            child = _child_path(path, key)
            if not isinstance(key, str):
                errors.append(f"{child} (key): JSON dict keys must be strings")
            elif marker := _PRIVATE_MARKER.search(key):
                errors.append(f"{child} (key): private marker {marker.group(0)!r}")
            errors.extend(_recursive_data_errors(nested, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            errors.extend(_recursive_data_errors(nested, f"{path}[{index}]"))
    else:
        errors.append(
            f"{path}: value of type {type(value).__name__} is not JSON-compatible"
        )
    return errors


def private_marker_errors(value: object, path: str = "$") -> list[str]:
    """Return recursive private-marker errors with nested JSON-style paths."""
    return [
        error
        for error in _recursive_data_errors(value, path)
        if "private marker" in error
    ]


def _validate_panel_check(path: str, check: object) -> list[str]:
    if not isinstance(check, dict):
        return [f"{path} must be an object"]
    errors: list[str] = []
    if not _non_empty_string(check.get("name")):
        errors.append(f"{path}.name must be a non-empty string")
    if type(check.get("passed")) is not bool:
        errors.append(f"{path}.passed must be a boolean")
    if not _non_empty_string(check.get("severity")):
        errors.append(f"{path}.severity must be a non-empty string")
    if (
        check.get("severity") == "hard"
        and check.get("passed") is False
        and not _non_empty_string(check.get("evidence"))
    ):
        errors.append(f"{path}.evidence must be non-empty for a failed hard check")
    return errors


def _validate_panel(side: str, panel: object, decision: str) -> list[str]:
    if not isinstance(panel, dict):
        return [f"{side}.panel must be an object"]
    errors: list[str] = []
    if panel.get("decision") != decision:
        errors.append(f"{side}.panel.decision must be {decision!r}")
    checks = panel.get("checks")
    if not isinstance(checks, list):
        errors.append(f"{side}.panel.checks must be an array")
        return errors
    if side == "chosen" and not any(
        isinstance(check, dict) and _non_empty_string(check.get("evidence"))
        for check in checks
    ):
        errors.append("chosen.panel must include non-empty check evidence")
    for index, check in enumerate(checks):
        errors.extend(_validate_panel_check(f"{side}.panel.checks[{index}]", check))
    return errors


def _validate_item(side: str, node: object, decision: str) -> list[str]:
    if not isinstance(node, dict):
        return [f"{side} must be an object"]

    errors: list[str] = []
    for field in ("id", "stem", "source_ref"):
        if not _non_empty_string(node.get(field)):
            errors.append(f"{side}.{field} must be a non-empty string")

    choices = node.get("choices")
    if (
        not isinstance(choices, list)
        or len(choices) != 5
        or any(not _non_empty_string(choice) for choice in choices)
    ):
        errors.append(f"{side}.choices must contain exactly five non-empty strings")

    correct = node.get("correct")
    if not isinstance(correct, str) or correct not in _CORRECT_CHOICES:
        errors.append(f"{side}.correct must be exactly one of A, B, C, D, or E")

    errors.extend(_validate_panel(side, node.get("panel"), decision))
    return errors


def _validate_failing_gates(rejected: object) -> list[str]:
    if not isinstance(rejected, dict):
        return []
    if "failing_gates" not in rejected:
        return ["rejected.failing_gates missing"]

    gates = rejected["failing_gates"]
    if (
        not isinstance(gates, list)
        or not gates
        or any(not isinstance(gate, str) or not gate.strip() for gate in gates)
    ):
        return ["rejected.failing_gates must be a non-empty list of non-empty strings"]
    errors: list[str] = []
    reason = rejected.get("reason")
    if not _non_empty_string(reason):
        errors.append("rejected.reason must be a non-empty string")
    refused = rejected.get("refused")
    if type(refused) is not bool:
        errors.append("rejected.refused must be a boolean")
        return errors
    if refused:
        if gates != ["refusal"]:
            errors.append("rejected refusal must use failing_gates ['refusal']")
        return errors

    panel = rejected.get("panel")
    checks = panel.get("checks") if isinstance(panel, dict) else None
    failed_hard = [
        check.get("name")
        for check in checks or []
        if isinstance(check, dict)
        and check.get("severity") == "hard"
        and check.get("passed") is False
        and _non_empty_string(check.get("name"))
    ]
    if not failed_hard:
        errors.append("rejected panel must contain at least one failed hard check")
    if sorted(gates) != sorted(failed_hard):
        errors.append("rejected.failing_gates must match failed hard check names")
    return errors


def validate_pair(pair: object) -> list[str]:
    """Validate one schema-v1 preference pair without mutating it."""
    if not isinstance(pair, dict):
        return ["pair must be an object"]

    errors: list[str] = []
    if (
        type(pair.get("schema")) is not int
        or pair.get("schema") != preference_schema_version
    ):
        errors.append(f"schema must be {preference_schema_version}")
    if not _non_empty_string(pair.get("run_id")):
        errors.append("run_id must be a non-empty string")
    if type(pair.get("synthetic")) is not bool:
        errors.append("synthetic must be a boolean")

    slot = pair.get("slot")
    if not isinstance(slot, dict):
        errors.append("slot must be an object")
    else:
        for field in ("topic", "blueprint_category"):
            if not _non_empty_string(slot.get(field)):
                errors.append(f"slot.{field} must be a non-empty string")
        category = slot.get("blueprint_category")
        if isinstance(category, str) and category not in BLUEPRINT_CATEGORIES:
            errors.append(
                "slot.blueprint_category must be one of the nine locked slugs"
            )

    chosen = pair.get("chosen")
    rejected = pair.get("rejected")
    errors.extend(_validate_item("chosen", chosen, "accept"))
    errors.extend(_validate_item("rejected", rejected, "reject"))
    errors.extend(_validate_failing_gates(rejected))
    if (
        isinstance(chosen, dict)
        and isinstance(rejected, dict)
        and _non_empty_string(chosen.get("id"))
        and chosen.get("id") == rejected.get("id")
    ):
        errors.append("chosen.id and rejected.id must be distinct")

    errors.extend(_recursive_data_errors(pair))
    return errors


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value} is not allowed")


def scan_jsonl(path: str) -> list[str]:
    errs: list[str] = []
    try:
        with open(path, encoding="utf-8") as file:
            for lineno, line in enumerate(file, start=1):
                try:
                    record = json.loads(line, parse_constant=_reject_json_constant)
                except (json.JSONDecodeError, ValueError) as error:
                    message = (
                        error.msg
                        if isinstance(error, json.JSONDecodeError)
                        else str(error)
                    )
                    errs.append(f"line {lineno}: malformed JSON: {message}")
                    continue
                if not isinstance(record, dict):
                    errs.append(f"line {lineno}: record must be a JSON object")
                    continue
                errs.extend(
                    f"line {lineno}: {error}" for error in validate_pair(record)
                )
    except OSError as error:
        errs.append(f"could not read {path}: {error}")
    return errs


def pairs_from_slot(
    slot: dict,
    result: SlotResult,
    *,
    run_id: str,
    max_pairs: int = 64,
    synthetic: bool = False,
) -> list[dict]:
    if max_pairs <= 0:
        return []

    pairs: list[dict] = []
    for chosen in result.accepted:
        for rejected in result.rejected:
            pair = {
                "schema": preference_schema_version,
                "synthetic": synthetic,
                "slot": {
                    "topic": slot.get("topic"),
                    **{k: slot[k] for k in slot if k != "topic"},
                },
                "chosen": {
                    "id": chosen.get("id", ""),
                    "stem": chosen.get("stem", ""),
                    "choices": list(chosen.get("choices") or []),
                    "correct": chosen.get("correct") or chosen.get("key") or "",
                    "source_ref": chosen.get("source_ref", ""),
                    "panel": copy.deepcopy(chosen.get("panel")),
                },
                "rejected": {
                    "id": rejected.get("id", ""),
                    "stem": rejected.get("stem", ""),
                    "choices": list(rejected.get("choices") or []),
                    "correct": rejected.get("correct") or rejected.get("key") or "",
                    "source_ref": rejected.get("source_ref", ""),
                    "panel": copy.deepcopy(rejected.get("panel")),
                    "failing_gates": _failing_gates(rejected),
                    "reason": rejected.get("reason", ""),
                    "refused": rejected.get("refused") is True,
                },
                "run_id": run_id,
            }
            if errors := validate_pair(pair):
                chosen_id = chosen.get("id", "<missing>")
                rejected_id = rejected.get("id", "<missing>")
                raise ValueError(
                    "invalid preference pair "
                    f"{chosen_id!r}/{rejected_id!r}: {'; '.join(errors)}"
                )
            pairs.append(pair)
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def _validate_pairs(pairs: list[dict]) -> None:
    combinations: set[tuple[str, str]] = set()
    for index, pair in enumerate(pairs):
        if errors := validate_pair(pair):
            raise ValueError(
                f"invalid preference pair at index {index}: {'; '.join(errors)}"
            )
        chosen_id = pair["chosen"]["id"]
        rejected_id = pair["rejected"]["id"]
        combination = (chosen_id, rejected_id)
        if combination in combinations:
            raise ValueError(
                "duplicate chosen/rejected pair at index "
                f"{index}: {chosen_id!r}/{rejected_id!r}"
            )
        combinations.add(combination)


def summarize_pairs(pairs: list[dict]) -> dict[str, Any]:
    """Return validated pair and distinct-category counts for Tier 3 audits."""
    _validate_pairs(pairs)
    eligible = [pair for pair in pairs if not pair["synthetic"]]
    categories = sorted({pair["slot"]["blueprint_category"] for pair in eligible})
    return {
        "validated_pair_count": len(pairs),
        "pair_count": len(eligible),
        "category_count": len(categories),
        "categories": categories,
    }


def _audit_file_label(root: Path, path: Path) -> str:
    if root.is_file():
        return path.name
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def audit_preferences(root: str | Path) -> dict[str, Any]:
    """Validate and summarize every preferences.jsonl below ``root``."""
    root_path = Path(root)
    if root_path.is_file():
        files = [root_path] if root_path.name == "preferences.jsonl" else []
    else:
        files = sorted(root_path.rglob("preferences.jsonl"))

    errors: list[str] = []
    duplicates: list[dict[str, str]] = []
    seen: dict[tuple[str, str], str] = {}
    valid_pairs: list[dict] = []
    for path in files:
        label = _audit_file_label(root_path, path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            errors.append(f"{label}: could not read file: {error}")
            continue
        for lineno, line in enumerate(lines, start=1):
            location = f"{label}:line {lineno}"
            try:
                record = json.loads(line, parse_constant=_reject_json_constant)
            except (json.JSONDecodeError, ValueError) as error:
                errors.append(f"{location}: malformed JSON: {error}")
                continue
            validation_errors = validate_pair(record)
            if validation_errors:
                errors.extend(f"{location}: {error}" for error in validation_errors)
                continue
            valid_pairs.append(record)
            identity = (record["chosen"]["id"], record["rejected"]["id"])
            if first := seen.get(identity):
                duplicates.append(
                    {
                        "chosen_id": identity[0],
                        "rejected_id": identity[1],
                        "first": first,
                        "duplicate": location,
                    }
                )
            else:
                seen[identity] = location

    eligible = [pair for pair in valid_pairs if not pair["synthetic"]]
    categories = sorted({pair["slot"]["blueprint_category"] for pair in eligible})
    return {
        "file_count": len(files),
        "validated_pair_count": len(valid_pairs),
        "validated_non_synthetic_pair_count": len(eligible),
        "categories": categories,
        "category_count": len(categories),
        "duplicates": duplicates,
        "errors": errors,
        "tier3_ready": (
            len(eligible) >= TIER3_MIN_PAIRS
            and len(categories) >= TIER3_MIN_CATEGORIES
            and not duplicates
            and not errors
        ),
    }


def write_jsonl(path: str, pairs: list[dict]) -> int:
    """Atomically replace one run's JSONL after validating every record."""
    _validate_pairs(pairs)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = file.name
            for pair in pairs:
                file.write(json.dumps(pair, ensure_ascii=False, allow_nan=False) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
    return len(pairs)
