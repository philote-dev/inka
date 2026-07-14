# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import json
import tempfile
from pathlib import Path

import pytest

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


def _valid_pair(chosen_id="cand-1", rejected_id="cand-2"):
    return {
        "schema": 1,
        "slot": {"topic": "optics"},
        "chosen": {
            "id": chosen_id,
            "stem": "chosen stem",
            "choices": ["a"] * 5,
            "correct": "A",
            "panel": {},
        },
        "rejected": {
            "id": rejected_id,
            "stem": "rejected stem",
            "choices": ["a"] * 5,
            "correct": "B",
            "panel": {},
            "failing_gates": ["key"],
        },
        "run_id": "r",
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


def test_pairs_from_slot_uses_failed_hard_checks_for_failing_gates():
    rejected = _item(2, "reject")
    rejected["reason"] = ""
    rejected["panel"]["checks"] = [
        {"name": "answer_key", "passed": False, "severity": "hard"},
        {"name": "wording", "passed": False, "severity": "soft"},
        {"name": "citation", "passed": True, "severity": "hard"},
    ]
    result = foundry_loop.SlotResult(
        accepted=[_item(1, "accept")],
        rejected=[rejected],
    )

    pairs = preference.pairs_from_slot({"topic": "optics"}, result, run_id="run-1")

    assert pairs[0]["rejected"]["failing_gates"] == ["answer_key"]


def test_validate_pair_rejects_missing_fields():
    errs = preference.validate_pair({"schema": 1})
    assert errs


@pytest.mark.parametrize("side", ["chosen", "rejected"])
def test_validate_pair_rejects_missing_ids(side):
    pair = _valid_pair()
    del pair[side]["id"]

    errs = preference.validate_pair(pair)

    assert any(f"{side}.id" in err for err in errs)


@pytest.mark.parametrize("side", ["chosen", "rejected"])
@pytest.mark.parametrize("invalid_id", ["", "   ", None, 42])
def test_validate_pair_rejects_empty_or_non_string_ids(side, invalid_id):
    pair = _valid_pair()
    pair[side]["id"] = invalid_id

    errs = preference.validate_pair(pair)

    assert any(f"{side}.id" in err for err in errs)


def test_validate_pair_allows_safe_non_candidate_ids():
    pair = _valid_pair(chosen_id="run42/item-7", rejected_id="generated_8")

    assert preference.validate_pair(pair) == []


@pytest.mark.parametrize(
    "invalid_gates",
    [[], "key", [""], ["   "], ["key", 42]],
)
def test_validate_pair_rejects_invalid_failing_gates(invalid_gates):
    pair = _valid_pair()
    pair["rejected"]["failing_gates"] = invalid_gates

    errs = preference.validate_pair(pair)

    assert any("rejected.failing_gates" in err for err in errs)


def test_validate_pair_rejects_private_id_prefixes():
    pair = _valid_pair(chosen_id="gold-001")
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
    valid = _valid_pair()
    invalid = {"schema": 1}
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "out" / "pairs.jsonl")
        count = preference.write_jsonl(path, [invalid, valid, invalid])
        assert count == 1
        lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == valid


def test_write_jsonl_appends_to_existing_records():
    first = _valid_pair()
    second = _valid_pair(chosen_id="generated-3", rejected_id="generated-4")
    second["run_id"] = "r-2"
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "pairs.jsonl")
        assert preference.write_jsonl(path, [first]) == 1

        assert preference.write_jsonl(path, [second]) == 1

        lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
        assert [json.loads(line) for line in lines] == [first, second]
