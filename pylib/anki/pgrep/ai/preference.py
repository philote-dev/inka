# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Preference dataset emitter for foundry runs (WS8).

Chosen = panel accept. Rejected = panel reject with failing gates recorded.
Escalations are not preference pairs (human still owns them). Schema stays
stable so Tier 3 SFT/DPO can consume it later without rewriting the loop.
"""

from __future__ import annotations

import json
import os

from .foundry_loop import SlotResult

preference_schema_version = 1

_PRIVATE_ID_MARKERS = (
    "gold-",
    "heldout-",
    "ets-",
    "tier3-",
    "gr9677-",
    "gr1777-",
)
_REQUIRED_ITEM_FIELDS = ("id", "stem", "choices", "correct", "panel")


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


def _validate_item(side: str, node: object) -> list[str]:
    if not isinstance(node, dict):
        return [f"{side} missing"]

    errs = [f"{side}.{key} missing" for key in _REQUIRED_ITEM_FIELDS if key not in node]
    iid = node.get("id")
    if "id" in node and (not isinstance(iid, str) or not iid.strip()):
        errs.append(f"{side}.id must be a non-empty string")
    elif isinstance(iid, str) and any(
        marker in iid.lower() for marker in _PRIVATE_ID_MARKERS
    ):
        errs.append(f"{side}.id looks private: {iid.lower()}")
    return errs


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


def validate_pair(pair: dict) -> list[str]:
    errs: list[str] = []
    if pair.get("schema") != preference_schema_version:
        errs.append(f"schema must be {preference_schema_version}")
    for side in ("chosen", "rejected"):
        errs.extend(_validate_item(side, pair.get(side)))
    if "run_id" not in pair:
        errs.append("run_id missing")
    if "slot" not in pair:
        errs.append("slot missing")
    errs.extend(_validate_failing_gates(pair.get("rejected")))
    return errs


def scan_jsonl(path: str) -> list[str]:
    errs: list[str] = []
    try:
        with open(path, encoding="utf-8") as file:
            for lineno, line in enumerate(file, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    errs.append(f"line {lineno}: malformed JSON: {error.msg}")
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
                    "panel": chosen.get("panel") or {},
                },
                "rejected": {
                    "id": rejected.get("id", ""),
                    "stem": rejected.get("stem", ""),
                    "choices": list(rejected.get("choices") or []),
                    "correct": rejected.get("correct") or rejected.get("key") or "",
                    "panel": rejected.get("panel") or {},
                    "failing_gates": _failing_gates(rejected),
                },
                "run_id": run_id,
            }
            if not validate_pair(pair):
                pairs.append(pair)
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def write_jsonl(path: str, pairs: list[dict]) -> int:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for pair in pairs:
            if validate_pair(pair):
                continue
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")
            n += 1
    return n
