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

_PRIVATE_ID_MARKERS = ("gold-", "heldout-", "ets-", "tier3-", "gr9677-", "gr1777-")


def _failing_gates(item: dict) -> list[str]:
    panel = item.get("panel") or {}
    checks = panel.get("checks") or []
    out = [
        c.get("name", "")
        for c in checks
        if isinstance(c, dict) and not c.get("passed", True) and c.get("severity") == "hard"
    ]
    if not out and item.get("reason"):
        out = [
            part.split(":")[0].strip()
            for part in str(item["reason"]).split(";")
            if part.strip()
        ]
    return [g for g in out if g]


def validate_pair(pair: dict) -> list[str]:
    errs: list[str] = []
    if pair.get("schema") != preference_schema_version:
        errs.append(f"schema must be {preference_schema_version}")
    for side in ("chosen", "rejected"):
        node = pair.get(side)
        if not isinstance(node, dict):
            errs.append(f"{side} missing")
            continue
        for k in ("id", "stem", "choices", "correct", "panel"):
            if k not in node:
                errs.append(f"{side}.{k} missing")
        iid = str((node or {}).get("id", "")).lower()
        if any(m in iid for m in _PRIVATE_ID_MARKERS):
            errs.append(f"{side}.id looks private: {iid}")
    if "run_id" not in pair:
        errs.append("run_id missing")
    if "slot" not in pair:
        errs.append("slot missing")
    if isinstance(pair.get("rejected"), dict) and "failing_gates" not in pair["rejected"]:
        errs.append("rejected.failing_gates missing")
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
