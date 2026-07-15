# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import copy
import datetime
import json
import math
from pathlib import Path

import pytest

from anki.pgrep.ai import foundry_loop, preference, verifier


def _item(i, decision="accept"):
    checks = [
        {
            "name": "key",
            "passed": decision == "accept",
            "severity": "hard",
            "evidence": "synthetic panel evidence",
        }
    ]
    return {
        "id": f"cand-{i}",
        "stem": f"stem {i}",
        "choices": ["a", "b", "c", "d", "e"],
        "correct": "A",
        "source_ref": f"corpus://source/{i}",
        "panel": {"decision": decision, "checks": checks},
        "reason": "key: disagree" if decision == "reject" else "",
    }


def _slot(category: str = "optics_waves") -> dict:
    return {"topic": "thin lenses", "blueprint_category": category}


def _valid_pair(
    chosen_id="cand-1",
    rejected_id="cand-2",
    *,
    category: str = "optics_waves",
    synthetic: bool = False,
):
    return {
        "schema": 1,
        "synthetic": synthetic,
        "slot": _slot(category),
        "chosen": {
            "id": chosen_id,
            "stem": "chosen stem",
            "choices": ["a"] * 5,
            "correct": "A",
            "source_ref": "corpus://source/chosen",
            "panel": {
                "decision": "accept",
                "checks": [
                    {
                        "name": "key",
                        "passed": True,
                        "severity": "hard",
                        "evidence": "verified",
                    }
                ],
            },
        },
        "rejected": {
            "id": rejected_id,
            "stem": "rejected stem",
            "choices": ["a"] * 5,
            "correct": "B",
            "source_ref": "corpus://source/rejected",
            "panel": {
                "decision": "reject",
                "checks": [
                    {
                        "name": "key",
                        "passed": False,
                        "severity": "hard",
                        "evidence": "disagreed",
                    }
                ],
            },
            "failing_gates": ["key"],
            "reason": "key: disagree",
            "refused": False,
        },
        "run_id": "r",
    }


def _set_path(value: dict, path: tuple[str, ...], replacement: object) -> None:
    node = value
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = replacement


def _finalize_preferences(path: Path) -> None:
    (path.parent / "_SUCCESS").write_text("ok\n", encoding="utf-8")


def test_pairs_from_slot_emits_chosen_rejected():
    result = foundry_loop.SlotResult(
        accepted=[_item(1, "accept")],
        rejected=[_item(2, "reject")],
        escalated=[],
    )
    pairs = preference.pairs_from_slot(_slot(), result, run_id="run-1")
    assert len(pairs) == 1
    assert pairs[0]["schema"] == 1
    assert pairs[0]["synthetic"] is False
    assert pairs[0]["slot"] == _slot()
    assert pairs[0]["chosen"]["id"] == "cand-1"
    assert pairs[0]["chosen"]["source_ref"] == "corpus://source/1"
    assert pairs[0]["rejected"]["id"] == "cand-2"
    assert pairs[0]["rejected"]["failing_gates"] == ["key"]
    assert pairs[0]["rejected"]["reason"] == "key: disagree"
    assert pairs[0]["run_id"] == "run-1"
    assert preference.validate_pair(pairs[0]) == []


def test_pairs_from_slot_uses_failed_hard_checks_for_failing_gates():
    rejected = _item(2, "reject")
    rejected["reason"] = "answer_key: disagreement"
    rejected["panel"]["checks"] = [
        {
            "name": "answer_key",
            "passed": False,
            "severity": "hard",
            "evidence": "independent solve disagreed",
        },
        {"name": "wording", "passed": False, "severity": "soft"},
        {"name": "citation", "passed": True, "severity": "hard"},
    ]
    result = foundry_loop.SlotResult(
        accepted=[_item(1, "accept")],
        rejected=[rejected],
    )

    pairs = preference.pairs_from_slot(_slot(), result, run_id="run-1")

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
    ("path", "invalid", "error"),
    [
        (("run_id",), "", "run_id"),
        (("synthetic",), "false", "synthetic"),
        (("slot", "topic"), "", "slot.topic"),
        (("slot", "blueprint_category"), " ", "slot.blueprint_category"),
        (("chosen", "stem"), "", "chosen.stem"),
        (("rejected", "stem"), " ", "rejected.stem"),
        (("chosen", "choices"), ["a"] * 4, "chosen.choices"),
        (("rejected", "choices"), ["a", "b", "", "d", "e"], "rejected.choices"),
        (("chosen", "correct"), "F", "chosen.correct"),
        (("rejected", "correct"), "a", "rejected.correct"),
        (("chosen", "panel"), [], "chosen.panel"),
        (("rejected", "panel"), None, "rejected.panel"),
        (("chosen", "panel", "decision"), "reject", "chosen.panel.decision"),
        (("rejected", "panel", "decision"), "accept", "rejected.panel.decision"),
        (("chosen", "source_ref"), "", "chosen.source_ref"),
        (("rejected", "source_ref"), 42, "rejected.source_ref"),
        (("rejected", "reason"), "", "rejected.reason"),
        (("rejected", "refused"), "false", "rejected.refused"),
    ],
)
def test_validate_pair_enforces_semantic_field_contract(path, invalid, error):
    pair = _valid_pair()
    _set_path(pair, path, invalid)

    assert any(error in item for item in preference.validate_pair(pair))


def test_validate_pair_requires_slot_object():
    pair = _valid_pair()
    pair["slot"] = []

    assert any("slot" in item for item in preference.validate_pair(pair))


@pytest.mark.parametrize(
    "category",
    [
        "mechanics",
        "electromagnetism",
        "quantum",
        "thermodynamics",
        "atomic",
        "optics_waves",
        "special_relativity",
        "lab",
        "specialized",
    ],
)
def test_validate_pair_accepts_locked_blueprint_categories(category):
    assert preference.validate_pair(_valid_pair(category=category)) == []


@pytest.mark.parametrize(
    "category",
    [
        "optics",
        "Optics_Waves",
        " optics_waves",
        "optics_waves ",
        "special-relativity",
        "classical_mechanics",
    ],
)
def test_validate_pair_rejects_category_variants(category):
    errors = preference.validate_pair(_valid_pair(category=category))

    assert any("slot.blueprint_category" in error for error in errors)


def test_validate_pair_requires_distinct_ids():
    pair = _valid_pair()
    pair["rejected"]["id"] = pair["chosen"]["id"]

    assert any("distinct" in item for item in preference.validate_pair(pair))


def test_validate_pair_requires_failed_hard_checks_to_match_failing_gates():
    pair = _valid_pair()
    pair["rejected"]["failing_gates"] = ["figure"]

    errors = preference.validate_pair(pair)

    assert any("failed hard check names" in error for error in errors)


def test_validate_pair_requires_rejected_panel_evidence():
    pair = _valid_pair()
    pair["rejected"]["panel"]["checks"][0]["evidence"] = ""

    errors = preference.validate_pair(pair)

    assert any("evidence" in error for error in errors)


def test_non_synthetic_chosen_requires_checks():
    pair = _valid_pair()
    pair["chosen"]["panel"]["checks"] = []

    errors = preference.validate_pair(pair)

    assert any("non-synthetic chosen" in error for error in errors)


def test_synthetic_chosen_allows_empty_checks():
    pair = _valid_pair(synthetic=True)
    pair["chosen"]["panel"]["checks"] = []

    assert preference.validate_pair(pair) == []


def test_real_panel_accept_with_empty_evidence_emits_and_validates():
    accepted = _item(1, "accept")
    accepted["panel"] = verifier.PanelVerdict(
        "accept",
        [
            verifier.CheckVerdict(
                "key",
                "hard",
                True,
                0.95,
                "",
            ),
            verifier.CheckVerdict(
                "giveaway",
                "soft",
                True,
                0.9,
                "",
            ),
        ],
    ).to_dict()
    result = foundry_loop.SlotResult(
        accepted=[accepted],
        rejected=[_item(2, "reject")],
    )

    pair = preference.pairs_from_slot(_slot(), result, run_id="real-run")[0]

    assert pair["chosen"]["panel"]["checks"][0]["evidence"] == ""
    assert preference.validate_pair(pair) == []


def test_chosen_accept_with_failed_hard_check_is_rejected():
    pair = _valid_pair()
    pair["chosen"]["panel"]["checks"].append(
        {
            "name": "figure",
            "passed": False,
            "severity": "hard",
            "evidence": "mismatch",
        }
    )

    errors = preference.validate_pair(pair)

    assert any("chosen" in error and "failed hard" in error for error in errors)


def test_pairs_from_slot_excludes_explicit_refusal():
    refused = _item(2, "reject")
    refused.update(
        {
            "refused": True,
            "refusal_reason": "source could not be verified",
            "reason": "source could not be verified",
            "panel": {"decision": "reject", "checks": [], "refusal": True},
            "preference_exclusion_reason": "panel refusal",
        }
    )
    result = foundry_loop.SlotResult(
        accepted=[_item(1, "accept")],
        rejected=[refused],
    )

    pairs, summary = preference.build_pairs_from_slot(
        _slot(),
        result,
        run_id="run-1",
    )

    assert pairs == []
    assert summary == {
        "emitted": 0,
        "excluded": 1,
        "exclusion_reasons": {"panel_refusal": 1},
    }


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


@pytest.mark.parametrize("nonfinite", [math.nan, math.inf, -math.inf])
def test_validate_pair_rejects_nonfinite_numbers_recursively(nonfinite):
    pair = _valid_pair()
    pair["chosen"]["panel"]["evidence"] = {"score": nonfinite}

    errs = preference.validate_pair(pair)

    assert any("$.chosen.panel.evidence.score" in error for error in errs)


@pytest.mark.parametrize(
    "invalid",
    [
        {"not", "json"},
        ("tuple", "is", "not", "json"),
        datetime.datetime(2026, 7, 14),
    ],
)
def test_validate_pair_rejects_non_json_nested_values(invalid):
    pair = _valid_pair()
    pair["chosen"]["panel"]["evidence"] = invalid

    errors = preference.validate_pair(pair)

    assert any("$.chosen.panel.evidence" in error for error in errors)


def test_validate_pair_rejects_non_string_nested_keys():
    pair = _valid_pair()
    pair["chosen"]["panel"]["evidence"] = {1: "not a JSON object key"}

    errors = preference.validate_pair(pair)

    assert any("dict keys must be strings" in error for error in errors)


def test_scan_jsonl_reports_malformed_json_with_line_number(tmp_path: Path):
    path = tmp_path / "preferences.jsonl"
    path.write_text(json.dumps(_valid_pair()) + "\n{broken\n", encoding="utf-8")

    errs = preference.scan_jsonl(str(path))

    assert any("line 2" in err and "malformed json" in err.lower() for err in errs)


def test_scan_jsonl_reports_non_object_record_with_line_number(tmp_path: Path):
    path = tmp_path / "preferences.jsonl"
    path.write_text("[]\n", encoding="utf-8")

    errs = preference.scan_jsonl(str(path))

    assert any("line 1" in err and "object" in err.lower() for err in errs)


def test_scan_jsonl_reports_private_id_with_line_number(tmp_path: Path):
    path = tmp_path / "preferences.jsonl"
    path.write_text(
        json.dumps(_valid_pair(chosen_id="gold-001")) + "\n", encoding="utf-8"
    )

    errs = preference.scan_jsonl(str(path))

    assert any("line 1" in err and "private" in err.lower() for err in errs)


def test_scan_jsonl_reports_nested_panel_marker_path_and_line(tmp_path: Path):
    pair = _valid_pair()
    pair["chosen"]["panel"]["evidence"] = {"note": "derived from gold-17"}
    path = tmp_path / "preferences.jsonl"
    path.write_text(json.dumps(pair) + "\n", encoding="utf-8")

    errs = preference.scan_jsonl(str(path))

    assert any(
        "line 1" in error
        and "$.chosen.panel.evidence.note" in error
        and "gold" in error
        for error in errs
    )


@pytest.mark.parametrize(
    "marker",
    ["held-out:17", "held_out/17", "heldout-17", "tier-3:17", "tier_3/17"],
)
def test_scan_jsonl_reports_nested_slot_metadata_marker(tmp_path: Path, marker: str):
    pair = _valid_pair()
    pair["slot"]["metadata"] = {"source": {"identifier": marker}}
    path = tmp_path / "preferences.jsonl"
    path.write_text(json.dumps(pair) + "\n", encoding="utf-8")

    errs = preference.scan_jsonl(str(path))

    assert any("$.slot.metadata.source.identifier" in error for error in errs)


@pytest.mark.parametrize(
    "marker",
    [
        "gold-17",
        "gold_17",
        "gold/17",
        "heldout:17",
        "held-out:17",
        "held_out/17",
        "ets-17",
        "tier 3",
        "tier3_17",
        "tier-3/17",
        "tier_3:17",
        "gr9677/17",
        "gr1777_17",
    ],
)
def test_scan_jsonl_catches_private_marker_separator_variants(
    tmp_path: Path, marker: str
):
    pair = _valid_pair()
    pair["chosen"]["panel"]["evidence"] = marker
    path = tmp_path / "preferences.jsonl"
    path.write_text(json.dumps(pair) + "\n", encoding="utf-8")

    assert preference.scan_jsonl(str(path))


def test_scan_jsonl_checks_nested_keys(tmp_path: Path):
    pair = _valid_pair()
    pair["rejected"]["panel"]["gold_ref"] = "hidden"
    path = tmp_path / "preferences.jsonl"
    path.write_text(json.dumps(pair) + "\n", encoding="utf-8")

    errs = preference.scan_jsonl(str(path))

    assert any(
        "$.rejected.panel.gold_ref" in error and "key" in error for error in errs
    )


def test_validate_pair_allows_benign_marigold_text():
    pair = _valid_pair()
    pair["chosen"]["stem"] = "A marigold is placed near a converging lens."
    pair["chosen"]["panel"]["evidence"] = {"note": "marigold petals"}

    assert preference.validate_pair(pair) == []


def test_pairs_from_slot_caps_at_max_pairs():
    accepted = [_item(i, "accept") for i in range(10)]
    rejected = [_item(i + 10, "reject") for i in range(10)]
    result = foundry_loop.SlotResult(accepted=accepted, rejected=rejected, escalated=[])
    pairs = preference.pairs_from_slot(_slot(), result, run_id="run-1", max_pairs=64)
    assert len(pairs) == 64


@pytest.mark.parametrize("max_pairs", [0, -1])
def test_pairs_from_slot_nonpositive_cap_emits_no_records(max_pairs):
    result = foundry_loop.SlotResult(
        accepted=[_item(1, "accept")],
        rejected=[_item(2, "reject")],
    )

    assert (
        preference.pairs_from_slot(_slot(), result, run_id="run-1", max_pairs=max_pairs)
        == []
    )


def test_pairs_from_slot_ignores_escalated():
    result = foundry_loop.SlotResult(
        accepted=[_item(1, "accept")],
        rejected=[_item(2, "reject")],
        escalated=[_item(3, "escalate")],
    )
    pairs = preference.pairs_from_slot(_slot(), result, run_id="run-1")
    ids = {pairs[0]["chosen"]["id"], pairs[0]["rejected"]["id"]}
    assert ids == {"cand-1", "cand-2"}


def test_pairs_from_slot_fails_loudly_on_invalid_candidate():
    accepted = _item(1, "accept")
    del accepted["source_ref"]
    result = foundry_loop.SlotResult(
        accepted=[accepted],
        rejected=[_item(2, "reject")],
    )

    with pytest.raises(ValueError, match=r"chosen\.source_ref"):
        preference.pairs_from_slot(_slot(), result, run_id="run-1")


def test_write_jsonl_rejects_invalid_records_without_writing(tmp_path: Path):
    invalid = {"schema": 1}
    path = tmp_path / "out" / "pairs.jsonl"

    with pytest.raises(ValueError, match="invalid preference pair at index 0"):
        preference.write_jsonl(str(path), [invalid])

    assert not path.exists()


def test_write_jsonl_atomically_overwrites_existing_records(tmp_path: Path):
    first = _valid_pair()
    second = _valid_pair(chosen_id="generated-3", rejected_id="generated-4")
    second["run_id"] = "r-2"
    path = tmp_path / "pairs.jsonl"
    assert preference.write_jsonl(str(path), [first]) == 1

    assert preference.write_jsonl(str(path), [second]) == 1

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line) for line in lines] == [second]


def test_write_jsonl_rejects_duplicate_pair_combinations(tmp_path: Path):
    first = _valid_pair()
    duplicate = copy.deepcopy(first)
    duplicate["run_id"] = "another-run"

    with pytest.raises(ValueError, match="duplicate chosen/rejected pair"):
        preference.write_jsonl(str(tmp_path / "pairs.jsonl"), [first, duplicate])


def test_summarize_pairs_counts_six_distinct_categories():
    categories = [
        "mechanics",
        "electromagnetism",
        "quantum",
        "thermodynamics",
        "atomic",
        "optics_waves",
    ]
    pairs = []
    for index, category in enumerate(categories):
        pair = _valid_pair(
            f"chosen-{index}",
            f"rejected-{index}",
            category=category,
        )
        pairs.append(pair)

    assert preference.summarize_pairs(pairs) == {
        "validated_pair_count": 6,
        "pair_count": 6,
        "category_count": 6,
        "categories": sorted(categories),
    }


def test_audit_preferences_counts_only_non_synthetic_pairs(tmp_path: Path):
    real = _valid_pair("real-chosen", "real-rejected", category="mechanics")
    synthetic = _valid_pair(
        "dry-chosen",
        "dry-rejected",
        category="quantum",
        synthetic=True,
    )
    real_path = tmp_path / "run-a" / "preferences.jsonl"
    synthetic_path = tmp_path / "run-b" / "preferences.jsonl"
    preference.write_jsonl(str(real_path), [real])
    preference.write_jsonl(str(synthetic_path), [synthetic])
    _finalize_preferences(real_path)
    _finalize_preferences(synthetic_path)

    audit = preference.audit_preferences(tmp_path)

    assert audit["validated_pair_count"] == 2
    assert audit["validated_non_synthetic_pair_count"] == 1
    assert audit["excluded_synthetic_pair_count"] == 1
    assert audit["categories"] == ["mechanics"]
    assert audit["category_count"] == 1
    assert audit["duplicates"] == []
    assert audit["errors"] == []
    assert not audit["tier3_ready"]


def test_audit_preferences_only_reads_finalized_run_directories(tmp_path: Path):
    finalized = tmp_path / "run-final" / "preferences.jsonl"
    active = tmp_path / ".run-active.tmp" / "preferences.jsonl"
    orphan = tmp_path / "run-orphan" / "preferences.jsonl"
    bare = tmp_path / "preferences.jsonl"
    preference.write_jsonl(
        str(finalized),
        [_valid_pair("final-chosen", "final-rejected")],
    )
    preference.write_jsonl(
        str(active),
        [_valid_pair("active-chosen", "active-rejected")],
    )
    preference.write_jsonl(
        str(orphan),
        [_valid_pair("orphan-chosen", "orphan-rejected")],
    )
    preference.write_jsonl(
        str(bare),
        [_valid_pair("bare-chosen", "bare-rejected")],
    )
    _finalize_preferences(finalized)

    audit = preference.audit_preferences(tmp_path)

    assert audit["file_count"] == 1
    assert audit["validated_non_synthetic_pair_count"] == 1
    assert audit["errors"] == []


def test_audit_preferences_detects_duplicates_across_runs(tmp_path: Path):
    first = _valid_pair()
    duplicate = copy.deepcopy(first)
    duplicate["run_id"] = "run-b"
    first_path = tmp_path / "run-a" / "preferences.jsonl"
    duplicate_path = tmp_path / "run-b" / "preferences.jsonl"
    preference.write_jsonl(str(first_path), [first])
    preference.write_jsonl(str(duplicate_path), [duplicate])
    _finalize_preferences(first_path)
    _finalize_preferences(duplicate_path)

    audit = preference.audit_preferences(tmp_path)

    assert len(audit["duplicates"]) == 1
    assert audit["duplicates"][0]["chosen_id"] == first["chosen"]["id"]
    assert audit["duplicates"][0]["rejected_id"] == first["rejected"]["id"]
    assert not audit["tier3_ready"]


def test_audit_preferences_reports_invalid_category_with_file_and_line(
    tmp_path: Path,
):
    pair = _valid_pair()
    pair["slot"]["blueprint_category"] = "Optics"
    path = tmp_path / "run-a" / "preferences.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(pair) + "\n", encoding="utf-8")
    _finalize_preferences(path)

    audit = preference.audit_preferences(tmp_path)

    assert any(
        "run-a/preferences.jsonl:line 1" in error and "blueprint_category" in error
        for error in audit["errors"]
    )


def test_audit_preferences_tier3_ready_requires_1000_pairs_and_six_categories(
    tmp_path: Path,
):
    categories = [
        "mechanics",
        "electromagnetism",
        "quantum",
        "thermodynamics",
        "atomic",
        "optics_waves",
    ]
    pairs = [
        _valid_pair(
            f"chosen-{index}",
            f"rejected-{index}",
            category=categories[index % len(categories)],
        )
        for index in range(1000)
    ]
    path = tmp_path / "run-a" / "preferences.jsonl"
    preference.write_jsonl(str(path), pairs)
    _finalize_preferences(path)

    audit = preference.audit_preferences(tmp_path)

    assert audit["validated_non_synthetic_pair_count"] == 1000
    assert audit["category_count"] == 6
    assert audit["tier3_ready"]
