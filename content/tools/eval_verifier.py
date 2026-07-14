# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Evaluate saved verifier labels with calibration isolated from held-out data.

The input contains explicit ``calibration`` and ``heldout`` splits. Held-out
records contain only labels and numeric confidences. They are evaluation-only
and never enter prompts, generation, or preference data. This command never
constructs clients or invokes models.
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
RAW_AGREEMENT_GATE = 0.90
BALANCED_ACCURACY_GATE = 0.85
CONSISTENCY_GATE = 0.90
ESCALATION_RATE_GATE = 0.15
CORE_PROPERTIES = ("key", "figure")
_PROPERTY_FIELDS = frozenset({"predicted", "human", "confidence", "runs"})


@dataclass(frozen=True)
class _PropertyLabels:
    predicted: list[bool]
    human: list[bool]
    confidence: list[float] | None
    runs: list[list[bool]] | None


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


def _validate_property(split: str, name: str, value: object) -> _PropertyLabels:
    path = f"{split}.properties.{name}"
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    unknown = sorted(set(value) - _PROPERTY_FIELDS)
    if unknown:
        raise ValueError(f"{path} has unsupported fields: {', '.join(unknown)}")
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
        runs = None
    else:
        raw_runs = value["runs"]
        if not isinstance(raw_runs, list) or len(raw_runs) < 2:
            raise ValueError(
                f"{path}.runs must contain at least 2 aligned boolean arrays"
            )
        runs = []
        for index, raw_run in enumerate(raw_runs):
            run = _bool_list(raw_run, f"{path}.runs[{index}]")
            if len(run) != len(predicted):
                raise ValueError(
                    f"{path}.runs[{index}] must have length {len(predicted)}"
                )
            runs.append(run)

    return _PropertyLabels(predicted, human, confidence, runs)


def _validated_split(
    split: str, value: object
) -> dict[str, _PropertyLabels]:
    if not isinstance(value, dict):
        raise ValueError(f"labels.{split} must be an object")
    unknown = sorted(set(value) - {"properties"})
    if unknown:
        raise ValueError(
            f"labels.{split} has unsupported fields: {', '.join(unknown)}"
        )
    properties = value.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError(f"labels.{split}.properties must be a non-empty object")
    validated: dict[str, _PropertyLabels] = {}
    for name, value in sorted(properties.items()):
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"labels.{split}.properties keys must be non-empty strings"
            )
        validated[name] = _validate_property(split, name, value)
    return validated


def _validated_labels(
    payload: object,
) -> tuple[dict[str, _PropertyLabels], dict[str, _PropertyLabels]]:
    if not isinstance(payload, dict):
        raise ValueError("labels must be an object")
    unknown = sorted(set(payload) - {"calibration", "heldout"})
    if unknown:
        raise ValueError(
            "labels must contain only calibration and heldout splits; "
            f"unsupported fields: {', '.join(unknown)}"
        )
    missing = [
        split for split in ("calibration", "heldout") if split not in payload
    ]
    if missing:
        raise ValueError(
            "labels must define explicit calibration and heldout splits; "
            f"missing: {', '.join(missing)}"
        )
    return (
        _validated_split("calibration", payload["calibration"]),
        _validated_split("heldout", payload["heldout"]),
    )


def _interval(values: list[float], seed: int) -> dict[str, float]:
    return eval_metrics.bootstrap_ci(values, seed=seed).as_dict()


def _json_number(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _consistency(item: _PropertyLabels) -> float | None:
    if item.runs is None:
        return None
    return _json_number(
        agreement.consistency_score([item.predicted, *item.runs])
    )


def _base_report(
    name: str, item: _PropertyLabels, *, seed: int
) -> dict:
    report = agreement.property_report(name, item.predicted, item.human).to_dict()
    for metric in ("raw_agreement", "balanced_accuracy", "precision", "recall"):
        report[metric] = _json_number(report[metric])
    raw_matches = [
        float(predicted == human)
        for predicted, human in zip(item.predicted, item.human)
    ]
    predicted_positive_labels = [
        float(human)
        for predicted, human in zip(item.predicted, item.human)
        if predicted
    ]
    report.update(
        {
            "consistency": _consistency(item),
            "raw_agreement_ci": _interval(raw_matches, seed),
            "accepted_precision_ci": (
                _interval(predicted_positive_labels, seed)
                if predicted_positive_labels
                else None
            ),
        }
    )
    return report


def _fit_threshold(item: _PropertyLabels) -> dict:
    eligible_labels = [
        human
        for predicted, human in zip(item.predicted, item.human)
        if predicted
    ]
    diagnostic = {
        "target_precision": TARGET_PRECISION,
        "attainable": False,
        "cutoff": None,
        "achieved_precision": None,
        "retained": 0,
        "eligible": len(eligible_labels),
    }
    if item.confidence is None or not eligible_labels:
        return diagnostic

    eligible_confidences = [
        confidence
        for predicted, confidence in zip(item.predicted, item.confidence)
        if predicted
    ]
    attempted_cutoff = agreement.tune_threshold(
        eligible_confidences,
        eligible_labels,
        target_precision=TARGET_PRECISION,
    )
    retained_labels = [
        human
        for confidence, human in zip(eligible_confidences, eligible_labels)
        if confidence >= attempted_cutoff
    ]
    achieved_precision = (
        sum(retained_labels) / len(retained_labels) if retained_labels else None
    )
    attainable = (
        achieved_precision is not None
        and achieved_precision >= TARGET_PRECISION
    )
    diagnostic.update(
        {
            "attainable": attainable,
            "cutoff": attempted_cutoff if attainable else None,
            "achieved_precision": achieved_precision,
            "retained": len(retained_labels),
        }
    )
    return diagnostic


def _overall_consistency(properties: list[dict]) -> float | None:
    measured = [
        report["consistency"]
        for report in properties
        if report["consistency"] is not None
    ]
    return sum(measured) / len(measured) if measured else None


def _calibration_report(
    labels: dict[str, _PropertyLabels],
    *,
    seed: int,
) -> tuple[dict, dict[str, dict]]:
    properties = [
        _base_report(name, item, seed=seed) for name, item in labels.items()
    ]
    thresholds = {name: _fit_threshold(item) for name, item in labels.items()}
    return {
        "properties": properties,
        "consistency": _overall_consistency(properties),
    }, thresholds


def _heldout_report(
    labels: dict[str, _PropertyLabels],
    thresholds: dict[str, dict],
    *,
    seed: int,
) -> dict:
    properties: list[dict] = []
    for name, item in labels.items():
        report = _base_report(name, item, seed=seed)
        threshold = thresholds.get(name)
        cutoff = threshold.get("cutoff") if threshold else None
        eligible = sum(item.predicted)
        retained_labels: list[bool] = []
        if cutoff is not None and item.confidence is not None:
            retained_labels = [
                human
                for predicted, human, confidence in zip(
                    item.predicted, item.human, item.confidence
                )
                if predicted and confidence >= cutoff
            ]
        accepted_precision = (
            sum(retained_labels) / len(retained_labels)
            if retained_labels
            else None
        )
        report.update(
            {
                "threshold_cutoff": cutoff,
                "eligible": eligible,
                "accepted": len(retained_labels),
                "accepted_precision": accepted_precision,
                "accepted_precision_ci": (
                    _interval([float(value) for value in retained_labels], seed)
                    if retained_labels
                    else None
                ),
            }
        )
        properties.append(report)
    return {
        "properties": properties,
        "consistency": _overall_consistency(properties),
    }


def _count(value: object, path: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{path} must be a non-negative integer")
    return value


def _partition_counts(payload: object, path: str) -> dict[str, int]:
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be an object")
    counts = {
        name: _count(payload.get(name), f"{path}.{name}")
        for name in ("accepted", "rejected", "escalated")
    }
    partition_total = sum(counts.values())
    candidates = (
        _count(payload["candidates"], f"{path}.candidates")
        if "candidates" in payload
        else partition_total
    )
    if candidates != partition_total:
        raise ValueError(
            f"{path}.candidates must equal accepted + rejected + escalated"
        )
    return {"candidates": candidates, **counts}


def _rates(counts: dict[str, int]) -> tuple[float | None, float | None]:
    candidates = counts["candidates"]
    if candidates == 0:
        return None, None
    return (
        counts["accepted"] / candidates,
        counts["escalated"] / candidates,
    )


def evaluate_foundry_summary(
    payload: object, *, seed: int = BOOTSTRAP_SEED
) -> dict:
    """Evaluate aggregate or per-slot foundry counts without item-level claims."""
    if not isinstance(payload, dict):
        raise ValueError("foundry summary must be an object")

    if "slots" not in payload:
        counts = _partition_counts(payload, "foundry summary")
        yield_rate, escalation_rate = _rates(counts)
        return {
            **counts,
            "yield_rate": yield_rate,
            "escalation_rate": escalation_rate,
            "yield_rate_ci": None,
            "escalation_rate_ci": None,
            "ci_unit": None,
            "slot_count": None,
            "ci_slot_count": 0,
            "category_count": None,
        }

    raw_slots = payload["slots"]
    if not isinstance(raw_slots, list):
        raise ValueError("foundry summary.slots must be an array")
    slots: list[dict] = []
    categories: set[str] = set()
    yield_values: list[float] = []
    escalation_values: list[float] = []
    totals = {"candidates": 0, "accepted": 0, "rejected": 0, "escalated": 0}
    for index, raw_slot in enumerate(raw_slots):
        path = f"foundry summary.slots[{index}]"
        if not isinstance(raw_slot, dict):
            raise ValueError(f"{path} must be an object")
        category = raw_slot.get("blueprint_category")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(
                f"{path}.blueprint_category must be a non-empty string"
            )
        counts = _partition_counts(raw_slot, path)
        yield_rate, escalation_rate = _rates(counts)
        if yield_rate is not None and escalation_rate is not None:
            yield_values.append(yield_rate)
            escalation_values.append(escalation_rate)
        categories.add(category)
        for name in totals:
            totals[name] += counts[name]
        slots.append(
            {
                "blueprint_category": category,
                **counts,
                "yield_rate": yield_rate,
                "escalation_rate": escalation_rate,
            }
        )

    for name, expected in totals.items():
        if name in payload and _count(
            payload[name], f"foundry summary.{name}"
        ) != expected:
            raise ValueError(
                f"foundry summary.{name} does not match its slot total"
            )

    yield_rate, escalation_rate = _rates(totals)
    enough_clusters = len(yield_values) >= 2
    return {
        **totals,
        "yield_rate": yield_rate,
        "escalation_rate": escalation_rate,
        "yield_rate_ci": (
            _interval(yield_values, seed) if enough_clusters else None
        ),
        "escalation_rate_ci": (
            _interval(escalation_values, seed) if enough_clusters else None
        ),
        "ci_unit": "slot",
        "slot_count": len(slots),
        "ci_slot_count": len(yield_values),
        "category_count": len(categories),
        "slots": slots,
    }


def _metric_map(report: dict) -> dict[str, dict]:
    return {item["name"]: item for item in report["properties"]}


def _check(
    name: str,
    observed: object,
    required: object,
    passed: bool,
    evidence: object,
) -> dict:
    return {
        "name": name,
        "observed": observed,
        "required": required,
        "pass": passed,
        "evidence": evidence,
    }


def _at_least(value: object, required: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= required


def _standing_gates(
    calibration: dict,
    heldout: dict,
    thresholds: dict[str, dict],
    foundry: dict | None,
) -> dict:
    calibration_properties = _metric_map(calibration)
    heldout_properties = _metric_map(heldout)
    property_names = sorted(
        set(calibration_properties) | set(heldout_properties)
    )
    checks: list[dict] = []

    for name in CORE_PROPERTIES:
        presence = {
            "calibration": name in calibration_properties,
            "heldout": name in heldout_properties,
        }
        checks.append(
            _check(
                f"required_property.{name}",
                presence,
                {"calibration": True, "heldout": True},
                all(presence.values()),
                (
                    "present in both splits"
                    if all(presence.values())
                    else "missing from one or both splits"
                ),
            )
        )

    for name in property_names:
        heldout_property = heldout_properties.get(name)
        for metric, required in (
            ("raw_agreement", RAW_AGREEMENT_GATE),
            ("balanced_accuracy", BALANCED_ACCURACY_GATE),
        ):
            observed = (
                heldout_property.get(metric) if heldout_property else None
            )
            checks.append(
                _check(
                    f"heldout.{name}.{metric}",
                    observed,
                    required,
                    _at_least(observed, required),
                    (
                        f"heldout.properties.{name}.{metric}"
                        if observed is not None
                        else "missing held-out property or metric"
                    ),
                )
            )

        threshold = thresholds.get(name)
        attainable = threshold.get("attainable") if threshold else None
        checks.append(
            _check(
                f"calibration.{name}.threshold_attainable",
                attainable,
                True,
                attainable is True,
                threshold or "missing calibration property",
            )
        )

        consistency = (
            heldout_property.get("consistency")
            if heldout_property
            else None
        )
        checks.append(
            _check(
                f"heldout.{name}.consistency",
                consistency,
                CONSISTENCY_GATE,
                _at_least(consistency, CONSISTENCY_GATE),
                (
                    f"heldout.properties.{name}.consistency"
                    if consistency is not None
                    else "missing perturbation runs"
                ),
            )
        )

    for name in CORE_PROPERTIES:
        heldout_property = heldout_properties.get(name)
        accepted_precision = (
            heldout_property.get("accepted_precision")
            if heldout_property
            else None
        )
        checks.append(
            _check(
                f"heldout.{name}.accepted_precision",
                accepted_precision,
                TARGET_PRECISION,
                _at_least(accepted_precision, TARGET_PRECISION),
                (
                    f"heldout.properties.{name}.accepted_precision"
                    if accepted_precision is not None
                    else "missing fixed-threshold accepted predictions"
                ),
            )
        )

    checks.append(
        _check(
            "foundry.supplied",
            foundry is not None,
            True,
            foundry is not None,
            "foundry summary supplied" if foundry else "missing foundry summary",
        )
    )
    cluster_support = foundry.get("ci_slot_count") if foundry else None
    checks.append(
        _check(
            "foundry.cluster_support",
            cluster_support,
            2,
            isinstance(cluster_support, int) and cluster_support >= 2,
            (
                f"{cluster_support} non-empty slot summaries"
                if cluster_support is not None
                else "missing foundry summary"
            ),
        )
    )
    escalation_rate = foundry.get("escalation_rate") if foundry else None
    checks.append(
        _check(
            "foundry.escalation_rate",
            escalation_rate,
            ESCALATION_RATE_GATE,
            isinstance(escalation_rate, (int, float))
            and not isinstance(escalation_rate, bool)
            and escalation_rate <= ESCALATION_RATE_GATE,
            (
                "foundry.escalation_rate"
                if escalation_rate is not None
                else "missing or zero-candidate foundry rate"
            ),
        )
    )
    return {"green": all(check["pass"] for check in checks), "checks": checks}


def evaluate_labels(
    payload: object,
    *,
    foundry_summary: object | None = None,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Fit on calibration only, then evaluate fixed decisions on held-out labels."""
    calibration_labels, heldout_labels = _validated_labels(payload)
    calibration, thresholds = _calibration_report(
        calibration_labels, seed=seed
    )
    heldout = _heldout_report(heldout_labels, thresholds, seed=seed)
    foundry = (
        evaluate_foundry_summary(foundry_summary, seed=seed)
        if foundry_summary is not None
        else None
    )
    report = {
        "target_precision": TARGET_PRECISION,
        "calibration": calibration,
        "heldout": heldout,
        "thresholds": thresholds,
        "foundry": foundry,
    }
    report["gates"] = _standing_gates(
        calibration, heldout, thresholds, foundry
    )
    return report


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value} is not allowed")


def _load_json(path: str, description: str) -> object:
    try:
        return json.loads(
            Path(path).read_text(encoding="utf8"),
            parse_constant=_reject_json_constant,
        )
    except OSError as err:
        raise ValueError(f"could not read {description} {path}: {err}") from err
    except json.JSONDecodeError as err:
        raise ValueError(f"{description} {path} is not valid JSON: {err}") from err


def _self_check() -> dict:
    def passing_property() -> dict:
        return {
            "predicted": [True, True, False, False],
            "human": [True, True, False, False],
            "confidence": [0.95, 0.9, 0.4, 0.3],
            "runs": [
                [True, True, False, False],
                [True, True, False, False],
            ],
        }

    report = evaluate_labels(
        {
            split: {
                "properties": {
                    "key": passing_property(),
                    "figure": passing_property(),
                }
            }
            for split in ("calibration", "heldout")
        },
        foundry_summary={
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
        },
    )
    assert report["calibration"]["properties"][0]["raw_agreement"] == 1.0
    assert report["heldout"]["properties"][0]["accepted_precision"] == 1.0
    assert report["foundry"]["yield_rate_ci"]["point"] == 0.9
    assert report["foundry"]["escalation_rate"] == 0.1
    assert report["gates"]["green"]
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
        help="foundry summary JSON required for a green standing evaluation",
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
            foundry_summary = (
                _load_json(args.foundry_summary, "foundry summary")
                if args.foundry_summary
                else None
            )
            report = evaluate_labels(
                _load_json(args.labels, "labels"),
                foundry_summary=foundry_summary,
            )
        except ValueError as err:
            parser.error(str(err))

    _emit(report, args.out)
    return 0 if report["gates"]["green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
