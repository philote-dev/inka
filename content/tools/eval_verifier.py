# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Evaluate precomputed verifier predictions against human labels, offline.

The labels file contains a ``properties`` object. Each property supplies aligned
``predicted`` and ``human`` boolean lists, plus optional ``confidence`` values
and optional perturbation ``runs``. This command only reads saved predictions.
It never creates clients or invokes models.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

import eval_metrics  # noqa: E402
from pgrep.ai import agreement  # type: ignore[import-not-found]  # noqa: E402

BOOTSTRAP_SEED = 0
TARGET_PRECISION = 0.95


@dataclass(frozen=True)
class _PropertyLabels:
    predicted: list[bool]
    human: list[bool]
    confidence: list[float] | None
    runs: list[list[bool]]


def _bool_list(value: object, path: str) -> list[bool]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} must be a non-empty boolean array")
    if any(type(item) is not bool for item in value):
        raise ValueError(f"{path} must contain only booleans")
    return list(value)


def _confidence_list(value: object, path: str, expected: int) -> list[float]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a numeric array")
    if len(value) != expected:
        raise ValueError(f"{path} must have length {expected}")
    confidences: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{path} must contain only numbers")
        confidence = float(item)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError(f"{path} values must be finite and between 0 and 1")
        confidences.append(confidence)
    return confidences


def _validate_property(name: str, value: object) -> _PropertyLabels:
    path = f"properties.{name}"
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    if "predicted" not in value or "human" not in value:
        raise ValueError(f"{path} must define predicted and human")
    predicted = _bool_list(value["predicted"], f"{path}.predicted")
    human = _bool_list(value["human"], f"{path}.human")
    if len(predicted) != len(human):
        raise ValueError(f"{path}.predicted and human must have equal lengths")

    confidence = None
    if "confidence" in value:
        confidence = _confidence_list(
            value["confidence"], f"{path}.confidence", len(predicted)
        )

    if "runs" not in value:
        runs = [predicted]
    else:
        raw_runs = value["runs"]
        if not isinstance(raw_runs, list) or not raw_runs:
            raise ValueError(f"{path}.runs must be a non-empty array of boolean arrays")
        runs = []
        for index, raw_run in enumerate(raw_runs):
            run = _bool_list(raw_run, f"{path}.runs[{index}]")
            if len(run) != len(predicted):
                raise ValueError(
                    f"{path}.runs[{index}] must have length {len(predicted)}"
                )
            runs.append(run)

    return _PropertyLabels(predicted, human, confidence, runs)


def _validated_labels(payload: object) -> dict[str, _PropertyLabels]:
    if not isinstance(payload, dict):
        raise ValueError("labels must be an object")
    properties = payload.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("labels.properties must be a non-empty object")
    validated: dict[str, _PropertyLabels] = {}
    for name, value in sorted(properties.items()):
        if not isinstance(name, str) or not name:
            raise ValueError("labels.properties keys must be non-empty strings")
        validated[name] = _validate_property(name, value)
    return validated


def _interval(values: list[float], seed: int) -> dict[str, float]:
    return eval_metrics.bootstrap_ci(values, seed=seed).as_dict()


def _json_number(value: float) -> float | None:
    return value if math.isfinite(value) else None


def evaluate_labels(payload: object, *, seed: int = BOOTSTRAP_SEED) -> dict:
    """Build a calibration card from aligned, precomputed property labels."""
    labels = _validated_labels(payload)
    reports: list[agreement.PropertyReport] = []
    thresholds: dict[str, float] = {}
    additions: dict[str, dict] = {}
    consistency_values: list[float] = []

    for name, item in labels.items():
        reports.append(agreement.property_report(name, item.predicted, item.human))
        consistency = agreement.consistency_score(item.runs)
        consistency_values.append(consistency)
        raw_matches = [
            float(predicted == human)
            for predicted, human in zip(item.predicted, item.human)
        ]
        accepted_labels = [
            float(human)
            for predicted, human in zip(item.predicted, item.human)
            if predicted
        ]
        additions[name] = {
            "consistency": consistency,
            "raw_agreement_ci": _interval(raw_matches, seed),
            "accepted_precision_ci": (
                _interval(accepted_labels, seed) if accepted_labels else None
            ),
        }
        if item.confidence is not None:
            correct = [
                predicted == human
                for predicted, human in zip(item.predicted, item.human)
            ]
            thresholds[name] = agreement.tune_threshold(
                item.confidence,
                correct,
                target_precision=TARGET_PRECISION,
            )

    card = agreement.build_card(
        reports,
        consistency=sum(consistency_values) / len(consistency_values),
        thresholds=thresholds,
    )
    for property_report in card["properties"]:
        for metric in ("raw_agreement", "balanced_accuracy", "precision", "recall"):
            property_report[metric] = _json_number(property_report[metric])
        property_report.update(additions[property_report["name"]])
    return card


def _count(value: object, path: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{path} must be a non-negative integer")
    return value


def evaluate_foundry_summary(
    payload: object, *, seed: int = BOOTSTRAP_SEED
) -> dict:
    """Add rates and bootstrap intervals to one saved foundry summary."""
    if not isinstance(payload, dict):
        raise ValueError("foundry summary must be an object")
    counts = {
        name: _count(payload.get(name), f"foundry summary.{name}")
        for name in ("accepted", "rejected", "escalated")
    }
    partition_total = sum(counts.values())
    candidates = (
        _count(payload["candidates"], "foundry summary.candidates")
        if "candidates" in payload
        else partition_total
    )
    if candidates != partition_total:
        raise ValueError(
            "foundry summary.candidates must equal accepted + rejected + escalated"
        )

    if candidates:
        yield_values = [1.0] * counts["accepted"] + [0.0] * (
            candidates - counts["accepted"]
        )
        escalation_values = [1.0] * counts["escalated"] + [0.0] * (
            candidates - counts["escalated"]
        )
        yield_rate = counts["accepted"] / candidates
        escalation_rate = counts["escalated"] / candidates
        yield_ci = _interval(yield_values, seed)
        escalation_ci = _interval(escalation_values, seed)
    else:
        yield_rate = escalation_rate = 0.0
        yield_ci = escalation_ci = None

    return {
        "candidates": candidates,
        **counts,
        "yield_rate": yield_rate,
        "escalation_rate": escalation_rate,
        "yield_rate_ci": yield_ci,
        "escalation_rate_ci": escalation_ci,
    }


def _load_json(path: str, description: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf8"))
    except OSError as err:
        raise ValueError(f"could not read {description} {path}: {err}") from err
    except json.JSONDecodeError as err:
        raise ValueError(f"{description} {path} is not valid JSON: {err}") from err


def _self_check() -> dict:
    report = evaluate_labels(
        {
            "properties": {
                "key": {
                    "predicted": [True, False, True, False],
                    "human": [True, False, False, False],
                    "confidence": [0.9, 0.8, 0.7, 0.6],
                    "runs": [
                        [True, False, True, False],
                        [True, False, False, False],
                    ],
                }
            }
        }
    )
    report["foundry"] = evaluate_foundry_summary(
        {"accepted": 2, "rejected": 1, "escalated": 1}
    )
    assert report["properties"][0]["raw_agreement_ci"]["point"] == 0.75
    assert report["properties"][0]["accepted_precision_ci"]["point"] == 0.5
    assert report["foundry"]["yield_rate_ci"]["point"] == 0.5
    assert report["foundry"]["escalation_rate"] == 0.25
    return report


def _emit(report: dict, out: str | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    print(rendered)
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate saved verifier predictions against human labels."
    )
    parser.add_argument("--labels", help="precomputed predictions and human labels JSON")
    parser.add_argument(
        "--foundry-summary",
        help="optional foundry summary.json to add yield confidence intervals",
    )
    parser.add_argument("--out", help="optional path for the printed JSON report")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run an entirely offline synthetic evaluation",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        report = _self_check()
    else:
        if not args.labels:
            parser.error("--labels is required unless --self-check is given")
        try:
            report = evaluate_labels(_load_json(args.labels, "labels"))
            if args.foundry_summary:
                report["foundry"] = evaluate_foundry_summary(
                    _load_json(args.foundry_summary, "foundry summary")
                )
        except ValueError as err:
            parser.error(str(err))

    _emit(report, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
