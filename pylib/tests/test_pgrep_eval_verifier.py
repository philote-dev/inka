# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

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


def _labels() -> dict:
    return {
        "properties": {
            "key": {
                "predicted": [True, False, True, False],
                "human": [True, False, False, False],
                "confidence": [0.9, 0.8, 0.7, 0.6],
                "runs": [
                    [True, False, True, False],
                    [True, False, False, False],
                ],
            },
            "figure": {
                "predicted": [False, False],
                "human": [False, True],
            },
        }
    }


def test_evaluate_labels_builds_card_with_bootstrap_confidence_intervals():
    card = _module().evaluate_labels(_labels(), seed=17)

    properties = {item["name"]: item for item in card["properties"]}
    key = properties["key"]
    assert key["raw_agreement"] == 0.75
    assert key["raw_agreement_ci"]["point"] == 0.75
    assert key["raw_agreement_ci"]["low"] <= 0.75 <= key["raw_agreement_ci"]["high"]
    assert key["accepted_precision_ci"]["point"] == 0.5
    assert key["consistency"] == 0.75
    assert card["thresholds"] == {"key": 0.8}

    figure = properties["figure"]
    assert figure["accepted_precision_ci"] is None
    assert figure["consistency"] == 1.0
    assert card["consistency"] == 0.875


def test_main_rejects_mismatched_label_lengths(tmp_path, capsys):
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(
        json.dumps(
            {
                "properties": {
                    "key": {
                        "predicted": [True, False],
                        "human": [True],
                    }
                }
            }
        )
    )

    with pytest.raises(SystemExit) as exc:
        _module().main(["--labels", str(labels_path)])

    assert exc.value.code == 2
    assert "predicted and human must have equal lengths" in capsys.readouterr().err


def test_main_adds_foundry_summary_and_writes_printed_json(tmp_path, capsys):
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(_labels()))
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps({"accepted": 1, "rejected": 2, "escalated": 1}))
    out_path = tmp_path / "eval.json"

    assert (
        _module().main(
            [
                "--labels",
                str(labels_path),
                "--foundry-summary",
                str(summary_path),
                "--out",
                str(out_path),
            ]
        )
        == 0
    )

    printed = capsys.readouterr().out
    assert out_path.read_text() == printed
    report = json.loads(printed)
    foundry = report["foundry"]
    assert foundry["candidates"] == 4
    assert foundry["accepted"] == 1
    assert foundry["rejected"] == 2
    assert foundry["escalated"] == 1
    assert foundry["yield_rate"] == 0.25
    assert foundry["escalation_rate"] == 0.25
    assert foundry["yield_rate_ci"]["point"] == 0.25
    assert foundry["escalation_rate_ci"]["point"] == 0.25


def test_self_check_prints_offline_card_and_yield(capsys):
    assert _module().main(["--self-check"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["properties"][0]["raw_agreement_ci"]["point"] > 0
    assert report["consistency"] > 0
    assert report["foundry"]["candidates"] > 0
    assert report["foundry"]["yield_rate_ci"]["point"] > 0
