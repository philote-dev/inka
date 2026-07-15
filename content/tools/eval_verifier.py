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
from pgrep.ai import agreement, preference  # type: ignore[import-not-found]  # noqa: E402

BOOTSTRAP_SEED = 0
TARGET_PRECISION = 0.95
RAW_AGREEMENT_GATE = 0.90
BALANCED_ACCURACY_GATE = 0.85
CONSISTENCY_GATE = 0.90
ESCALATION_RATE_GATE = 0.15
MIN_ALIGNED_EXAMPLES = 30
MIN_HUMAN_POSITIVES = 5
MIN_HUMAN_NEGATIVES = 5
MIN_RETAINED_ACCEPTS = 20
MIN_CONSISTENCY_ITEMS = 30
MIN_FOUNDRY_SLOTS = 6
MIN_FOUNDRY_CATEGORIES = 6
CORE_PROPERTIES = ("key", "figure")
_PROPERTY_FIELDS = frozenset({"item_ids", "predicted", "human", "confidence", "runs"})


@dataclass(frozen=True)
class _PropertyLabels:
    item_ids: list[str]
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


def _item_id_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} must be a non-empty string array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{path} must contain only non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{path} must contain unique strings")
    return list(value)


def _validate_property(split: str, name: str, value: object) -> _PropertyLabels:
    path = f"{split}.properties.{name}"
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    unknown = sorted(set(value) - _PROPERTY_FIELDS)
    if unknown:
        raise ValueError(f"{path} has unsupported fields: {', '.join(unknown)}")
    if any(field not in value for field in ("item_ids", "predicted", "human")):
        raise ValueError(f"{path} must define item_ids, predicted, and human")
    item_ids = _item_id_list(value["item_ids"], f"{path}.item_ids")
    predicted = _bool_list(value["predicted"], f"{path}.predicted")
    human = _bool_list(value["human"], f"{path}.human")
    if len(predicted) != len(human):
        raise ValueError(f"{path}.predicted and human must have equal lengths")
    if len(item_ids) != len(predicted):
        raise ValueError(f"{path}.item_ids must have length {len(predicted)}")

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

    return _PropertyLabels(item_ids, predicted, human, confidence, runs)


def _validated_split(split: str, value: object) -> dict[str, _PropertyLabels]:
    if not isinstance(value, dict):
        raise ValueError(f"labels.{split} must be an object")
    unknown = sorted(set(value) - {"properties"})
    if unknown:
        raise ValueError(f"labels.{split} has unsupported fields: {', '.join(unknown)}")
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
    missing = [split for split in ("calibration", "heldout") if split not in payload]
    if missing:
        raise ValueError(
            "labels must define explicit calibration and heldout splits; "
            f"missing: {', '.join(missing)}"
        )
    calibration = _validated_split("calibration", payload["calibration"])
    heldout = _validated_split("heldout", payload["heldout"])
    calibration_ids = {
        item_id for labels in calibration.values() for item_id in labels.item_ids
    }
    heldout_ids = {
        item_id for labels in heldout.values() for item_id in labels.item_ids
    }
    overlap = sorted(calibration_ids & heldout_ids)
    if overlap:
        preview = ", ".join(overlap[:5])
        raise ValueError(
            f"calibration and heldout item_ids overlap across properties: {preview}"
        )
    return calibration, heldout


def _interval(values: list[float], seed: int) -> dict[str, float]:
    return eval_metrics.bootstrap_ci(values, seed=seed).as_dict()


def wilson_lower_bound(successes: int, total: int) -> float | None:
    """Deterministic two-sided 95% Wilson lower bound for a binomial rate."""
    if total <= 0 or successes < 0 or successes > total:
        return None
    z = 1.959963984540054
    proportion = successes / total
    z_squared = z * z
    denominator = 1.0 + z_squared / total
    center = proportion + z_squared / (2.0 * total)
    margin = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z_squared / (4.0 * total * total)
    )
    return (center - margin) / denominator


def _json_number(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _consistency(item: _PropertyLabels) -> float | None:
    if item.runs is None:
        return None
    return _json_number(agreement.consistency_score([item.predicted, *item.runs]))


def _label_support(item: _PropertyLabels) -> dict[str, int]:
    positives = sum(item.human)
    return {
        "item_count": len(item.human),
        "human_positives": positives,
        "human_negatives": len(item.human) - positives,
    }


def _prediction_report(
    name: str,
    predictions: list[bool],
    labels: list[bool],
    *,
    seed: int,
) -> dict:
    report = agreement.property_report(name, predictions, labels).to_dict()
    for metric in ("raw_agreement", "balanced_accuracy", "precision", "recall"):
        report[metric] = _json_number(report[metric])
    raw_matches = [
        float(predicted == human) for predicted, human in zip(predictions, labels)
    ]
    predicted_positive_labels = [
        float(human) for predicted, human in zip(predictions, labels) if predicted
    ]
    report.update(
        {
            "raw_agreement_ci": _interval(raw_matches, seed),
            "accepted_precision_ci": (
                _interval(predicted_positive_labels, seed)
                if predicted_positive_labels
                else None
            ),
        }
    )
    return report


def _base_report(name: str, item: _PropertyLabels, *, seed: int) -> dict:
    report = _prediction_report(
        name,
        item.predicted,
        item.human,
        seed=seed,
    )
    report.update(
        {
            "item_count": len(item.item_ids),
            "support": _label_support(item),
            "consistency": _consistency(item),
            "consistency_n": len(item.item_ids) if item.runs is not None else 0,
        }
    )
    return report


def _fit_threshold(item: _PropertyLabels) -> dict:
    eligible_labels = [
        human for predicted, human in zip(item.predicted, item.human) if predicted
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
        achieved_precision is not None and achieved_precision >= TARGET_PRECISION
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
    properties = [_base_report(name, item, seed=seed) for name, item in labels.items()]
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
        pre_threshold = _base_report(name, item, seed=seed)
        threshold = thresholds.get(name)
        cutoff = threshold.get("cutoff") if threshold else None
        eligible = sum(item.predicted)
        post_predictions: list[bool] | None = None
        if cutoff is not None and item.confidence is not None:
            post_predictions = [
                predicted and confidence >= cutoff
                for predicted, confidence in zip(
                    item.predicted,
                    item.confidence,
                )
            ]
        if post_predictions is None:
            report = {
                "name": name,
                "n": len(item.human),
                "raw_agreement": None,
                "balanced_accuracy": None,
                "precision": None,
                "recall": None,
                "raw_agreement_ci": None,
                "accepted_precision_ci": None,
            }
            accepted = 0
            accepted_correct = 0
        else:
            report = _prediction_report(
                name,
                post_predictions,
                item.human,
                seed=seed,
            )
            accepted = sum(post_predictions)
            accepted_correct = sum(
                predicted and human
                for predicted, human in zip(post_predictions, item.human)
            )
        report.update(
            {
                "item_count": len(item.item_ids),
                "support": _label_support(item),
                "consistency": _consistency(item),
                "consistency_n": (len(item.item_ids) if item.runs is not None else 0),
                "pre_threshold": {
                    key: pre_threshold[key]
                    for key in (
                        "raw_agreement",
                        "balanced_accuracy",
                        "precision",
                        "recall",
                        "raw_agreement_ci",
                        "accepted_precision_ci",
                    )
                },
                "threshold_cutoff": cutoff,
                "threshold_attainable": bool(threshold and threshold.get("attainable")),
                "confidence_available": item.confidence is not None,
                "eligible": eligible,
                "accepted": accepted,
                "accepted_precision": report["precision"],
                "accepted_precision_wilson_lower": wilson_lower_bound(
                    accepted_correct,
                    accepted,
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


def evaluate_foundry_summary(payload: object, *, seed: int = BOOTSTRAP_SEED) -> dict:
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
    excluded_synthetic_run_count = (
        _count(
            payload["excluded_synthetic_run_count"],
            "foundry summary.excluded_synthetic_run_count",
        )
        if "excluded_synthetic_run_count" in payload
        else 0
    )
    slots: list[dict] = []
    categories: set[str] = set()
    non_empty_categories: set[str] = set()
    yield_values: list[float] = []
    escalation_values: list[float] = []
    totals = {"candidates": 0, "accepted": 0, "rejected": 0, "escalated": 0}
    for index, raw_slot in enumerate(raw_slots):
        path = f"foundry summary.slots[{index}]"
        if not isinstance(raw_slot, dict):
            raise ValueError(f"{path} must be an object")
        category = raw_slot.get("blueprint_category")
        if (
            not isinstance(category, str)
            or category not in preference.BLUEPRINT_CATEGORIES
        ):
            raise ValueError(
                f"{path}.blueprint_category must be one of the nine locked slugs"
            )
        counts = _partition_counts(raw_slot, path)
        yield_rate, escalation_rate = _rates(counts)
        if yield_rate is not None and escalation_rate is not None:
            yield_values.append(yield_rate)
            escalation_values.append(escalation_rate)
            non_empty_categories.add(category)
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
        if (
            name in payload
            and _count(payload[name], f"foundry summary.{name}") != expected
        ):
            raise ValueError(f"foundry summary.{name} does not match its slot total")

    pooled_yield_rate, pooled_escalation_rate = _rates(totals)
    enough_clusters = len(yield_values) >= 2
    yield_ci = _interval(yield_values, seed) if enough_clusters else None
    escalation_ci = _interval(escalation_values, seed) if enough_clusters else None
    yield_rate = (
        yield_ci["point"]
        if yield_ci is not None
        else (yield_values[0] if yield_values else None)
    )
    escalation_rate = (
        escalation_ci["point"]
        if escalation_ci is not None
        else (escalation_values[0] if escalation_values else None)
    )
    return {
        **totals,
        "yield_rate": yield_rate,
        "escalation_rate": escalation_rate,
        "pooled_yield_rate": pooled_yield_rate,
        "pooled_escalation_rate": pooled_escalation_rate,
        "yield_rate_ci": yield_ci,
        "escalation_rate_ci": escalation_ci,
        "ci_unit": "slot",
        "slot_count": len(slots),
        "non_empty_slot_count": len(yield_values),
        "ci_slot_count": len(yield_values),
        "category_count": len(non_empty_categories),
        "reported_category_count": len(categories),
        "excluded_synthetic_run_count": excluded_synthetic_run_count,
        "slots": slots,
    }


def _metric_map(report: dict) -> dict[str, dict]:
    return {item["name"]: item for item in report["properties"]}


def _check(
    name: str,
    observed: object,
    required: object,
    passed: bool,
    support: object,
    evidence: object,
) -> dict:
    return {
        "name": name,
        "observed": observed,
        "required": required,
        "pass": passed,
        "support": support,
        "evidence": evidence,
    }


def _at_least(value: object, required: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= required
    )


def _sample_support_pass(support: object) -> bool:
    return (
        isinstance(support, dict)
        and support.get("item_count", 0) >= MIN_ALIGNED_EXAMPLES
        and support.get("human_positives", 0) >= MIN_HUMAN_POSITIVES
        and support.get("human_negatives", 0) >= MIN_HUMAN_NEGATIVES
    )


def _standing_gates(
    calibration: dict,
    heldout: dict,
    thresholds: dict[str, dict],
    foundry: dict | None,
) -> dict:
    calibration_properties = _metric_map(calibration)
    heldout_properties = _metric_map(heldout)
    property_names = sorted(set(calibration_properties) | set(heldout_properties))
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
                presence,
                (
                    "present in both splits"
                    if all(presence.values())
                    else "missing from one or both splits"
                ),
            )
        )

    for name in property_names:
        calibration_property = calibration_properties.get(name)
        heldout_property = heldout_properties.get(name)
        for split, property_report in (
            ("calibration", calibration_property),
            ("heldout", heldout_property),
        ):
            support = property_report.get("support") if property_report else None
            checks.append(
                _check(
                    f"{split}.{name}.sample_support",
                    support,
                    {
                        "item_count": MIN_ALIGNED_EXAMPLES,
                        "human_positives": MIN_HUMAN_POSITIVES,
                        "human_negatives": MIN_HUMAN_NEGATIVES,
                    },
                    _sample_support_pass(support),
                    support,
                    (
                        f"{split}.properties.{name}.support"
                        if support is not None
                        else f"missing {split} property"
                    ),
                )
            )

        heldout_support = heldout_property.get("support") if heldout_property else None
        for metric, required in (
            ("raw_agreement", RAW_AGREEMENT_GATE),
            ("balanced_accuracy", BALANCED_ACCURACY_GATE),
        ):
            observed = heldout_property.get(metric) if heldout_property else None
            checks.append(
                _check(
                    f"heldout.{name}.{metric}",
                    observed,
                    required,
                    _at_least(observed, required)
                    and _sample_support_pass(heldout_support),
                    heldout_support,
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
                threshold,
                threshold or "missing calibration property",
            )
        )

        confidence_available = (
            heldout_property.get("confidence_available") if heldout_property else None
        )
        checks.append(
            _check(
                f"heldout.{name}.confidence_available",
                confidence_available,
                True,
                confidence_available is True,
                heldout_support,
                (
                    f"heldout.properties.{name}.confidence"
                    if confidence_available
                    else "missing held-out confidence or property"
                ),
            )
        )

        consistency = heldout_property.get("consistency") if heldout_property else None
        consistency_n = heldout_property.get("consistency_n") if heldout_property else 0
        checks.append(
            _check(
                f"heldout.{name}.consistency",
                {"point": consistency, "items": consistency_n},
                {
                    "point": CONSISTENCY_GATE,
                    "items": MIN_CONSISTENCY_ITEMS,
                },
                _at_least(consistency, CONSISTENCY_GATE)
                and isinstance(consistency_n, int)
                and consistency_n >= MIN_CONSISTENCY_ITEMS,
                {"consistency_items": consistency_n},
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
            heldout_property.get("accepted_precision") if heldout_property else None
        )
        accepted_ci = (
            heldout_property.get("accepted_precision_ci") if heldout_property else None
        )
        retained = heldout_property.get("accepted") if heldout_property else 0
        wilson_low = (
            heldout_property.get("accepted_precision_wilson_lower")
            if heldout_property
            else None
        )
        checks.append(
            _check(
                f"heldout.{name}.retained_accepts",
                retained,
                MIN_RETAINED_ACCEPTS,
                isinstance(retained, int) and retained >= MIN_RETAINED_ACCEPTS,
                {"retained": retained},
                (
                    f"heldout.properties.{name}.accepted"
                    if heldout_property
                    else "missing held-out property"
                ),
            )
        )
        ci_low = accepted_ci.get("low") if accepted_ci else None
        checks.append(
            _check(
                f"heldout.{name}.accepted_precision",
                {
                    "point": accepted_precision,
                    "ci_low": ci_low,
                    "wilson_low": wilson_low,
                },
                {
                    "point": TARGET_PRECISION,
                    "ci_low": TARGET_PRECISION,
                    "wilson_low": TARGET_PRECISION,
                },
                _at_least(accepted_precision, TARGET_PRECISION)
                and _at_least(ci_low, TARGET_PRECISION)
                and _at_least(wilson_low, TARGET_PRECISION)
                and isinstance(retained, int)
                and retained >= MIN_RETAINED_ACCEPTS,
                {
                    "retained": retained,
                    "interval": accepted_ci,
                    "wilson_lower": wilson_low,
                },
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
            foundry,
            "foundry summary supplied" if foundry else "missing foundry summary",
        )
    )
    cluster_support = foundry.get("non_empty_slot_count") if foundry else None
    checks.append(
        _check(
            "foundry.slot_support",
            cluster_support,
            MIN_FOUNDRY_SLOTS,
            isinstance(cluster_support, int)
            and cluster_support >= MIN_FOUNDRY_SLOTS
            and foundry is not None
            and foundry.get("ci_unit") == "slot",
            {
                "non_empty_slots": cluster_support,
                "ci_unit": foundry.get("ci_unit") if foundry else None,
            },
            (
                f"{cluster_support} non-empty slot summaries"
                if cluster_support is not None
                else "missing foundry summary"
            ),
        )
    )
    category_support = foundry.get("category_count") if foundry else None
    checks.append(
        _check(
            "foundry.category_support",
            category_support,
            MIN_FOUNDRY_CATEGORIES,
            isinstance(category_support, int)
            and category_support >= MIN_FOUNDRY_CATEGORIES,
            {"valid_non_empty_categories": category_support},
            (
                "foundry.category_count"
                if category_support is not None
                else "missing foundry category evidence"
            ),
        )
    )
    escalation_rate = foundry.get("escalation_rate") if foundry else None
    escalation_ci = foundry.get("escalation_rate_ci") if foundry else None
    escalation_ci_high = escalation_ci.get("high") if escalation_ci else None
    checks.append(
        _check(
            "foundry.escalation_rate",
            {"point": escalation_rate, "ci_high": escalation_ci_high},
            {
                "point_max": ESCALATION_RATE_GATE,
                "ci_high_max": ESCALATION_RATE_GATE,
            },
            isinstance(escalation_rate, (int, float))
            and not isinstance(escalation_rate, bool)
            and escalation_rate <= ESCALATION_RATE_GATE
            and isinstance(escalation_ci_high, (int, float))
            and escalation_ci_high <= ESCALATION_RATE_GATE,
            {
                "non_empty_slots": cluster_support,
                "interval": escalation_ci,
            },
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
    preference_audit: dict | None = None,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Fit on calibration only, then evaluate fixed decisions on held-out labels."""
    calibration_labels, heldout_labels = _validated_labels(payload)
    calibration, thresholds = _calibration_report(calibration_labels, seed=seed)
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
        "preferences": preference_audit,
    }
    report["gates"] = _standing_gates(calibration, heldout, thresholds, foundry)
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


def load_foundry_summary(path: str | Path) -> object:
    """Load one summary JSON or aggregate every run summary below a root."""
    source = Path(path)
    if not source.is_dir():
        return _load_json(str(source), "foundry summary")

    run_dirs = preference.finalized_run_directories(source)
    if not run_dirs:
        raise ValueError(f"foundry root {source} has no finalized runs")
    slots: list[dict] = []
    excluded_synthetic = 0
    for run_dir in run_dirs:
        summary_path = run_dir / "summary.json"
        if not summary_path.is_file():
            raise ValueError(f"finalized foundry run {run_dir} has no summary.json")
        payload = _load_json(str(summary_path), "foundry summary")
        if not isinstance(payload, dict):
            raise ValueError(f"foundry summary {summary_path} must be an object")
        synthetic = payload.get("synthetic")
        if type(synthetic) is not bool:
            raise ValueError(
                f"foundry summary {summary_path}.synthetic must be a boolean"
            )
        if synthetic:
            excluded_synthetic += 1
            continue
        category = payload.get("blueprint_category")
        if (
            not isinstance(category, str)
            or category not in preference.BLUEPRINT_CATEGORIES
        ):
            raise ValueError(
                f"foundry summary {summary_path}.blueprint_category "
                "must be one of the nine locked slugs"
            )
        counts = _partition_counts(payload, f"foundry summary {summary_path}")
        slots.append({"blueprint_category": category, **counts})
    return {
        "slots": slots,
        "included_run_count": len(slots),
        "excluded_synthetic_run_count": excluded_synthetic,
    }


def _self_check() -> dict:
    def passing_property(prefix: str) -> dict:
        predicted = [True] * 110 + [False] * 10
        return {
            "item_ids": [f"{prefix}-{index}" for index in range(120)],
            "predicted": predicted,
            "human": list(predicted),
            "confidence": [0.95] * 110 + [0.2] * 10,
            "runs": [
                list(predicted),
                list(predicted),
            ],
        }

    categories = [
        "mechanics",
        "electromagnetism",
        "quantum",
        "thermodynamics",
        "atomic",
        "optics_waves",
    ]
    report = evaluate_labels(
        {
            split: {
                "properties": {
                    "key": passing_property(f"{split}-key"),
                    "figure": passing_property(f"{split}-figure"),
                }
            }
            for split in ("calibration", "heldout")
        },
        foundry_summary={
            "slots": [
                {
                    "blueprint_category": category,
                    "accepted": 19,
                    "rejected": 0,
                    "escalated": 1,
                }
                for category in categories
            ]
        },
    )
    assert report["calibration"]["properties"][0]["raw_agreement"] == 1.0
    assert report["heldout"]["properties"][0]["accepted_precision"] == 1.0
    assert (
        report["foundry"]["yield_rate"] == report["foundry"]["yield_rate_ci"]["point"]
    )
    assert (
        report["foundry"]["escalation_rate"]
        == report["foundry"]["escalation_rate_ci"]["point"]
    )
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
    parser.add_argument(
        "--labels", help="precomputed predictions and human labels JSON"
    )
    parser.add_argument(
        "--foundry-summary",
        help=(
            "single foundry summary JSON or foundry root directory "
            "required for a green standing evaluation"
        ),
    )
    parser.add_argument(
        "--preferences-root",
        help="optional foundry root for cross-run Tier 3 preference audit",
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
                load_foundry_summary(args.foundry_summary)
                if args.foundry_summary
                else None
            )
            preference_audit = (
                preference.audit_preferences(args.preferences_root)
                if args.preferences_root
                else None
            )
            report = evaluate_labels(
                _load_json(args.labels, "labels"),
                foundry_summary=foundry_summary,
                preference_audit=preference_audit,
            )
        except ValueError as err:
            parser.error(str(err))

    _emit(report, args.out)
    return 0 if report["gates"]["green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
