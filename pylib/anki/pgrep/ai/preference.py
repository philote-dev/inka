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

_PRIVATE_MARKER = re.compile(
    r"(?i)(?<![a-z0-9])(?:"
    r"(?:gold|heldout|ets|gr9677|gr1777)(?=$|[-_/:\\])"
    r"|tier[\s_-]*3(?=$|[\s_/:\\-])"
    r")"
)
_CORRECT_CHOICES = frozenset("ABCDE")


def _failing_gates(item: dict) -> list[str]:
    panel = item.get("panel") or {}
    checks = panel.get("checks") or []
    out = [
        c.get("name", "")
        for c in checks
        if isinstance(c, dict)
        and not c.get("passed", True)
        and c.get("severity") == "hard"
    ]
    if not out and item.get("reason"):
        out = [
            part.split(":")[0].strip()
            for part in str(item["reason"]).split(";")
            if part.strip()
        ]
    return [g for g in out if g]


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _child_path(path: str, key: object) -> str:
    return f"{path}.{key}" if isinstance(key, str) else f"{path}[{key!r}]"


def _recursive_data_errors(value: object, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: non-finite numbers are not allowed")
    elif isinstance(value, str):
        if marker := _PRIVATE_MARKER.search(value):
            errors.append(f"{path}: private marker {marker.group(0)!r}")
    elif isinstance(value, dict):
        for key, nested in value.items():
            child = _child_path(path, key)
            if isinstance(key, str) and (marker := _PRIVATE_MARKER.search(key)):
                errors.append(
                    f"{child} (key): private marker {marker.group(0)!r}"
                )
            elif isinstance(key, float) and not math.isfinite(key):
                errors.append(f"{child} (key): non-finite numbers are not allowed")
            errors.extend(_recursive_data_errors(nested, child))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            errors.extend(_recursive_data_errors(nested, f"{path}[{index}]"))
    return errors


def private_marker_errors(value: object, path: str = "$") -> list[str]:
    """Return recursive private-marker errors with nested JSON-style paths."""
    return [
        error
        for error in _recursive_data_errors(value, path)
        if "private marker" in error
    ]


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
        errors.append(
            f"{side}.choices must contain exactly five non-empty strings"
        )

    correct = node.get("correct")
    if not isinstance(correct, str) or correct not in _CORRECT_CHOICES:
        errors.append(f"{side}.correct must be exactly one of A, B, C, D, or E")

    panel = node.get("panel")
    if not isinstance(panel, dict):
        errors.append(f"{side}.panel must be an object")
    elif panel.get("decision") != decision:
        errors.append(f"{side}.panel.decision must be {decision!r}")
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
    return []


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

    slot = pair.get("slot")
    if not isinstance(slot, dict):
        errors.append("slot must be an object")
    else:
        for field in ("topic", "blueprint_category"):
            if not _non_empty_string(slot.get(field)):
                errors.append(f"slot.{field} must be a non-empty string")

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
    slot: dict, result: SlotResult, *, run_id: str, max_pairs: int = 64
) -> list[dict]:
    if max_pairs <= 0:
        return []

    pairs: list[dict] = []
    for chosen in result.accepted:
        for rejected in result.rejected:
            pair = {
                "schema": preference_schema_version,
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
    categories = sorted({pair["slot"]["blueprint_category"] for pair in pairs})
    return {
        "pair_count": len(pairs),
        "category_count": len(categories),
        "categories": categories,
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
                file.write(
                    json.dumps(pair, ensure_ascii=False, allow_nan=False) + "\n"
                )
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
