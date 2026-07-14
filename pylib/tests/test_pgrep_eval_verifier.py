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


def _module():
    return importlib.import_module("eval_verifier")


def _property() -> dict:
    return {
        "predicted": [True, True, False, False],
        "human": [True, True, False, False],
        "confidence": [0.95, 0.9, 0.4, 0.3],
        "runs": [
            [True, True, False, False],
            [True, True, False, False],
        ],
    }


def _labels() -> dict:
    return {
        split: {
            "properties": {
                "key": copy.deepcopy(_property()),
                "figure": copy.deepcopy(_property()),
            }
        }
        for split in ("calibration", "heldout")
    }


def _foundry() -> dict:
    return {
        "slots": [
            {
                "blueprint_category": "mechanics",
                "accepted": 9,
                "rejected": 0,
                "escalated": 1,
            },
            {
                "blueprint_category": "optics",
                "accepted": 9,
                "rejected": 0,
                "escalated": 1,
            },
        ]
    }


def _checks(report: dict) -> dict[str, dict]:
    return {check["name"]: check for check in report["gates"]["checks"]}


def test_evaluate_labels_requires_explicit_calibration_and_heldout_splits():
    with pytest.raises(ValueError, match="calibration"):
        _module().evaluate_labels({"properties": {"key": _property()}})


def test_heldout_split_rejects_item_text_fields():
    labels = _labels()
    labels["heldout"]["properties"]["key"]["item_text"] = "private item text"

    with pytest.raises(ValueError, match=r"heldout\.properties\.key.*item_text"):
        _module().evaluate_labels(labels)


def test_evaluate_labels_returns_split_reports_and_threshold_diagnostics():
    report = _module().evaluate_labels(
        _labels(), foundry_summary=_foundry(), seed=17
    )

    calibration = {
        item["name"]: item for item in report["calibration"]["properties"]
    }
    heldout = {item["name"]: item for item in report["heldout"]["properties"]}
    assert calibration["key"]["raw_agreement"] == 1.0
    assert calibration["key"]["consistency"] == 1.0
    assert heldout["key"]["accepted_precision"] == 1.0
    assert heldout["key"]["accepted"] == 2
    assert report["calibration"]["consistency"] == 1.0
    assert report["heldout"]["consistency"] == 1.0

    assert report["thresholds"]["key"] == {
        "target_precision": 0.95,
        "attainable": True,
        "cutoff": 0.9,
        "achieved_precision": 1.0,
        "retained": 2,
        "eligible": 2,
    }
    assert report["gates"]["green"]
    assert all(
        {"observed", "required", "pass", "evidence"} <= check.keys()
        for check in report["gates"]["checks"]
    )


def test_heldout_changes_cannot_change_fitted_thresholds():
    labels = _labels()
    baseline = _module().evaluate_labels(labels)["thresholds"]
    adversarial = copy.deepcopy(labels)
    adversarial["heldout"]["properties"]["key"]["human"] = [
        False,
        False,
        True,
        True,
    ]
    adversarial["heldout"]["properties"]["key"]["confidence"] = [
        0.01,
        0.02,
        1.0,
        0.99,
    ]
    adversarial["heldout"]["properties"]["figure"]["human"] = [
        False,
        True,
        True,
        False,
    ]
    adversarial["heldout"]["properties"]["figure"]["confidence"] = [
        1.0,
        1.0,
        1.0,
        1.0,
    ]

    changed = _module().evaluate_labels(adversarial)["thresholds"]

    assert changed == baseline


def test_threshold_unattainable_when_confidence_one_accept_is_false():
    labels = _labels()
    labels["calibration"]["properties"]["key"].update(
        {
            "predicted": [True, True, False, False],
            "human": [False, True, False, False],
            "confidence": [1.0, 0.9, 0.4, 0.3],
        }
    )

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())

    assert report["thresholds"]["key"] == {
        "target_precision": 0.95,
        "attainable": False,
        "cutoff": None,
        "achieved_precision": 0.0,
        "retained": 1,
        "eligible": 2,
    }
    assert not report["gates"]["green"]
    assert not _checks(report)["calibration.key.threshold_attainable"]["pass"]


def test_threshold_diagnostics_expose_tiny_support():
    labels = _labels()
    labels["calibration"]["properties"]["key"].update(
        {
            "predicted": [True, False],
            "human": [True, False],
            "confidence": [0.73, 0.1],
            "runs": [[True, False], [True, False]],
        }
    )
    labels["heldout"]["properties"]["key"].update(
        {
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
    labels["calibration"]["properties"]["key"]["confidence"] = [
        0.8,
        0.8,
        0.4,
        0.3,
    ]
    labels["heldout"]["properties"]["key"].update(
        {
            "predicted": [True, True, False, False],
            "human": [True, False, False, False],
            "confidence": [0.9, 0.7, 0.4, 0.3],
        }
    )

    report = _module().evaluate_labels(labels)
    key = {
        item["name"]: item for item in report["heldout"]["properties"]
    }["key"]

    assert report["thresholds"]["key"]["cutoff"] == 0.8
    assert key["eligible"] == 2
    assert key["accepted"] == 1
    assert key["accepted_precision"] == 1.0


def test_consistency_includes_original_verdicts():
    labels = _labels()
    labels["heldout"]["properties"]["key"].update(
        {
            "predicted": [True, False],
            "human": [True, False],
            "confidence": [0.9, 0.2],
            "runs": [[False, True], [False, True]],
        }
    )

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())
    key = {
        item["name"]: item for item in report["heldout"]["properties"]
    }["key"]

    assert key["consistency"] == 0.0
    assert not _checks(report)["heldout.key.consistency"]["pass"]


def test_missing_consistency_evidence_forces_red_gate():
    labels = _labels()
    del labels["heldout"]["properties"]["figure"]["runs"]

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())

    check = _checks(report)["heldout.figure.consistency"]
    assert check["observed"] is None
    assert check["evidence"] == "missing perturbation runs"
    assert not check["pass"]
    assert not report["gates"]["green"]


def test_key_and_figure_are_required_for_green_gate():
    labels = _labels()
    del labels["calibration"]["properties"]["figure"]
    del labels["heldout"]["properties"]["figure"]

    report = _module().evaluate_labels(labels, foundry_summary=_foundry())

    assert not _checks(report)["required_property.figure"]["pass"]
    assert not report["gates"]["green"]


def test_standing_gate_uses_design_thresholds_for_every_property():
    labels = _labels()
    labels["calibration"]["properties"]["distractor"] = copy.deepcopy(_property())
    labels["heldout"]["properties"]["distractor"] = {
        "predicted": [False, False, False, False],
        "human": [True, False, False, False],
        "confidence": [0.9, 0.8, 0.7, 0.6],
        "runs": [
            [False, False, False, False],
            [False, False, False, False],
        ],
    }
    labels["heldout"]["properties"]["key"]["human"] = [
        True,
        False,
        False,
        False,
    ]
    foundry = _foundry()
    for slot in foundry["slots"]:
        slot.update(accepted=8, rejected=0, escalated=2)

    report = _module().evaluate_labels(labels, foundry_summary=foundry)
    checks = _checks(report)

    assert checks["heldout.distractor.raw_agreement"]["required"] == 0.9
    assert not checks["heldout.distractor.raw_agreement"]["pass"]
    assert checks["heldout.distractor.balanced_accuracy"]["required"] == 0.85
    assert not checks["heldout.distractor.balanced_accuracy"]["pass"]
    assert checks["heldout.key.accepted_precision"]["required"] == 0.95
    assert not checks["heldout.key.accepted_precision"]["pass"]
    assert checks["foundry.escalation_rate"]["required"] == 0.15
    assert not checks["foundry.escalation_rate"]["pass"]
    assert not report["gates"]["green"]


def test_main_rejects_mismatched_label_lengths(tmp_path, capsys):
    labels_path = tmp_path / "labels.json"
    labels = _labels()
    labels["heldout"]["properties"]["key"]["human"] = [True]
    labels_path.write_text(
        json.dumps(labels)
    )

    with pytest.raises(SystemExit) as exc:
        _module().main(["--labels", str(labels_path)])

    assert exc.value.code == 2
    assert "predicted and human must have equal lengths" in capsys.readouterr().err


def test_main_rejects_a_single_perturbation_run(tmp_path, capsys):
    labels_path = tmp_path / "labels.json"
    labels = _labels()
    labels["heldout"]["properties"]["key"]["runs"] = [
        [True, True, False, False]
    ]
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


def test_structurally_valid_red_main_writes_report_and_exits_nonzero(
    tmp_path, capsys
):
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(_labels()))
    out_path = tmp_path / "eval.json"

    assert _module().main(
        [
            "--labels",
            str(labels_path),
            "--out",
            str(out_path),
        ]
    ) == 1

    printed = capsys.readouterr().out
    assert out_path.read_text() == printed
    report = json.loads(printed)
    assert not report["gates"]["green"]
    assert not _checks(report)["foundry.supplied"]["pass"]


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
                    "blueprint_category": "optics",
                    "accepted": 2,
                    "rejected": 0,
                    "escalated": 0,
                },
            ]
        },
        seed=11,
    )

    assert report["candidates"] == 12
    assert report["yield_rate"] == 10 / 12
    assert report["escalation_rate"] == 1 / 12
    assert report["ci_unit"] == "slot"
    assert report["slot_count"] == 2
    assert report["category_count"] == 2
    assert report["yield_rate_ci"]["point"] == 0.9
    assert report["escalation_rate_ci"]["point"] == 0.05


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
    assert not _checks(report)["foundry.cluster_support"]["pass"]
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
                    "blueprint_category": "optics",
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
