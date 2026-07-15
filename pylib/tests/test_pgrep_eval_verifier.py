# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline regression tests for the standing verifier evaluation.

No test in this module constructs a model client or touches the network.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for _path in (REPO / "pylib" / "anki", REPO / "content" / "tools"):
    if str(_path) not in sys.path:
        sys.path.append(str(_path))

from pgrep.ai import preference  # type: ignore[import-not-found]  # noqa: E402


def _module():
    return importlib.import_module("eval_verifier")


_CATEGORIES = [
    "mechanics",
    "electromagnetism",
    "quantum",
    "thermodynamics",
    "atomic",
    "optics_waves",
    "special_relativity",
    "lab",
    "specialized",
]


def _property(prefix: str, *, count: int = 30, positives: int = 24) -> dict:
    human = [True] * positives + [False] * (count - positives)
    predicted = list(human)
    return {
        "item_ids": [f"{prefix}-{index}" for index in range(count)],
        "predicted": predicted,
        "human": human,
        "confidence": [0.95] * positives + [0.2] * (count - positives),
        "runs": [
            list(predicted),
            list(predicted),
        ],
    }


def _labels() -> dict:
    return {
        split: {
            "properties": {
                "key": _property(f"{split}-key"),
                "figure": _property(f"{split}-figure"),
            }
        }
        for split in ("calibration", "heldout")
    }


def _foundry() -> dict:
    return {
        "slots": [
            {
                "blueprint_category": category,
                "accepted": 19,
                "rejected": 0,
                "escalated": 1,
            }
            for category in _CATEGORIES[:6]
        ]
    }


def _checks(report: dict) -> dict[str, dict]:
    return {check["name"]: check for check in report["gates"]["checks"]}


def _audit_pair() -> dict:
    return {
        "schema": 1,
        "synthetic": False,
        "slot": {"topic": "dynamics", "blueprint_category": "mechanics"},
        "chosen": {
            "id": "chosen-1",
            "stem": "chosen stem",
            "choices": ["a", "b", "c", "d", "e"],
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
            "id": "rejected-1",
            "stem": "rejected stem",
            "choices": ["a", "b", "c", "d", "e"],
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
        "run_id": "run-1",
    }


def test_evaluate_labels_requires_explicit_calibration_and_heldout_splits():
    with pytest.raises(ValueError, match="calibration"):
        _module().evaluate_labels(
            {"properties": {"key": _property("undifferentiated")}}
        )


def test_heldout_split_rejects_item_text_fields():
    labels = _labels()
    labels["heldout"]["properties"]["key"]["item_text"] = "private item text"

    with pytest.raises(ValueError, match=r"heldout\.properties\.key.*item_text"):
        _module().evaluate_labels(labels)


def test_property_item_ids_must_be_aligned_unique_non_empty_strings():
    labels = _labels()
    labels["heldout"]["properties"]["key"]["item_ids"][1] = labels["heldout"][
        "properties"
    ]["key"]["item_ids"][0]

    with pytest.raises(ValueError, match="item_ids must contain unique"):
        _module().evaluate_labels(labels)


def test_calibration_and_heldout_item_ids_must_not_overlap_across_properties():
    labels = _labels()
    labels["heldout"]["properties"]["figure"]["item_ids"][0] = labels["calibration"][
        "properties"
    ]["key"]["item_ids"][0]

    with pytest.raises(ValueError, match="calibration and heldout item_ids overlap"):
        _module().evaluate_labels(labels)


def test_evaluate_labels_returns_split_reports_and_threshold_diagnostics():
    report = _module().evaluate_labels(_labels(), foundry_summary=_foundry(), seed=17)

    calibration = {item["name"]: item for item in report["calibration"]["properties"]}
    heldout = {item["name"]: item for item in report["heldout"]["properties"]}
    assert calibration["key"]["raw_agreement"] == 1.0
    assert calibration["key"]["consistency"] == 1.0
    assert heldout["key"]["accepted_precision"] == 1.0
    assert heldout["key"]["accepted"] == 24
    assert heldout["key"]["item_count"] == 30
    assert report["calibration"]["consistency"] == 1.0
    assert report["heldout"]["consistency"] == 1.0

    assert report["thresholds"]["key"] == {
        "target_precision": 0.95,
        "attainable": True,
        "cutoff": 0.95,
        "achieved_precision": 1.0,
        "retained": 24,
        "eligible": 24,
    }
    assert report["gates"]["green"]
    assert all(
        {"observed", "required", "pass", "support", "evidence"} <= check.keys()
        for check in report["gates"]["checks"]
    )


def test_heldout_changes_cannot_change_fitted_thresholds():
    labels = _labels()
    baseline = _module().evaluate_labels(labels)["thresholds"]
    adversarial = copy.deepcopy(labels)
    for name in ("key", "figure"):
        prop = adversarial["heldout"]["properties"][name]
        prop["human"] = [not value for value in prop["human"]]
        prop["confidence"] = list(reversed(prop["confidence"]))

    changed = _module().evaluate_labels(adversarial)["thresholds"]

    assert changed == baseline


def test_threshold_unattainable_when_confidence_one_accept_is_false():
    labels = _labels()
    labels["calibration"]["properties"]["key"].update(
        {
            "predicted": [True] * 10 + [False] * 20,
            "human": [False] * 10 + [True] * 5 + [False] * 15,
            "confidence": [1.0] * 10 + [0.2] * 20,
        }
    )

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())

    assert report["thresholds"]["key"] == {
        "target_precision": 0.95,
        "attainable": False,
        "cutoff": None,
        "achieved_precision": 0.0,
        "retained": 10,
        "eligible": 10,
    }
    assert not report["gates"]["green"]
    assert not _checks(report)["calibration.key.threshold_attainable"]["pass"]


def test_threshold_diagnostics_expose_tiny_support():
    labels = _labels()
    labels["calibration"]["properties"]["key"].update(
        {
            "item_ids": ["calibration-tiny-0", "calibration-tiny-1"],
            "predicted": [True, False],
            "human": [True, False],
            "confidence": [0.73, 0.1],
            "runs": [[True, False], [True, False]],
        }
    )
    labels["heldout"]["properties"]["key"].update(
        {
            "item_ids": ["heldout-tiny-0", "heldout-tiny-1"],
            "predicted": [True, False],
            "human": [True, False],
            "confidence": [0.8, 0.2],
            "runs": [[True, False], [True, False]],
        }
    )

    threshold = _module().evaluate_labels(labels)["thresholds"]["key"]

    assert threshold["attainable"]
    assert threshold["cutoff"] == 0.73
    assert threshold["achieved_precision"] == 1.0
    assert threshold["retained"] == 1
    assert threshold["eligible"] == 1


def test_heldout_accepted_precision_uses_fixed_calibration_cutoff():
    labels = _labels()
    labels["calibration"]["properties"]["key"]["confidence"] = [0.8] * 24 + [0.2] * 6
    labels["heldout"]["properties"]["key"].update(
        {
            "predicted": [True] * 24 + [False] * 6,
            "human": [True] * 20 + [False] * 10,
            "confidence": [0.9] * 20 + [0.7] * 4 + [0.2] * 6,
        }
    )

    report = _module().evaluate_labels(labels)
    key = {item["name"]: item for item in report["heldout"]["properties"]}["key"]

    assert report["thresholds"]["key"]["cutoff"] == 0.8
    assert key["eligible"] == 24
    assert key["accepted"] == 20
    assert key["accepted_precision"] == 1.0


def test_consistency_includes_original_verdicts():
    labels = _labels()
    labels["heldout"]["properties"]["key"].update(
        {
            "item_ids": ["heldout-consistency-0", "heldout-consistency-1"],
            "predicted": [True, False],
            "human": [True, False],
            "confidence": [0.9, 0.2],
            "runs": [[False, True], [False, True]],
        }
    )

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())
    key = {item["name"]: item for item in report["heldout"]["properties"]}["key"]

    assert key["consistency"] == 0.0
    assert not _checks(report)["heldout.key.consistency"]["pass"]


def test_missing_consistency_evidence_forces_red_gate():
    labels = _labels()
    del labels["heldout"]["properties"]["figure"]["runs"]

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())

    check = _checks(report)["heldout.figure.consistency"]
    assert check["observed"]["point"] is None
    assert check["evidence"] == "missing perturbation runs"
    assert not check["pass"]
    assert not report["gates"]["green"]


def test_missing_heldout_confidence_for_key_fails_post_threshold_gate():
    labels = _labels()
    del labels["heldout"]["properties"]["key"]["confidence"]

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())
    key = {item["name"]: item for item in report["heldout"]["properties"]}["key"]

    assert key["raw_agreement"] is None
    assert not _checks(report)["heldout.key.confidence_available"]["pass"]
    assert not report["gates"]["green"]


def test_key_and_figure_are_required_for_green_gate():
    labels = _labels()
    del labels["calibration"]["properties"]["figure"]
    del labels["heldout"]["properties"]["figure"]

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())

    assert not _checks(report)["required_property.figure"]["pass"]
    assert not report["gates"]["green"]


def test_split_support_requires_30_items_and_both_human_classes():
    labels = _labels()
    labels["calibration"]["properties"]["key"] = _property(
        "calibration-key-small",
        count=29,
        positives=24,
    )
    labels["heldout"]["properties"]["figure"]["human"] = [True] * 30

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())
    checks = _checks(report)

    assert not checks["calibration.key.sample_support"]["pass"]
    assert checks["calibration.key.sample_support"]["support"]["item_count"] == 29
    assert not checks["heldout.figure.sample_support"]["pass"]
    assert checks["heldout.figure.sample_support"]["support"]["human_negatives"] == 0
    assert not report["gates"]["green"]


def test_accepted_precision_requires_support_and_ci_lower_bound():
    labels = _labels()
    key = labels["heldout"]["properties"]["key"]
    key["predicted"] = [True] * 20 + [False] * 10
    key["human"] = [True] * 19 + [False] + [True] * 5 + [False] * 5
    key["confidence"] = [0.95] * 20 + [0.2] * 10
    key["runs"] = [list(key["predicted"]), list(key["predicted"])]

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())
    check = _checks(report)["heldout.key.accepted_precision"]

    assert check["observed"]["point"] == 0.95
    assert check["observed"]["ci_low"] < 0.95
    assert check["support"]["retained"] == 20
    assert not check["pass"]
    assert not report["gates"]["green"]


def test_post_threshold_metrics_expose_over_pruning_recall_loss():
    labels = _labels()
    calibration = labels["calibration"]["properties"]["key"]
    calibration["predicted"] = [True] * 24 + [False] * 6
    calibration["human"] = [True] * 20 + [False] * 4 + [True] * 5 + [False]
    calibration["confidence"] = [0.99] * 20 + [0.8] * 4 + [0.2] * 6
    calibration["runs"] = [
        list(calibration["predicted"]),
        list(calibration["predicted"]),
    ]

    heldout = labels["heldout"]["properties"]["key"]
    heldout["confidence"] = [0.99] * 5 + [0.8] * 19 + [0.2] * 6

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())
    key = {item["name"]: item for item in report["heldout"]["properties"]}["key"]

    assert report["thresholds"]["key"]["cutoff"] == 0.99
    assert key["pre_threshold"]["recall"] == 1.0
    assert key["recall"] == 5 / 24
    assert key["balanced_accuracy"] < 0.85
    assert not _checks(report)["heldout.key.balanced_accuracy"]["pass"]
    assert not report["gates"]["green"]


def test_foundry_support_requires_six_slots_and_categories():
    foundry = _foundry()
    foundry["slots"] = foundry["slots"][:5]

    report = _module().evaluate_labels(_labels(), foundry_summary=foundry)
    checks = _checks(report)

    assert not checks["foundry.slot_support"]["pass"]
    assert not checks["foundry.category_support"]["pass"]
    assert not report["gates"]["green"]


def test_foundry_escalation_gate_uses_ci_upper_bound():
    foundry = _foundry()
    escalation_counts = [0, 0, 0, 0, 2, 4]
    for slot, escalated in zip(foundry["slots"], escalation_counts):
        slot.update(
            accepted=10 - escalated,
            rejected=0,
            escalated=escalated,
        )

    report = _module().evaluate_labels(_labels(), foundry_summary=foundry)
    check = _checks(report)["foundry.escalation_rate"]

    assert check["observed"]["point"] == pytest.approx(0.1)
    assert check["observed"]["ci_high"] > 0.15
    assert not check["pass"]
    assert not report["gates"]["green"]


def test_standing_gate_uses_design_thresholds_for_every_property():
    labels = _labels()
    labels["calibration"]["properties"]["distractor"] = _property(
        "calibration-distractor"
    )
    labels["heldout"]["properties"]["distractor"] = {
        "item_ids": [f"heldout-distractor-{index}" for index in range(30)],
        "predicted": [False] * 30,
        "human": [True] * 5 + [False] * 25,
        "confidence": [0.9] * 30,
        "runs": [
            [False] * 30,
            [False] * 30,
        ],
    }
    labels["heldout"]["properties"]["key"]["human"] = [True] * 23 + [False] * 7
    foundry = _foundry()
    for slot in foundry["slots"]:
        slot.update(accepted=8, rejected=0, escalated=2)

    report = _module().evaluate_labels(labels, foundry_summary=foundry)
    checks = _checks(report)

    assert checks["heldout.distractor.raw_agreement"]["required"] == 0.9
    assert not checks["heldout.distractor.raw_agreement"]["pass"]
    assert checks["heldout.distractor.balanced_accuracy"]["required"] == 0.85
    assert not checks["heldout.distractor.balanced_accuracy"]["pass"]
    assert checks["heldout.key.accepted_precision"]["required"]["point"] == 0.95
    assert not checks["heldout.key.accepted_precision"]["pass"]
    assert checks["foundry.escalation_rate"]["required"]["point_max"] == 0.15
    assert not checks["foundry.escalation_rate"]["pass"]
    assert not report["gates"]["green"]


def test_main_rejects_mismatched_label_lengths(tmp_path, capsys):
    labels_path = tmp_path / "labels.json"
    labels = _labels()
    labels["heldout"]["properties"]["key"]["human"] = [True]
    labels_path.write_text(json.dumps(labels))

    with pytest.raises(SystemExit) as exc:
        _module().main(["--labels", str(labels_path)])

    assert exc.value.code == 2
    assert "predicted and human must have equal lengths" in capsys.readouterr().err


def test_main_rejects_a_single_perturbation_run(tmp_path, capsys):
    labels_path = tmp_path / "labels.json"
    labels = _labels()
    labels["heldout"]["properties"]["key"]["runs"] = [[True, True, False, False]]
    labels_path.write_text(json.dumps(labels))

    with pytest.raises(SystemExit) as exc:
        _module().main(["--labels", str(labels_path)])

    assert exc.value.code == 2
    assert "runs must contain at least 2" in capsys.readouterr().err


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_main_rejects_nonstandard_json_constants(tmp_path, capsys, constant):
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(f'{{"calibration": {constant}, "heldout": {{}}}}')

    with pytest.raises(SystemExit) as exc:
        _module().main(["--labels", str(labels_path)])

    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert f"non-standard JSON constant {constant}" in error
    assert "is not allowed" in error


def test_structurally_valid_red_main_writes_report_and_exits_nonzero(tmp_path, capsys):
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(_labels()))
    out_path = tmp_path / "eval.json"

    assert (
        _module().main(
            [
                "--labels",
                str(labels_path),
                "--out",
                str(out_path),
            ]
        )
        == 1
    )

    printed = capsys.readouterr().out
    assert out_path.read_text() == printed
    report = json.loads(printed)
    assert not report["gates"]["green"]
    assert not _checks(report)["foundry.supplied"]["pass"]


def test_main_reports_cross_run_preference_audit(tmp_path, capsys):
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(_labels()), encoding="utf-8")
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(_foundry()), encoding="utf-8")
    preferences_root = tmp_path / "foundry"
    preference.write_jsonl(
        str(preferences_root / "run-1" / "preferences.jsonl"),
        [_audit_pair()],
    )

    assert (
        _module().main(
            [
                "--labels",
                str(labels_path),
                "--foundry-summary",
                str(summary_path),
                "--preferences-root",
                str(preferences_root),
            ]
        )
        == 0
    )

    report = json.loads(capsys.readouterr().out)
    assert report["preferences"]["validated_non_synthetic_pair_count"] == 1
    assert report["preferences"]["category_count"] == 1
    assert not report["preferences"]["tier3_ready"]


def test_evaluate_foundry_summary_bootstraps_slot_rates():
    report = _module().evaluate_foundry_summary(
        {
            "slots": [
                {
                    "blueprint_category": "mechanics",
                    "accepted": 8,
                    "rejected": 1,
                    "escalated": 1,
                },
                {
                    "blueprint_category": "optics_waves",
                    "accepted": 2,
                    "rejected": 0,
                    "escalated": 0,
                },
            ]
        },
        seed=11,
    )

    assert report["candidates"] == 12
    assert report["yield_rate"] == 0.9
    assert report["yield_rate"] == report["yield_rate_ci"]["point"]
    assert report["escalation_rate"] == 0.05
    assert report["escalation_rate"] == report["escalation_rate_ci"]["point"]
    assert report["pooled_yield_rate"] == 10 / 12
    assert report["pooled_escalation_rate"] == 1 / 12
    assert report["ci_unit"] == "slot"
    assert report["slot_count"] == 2
    assert report["category_count"] == 2
    assert report["yield_rate_ci"]["point"] == 0.9
    assert report["escalation_rate_ci"]["point"] == 0.05


def test_foundry_summary_excludes_empty_slots_from_rate_samples():
    report = _module().evaluate_foundry_summary(
        {
            "slots": [
                {
                    "blueprint_category": "mechanics",
                    "accepted": 8,
                    "rejected": 2,
                    "escalated": 0,
                },
                {
                    "blueprint_category": "quantum",
                    "accepted": 2,
                    "rejected": 0,
                    "escalated": 0,
                },
                {
                    "blueprint_category": "lab",
                    "accepted": 0,
                    "rejected": 0,
                    "escalated": 0,
                },
            ]
        }
    )

    assert report["slot_count"] == 3
    assert report["ci_slot_count"] == 2
    assert report["slots"][2]["yield_rate"] is None
    assert report["yield_rate"] == 0.9
    assert report["yield_rate_ci"]["point"] == 0.9


@pytest.mark.parametrize("category", ["optics", "Mechanics", " mechanics"])
def test_foundry_summary_rejects_category_variants(category):
    with pytest.raises(ValueError, match="blueprint_category"):
        _module().evaluate_foundry_summary(
            {
                "slots": [
                    {
                        "blueprint_category": category,
                        "accepted": 1,
                        "rejected": 0,
                        "escalated": 0,
                    }
                ]
            }
        )


def test_single_slot_foundry_has_null_intervals_and_red_support_gate():
    labels = _labels()
    foundry = {
        "slots": [
            {
                "blueprint_category": "mechanics",
                "accepted": 9,
                "rejected": 0,
                "escalated": 1,
            }
        ]
    }

    report = _module().evaluate_labels(labels, foundry_summary=foundry)

    assert report["foundry"]["ci_unit"] == "slot"
    assert report["foundry"]["yield_rate_ci"] is None
    assert report["foundry"]["escalation_rate_ci"] is None
    assert not _checks(report)["foundry.slot_support"]["pass"]
    assert not report["gates"]["green"]


def test_legacy_foundry_reports_points_without_candidate_independent_ci():
    report = _module().evaluate_foundry_summary(
        {"accepted": 8, "rejected": 1, "escalated": 1}
    )

    assert report["yield_rate"] == 0.8
    assert report["escalation_rate"] == 0.1
    assert report["yield_rate_ci"] is None
    assert report["escalation_rate_ci"] is None
    assert report["ci_unit"] is None
    assert report["category_count"] is None


def test_load_foundry_summary_directory_builds_multi_slot_input(tmp_path):
    for index, category in enumerate(_CATEGORIES[:6]):
        run = tmp_path / f"run-{index}"
        run.mkdir()
        (run / "summary.json").write_text(
            json.dumps(
                {
                    "blueprint_category": category,
                    "accepted": 19,
                    "rejected": 0,
                    "escalated": 1,
                }
            ),
            encoding="utf-8",
        )

    payload = _module().load_foundry_summary(tmp_path)
    report = _module().evaluate_labels(_labels(), foundry_summary=payload)

    assert len(payload["slots"]) == 6
    assert report["foundry"]["category_count"] == 6
    assert report["gates"]["green"]


def test_load_foundry_summary_directory_rejects_missing_category(tmp_path):
    run = tmp_path / "run-1"
    run.mkdir()
    (run / "summary.json").write_text(
        json.dumps({"accepted": 1, "rejected": 0, "escalated": 0}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="blueprint_category"):
        _module().load_foundry_summary(tmp_path)


@pytest.mark.parametrize(
    "summary",
    [
        {"accepted": 0, "rejected": 0, "escalated": 0},
        {
            "slots": [
                {
                    "blueprint_category": "mechanics",
                    "accepted": 0,
                    "rejected": 0,
                    "escalated": 0,
                },
                {
                    "blueprint_category": "optics_waves",
                    "accepted": 0,
                    "rejected": 0,
                    "escalated": 0,
                },
            ]
        },
    ],
)
def test_zero_candidate_foundry_rates_are_null(summary):
    report = _module().evaluate_foundry_summary(summary)

    assert report["yield_rate"] is None
    assert report["escalation_rate"] is None
    assert report["yield_rate_ci"] is None
    assert report["escalation_rate_ci"] is None


def test_self_check_prints_offline_card_and_yield(capsys):
    assert _module().main(["--self-check"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["calibration"]["properties"][0]["raw_agreement_ci"]["point"] > 0
    assert report["heldout"]["consistency"] >= 0.9
    assert report["foundry"]["candidates"] > 0
    assert report["foundry"]["yield_rate_ci"]["point"] > 0
    assert report["gates"]["green"]
