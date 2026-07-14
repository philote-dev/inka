# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import json
import tempfile
from pathlib import Path

from anki.pgrep.ai import foundry_loop, preference


def _item(i, decision="accept"):
    return {
        "id": f"cand-{i}",
        "stem": f"stem {i}",
        "choices": ["a", "b", "c", "d", "e"],
        "correct": "A",
        "panel": {"decision": decision, "checks": []},
        "reason": "key: disagree" if decision == "reject" else "",
    }


def test_pairs_from_slot_emits_chosen_rejected():
    result = foundry_loop.SlotResult(
        accepted=[_item(1, "accept")],
        rejected=[_item(2, "reject")],
        escalated=[],
    )
    pairs = preference.pairs_from_slot({"topic": "optics"}, result, run_id="run-1")
    assert len(pairs) == 1
    assert pairs[0]["schema"] == 1
    assert pairs[0]["chosen"]["id"] == "cand-1"
    assert pairs[0]["rejected"]["id"] == "cand-2"
    assert pairs[0]["rejected"]["failing_gates"] == ["key"]
    assert pairs[0]["run_id"] == "run-1"
    assert preference.validate_pair(pairs[0]) == []


def test_validate_pair_rejects_missing_fields():
    errs = preference.validate_pair({"schema": 1})
    assert errs


def test_validate_pair_rejects_private_id_prefixes():
    pair = {
        "schema": 1,
        "slot": {"topic": "optics"},
        "chosen": {
            "id": "gold-001",
            "stem": "s",
            "choices": ["a"] * 5,
            "correct": "A",
            "panel": {},
        },
        "rejected": {
            "id": "cand-2",
            "stem": "s",
            "choices": ["a"] * 5,
            "correct": "B",
            "panel": {},
            "failing_gates": ["key"],
        },
        "run_id": "r",
    }
    errs = preference.validate_pair(pair)
    assert any("gold" in e.lower() or "private" in e.lower() for e in errs)


def test_pairs_from_slot_caps_at_max_pairs():
    accepted = [_item(i, "accept") for i in range(10)]
    rejected = [_item(i + 10, "reject") for i in range(10)]
    result = foundry_loop.SlotResult(accepted=accepted, rejected=rejected, escalated=[])
    pairs = preference.pairs_from_slot(
        {"topic": "optics"}, result, run_id="run-1", max_pairs=64
    )
    assert len(pairs) == 64


def test_pairs_from_slot_ignores_escalated():
    result = foundry_loop.SlotResult(
        accepted=[_item(1, "accept")],
        rejected=[_item(2, "reject")],
        escalated=[_item(3, "escalate")],
    )
    pairs = preference.pairs_from_slot({"topic": "optics"}, result, run_id="run-1")
    ids = {pairs[0]["chosen"]["id"], pairs[0]["rejected"]["id"]}
    assert ids == {"cand-1", "cand-2"}


def test_write_jsonl_skips_invalid_records():
    valid = {
        "schema": 1,
        "slot": {"topic": "optics"},
        "chosen": {
            "id": "cand-1",
            "stem": "s",
            "choices": ["a"] * 5,
            "correct": "A",
            "panel": {},
        },
        "rejected": {
            "id": "cand-2",
            "stem": "s",
            "choices": ["a"] * 5,
            "correct": "B",
            "panel": {},
            "failing_gates": ["key"],
        },
        "run_id": "r",
    }
    invalid = {"schema": 1}
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "out" / "pairs.jsonl")
        count = preference.write_jsonl(path, [invalid, valid, invalid])
        assert count == 1
        lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == valid
