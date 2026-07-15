# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Calibration statistics for the verifier panel (WS6).

Stdlib-only, pure functions over aligned boolean labels: raw agreement, balanced
accuracy, precision/recall, verdict consistency across perturbations, and a
precision-target threshold sweep. These replace the single misleading kappa with
a per-property, human-aligned picture, and they ship with the app (no numpy), so
they are trivially unit tested.
"""

from __future__ import annotations

from dataclasses import dataclass


def raw_agreement(pred: list[bool], human: list[bool]) -> float:
    if not pred or len(pred) != len(human):
        return float("nan")
    return sum(1 for p, h in zip(pred, human) if p == h) / len(pred)


def balanced_accuracy(pred: list[bool], human: list[bool]) -> float:
    if not pred or len(pred) != len(human):
        return float("nan")
    pos = sum(1 for h in human if h)
    neg = sum(1 for h in human if not h)
    tp = sum(1 for p, h in zip(pred, human) if h and p)
    tn = sum(1 for p, h in zip(pred, human) if (not h) and (not p))
    recalls = []
    if pos:
        recalls.append(tp / pos)
    if neg:
        recalls.append(tn / neg)
    return sum(recalls) / len(recalls) if recalls else float("nan")


def precision_recall(pred: list[bool], human: list[bool]) -> tuple[float, float]:
    if not pred or len(pred) != len(human):
        return float("nan"), float("nan")
    tp = sum(1 for p, h in zip(pred, human) if p and h)
    fp = sum(1 for p, h in zip(pred, human) if p and not h)
    fn = sum(1 for p, h in zip(pred, human) if (not p) and h)
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    return prec, rec


def consistency_score(runs: list[list[bool]]) -> float:
    """Fraction of items whose verdict is identical across every perturbation run."""
    if not runs or not runs[0]:
        return float("nan")
    n = len(runs[0])
    if any(len(run) != n for run in runs):
        return float("nan")
    same = sum(1 for i in range(n) if len({run[i] for run in runs}) == 1)
    return same / n


def tune_threshold(
    confidences: list[float], correct: list[bool], *, target_precision: float = 0.95
) -> float:
    """Smallest confidence cutoff whose kept predictions reach ``target_precision``.

    Evaluates cumulative precision at each distinct confidence boundary (a real
    ``>= cutoff`` threshold cannot split tied confidences), sweeping high to low.
    Returns the lowest qualifying cutoff, or 1.0 if none qualifies.
    """
    if not confidences or len(confidences) != len(correct):
        return 1.0
    pairs = sorted(zip(confidences, correct), key=lambda cp: cp[0], reverse=True)
    best = 1.0
    kept = correct_kept = 0
    i = 0
    total = len(pairs)
    while i < total:
        conf = pairs[i][0]
        while i < total and pairs[i][0] == conf:
            kept += 1
            correct_kept += 1 if pairs[i][1] else 0
            i += 1
        if correct_kept / kept >= target_precision:
            best = conf
    return best


@dataclass
class PropertyReport:
    name: str
    n: int
    raw_agreement: float
    balanced_accuracy: float
    precision: float
    recall: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "n": self.n,
            "raw_agreement": self.raw_agreement,
            "balanced_accuracy": self.balanced_accuracy,
            "precision": self.precision,
            "recall": self.recall,
        }


def property_report(name: str, pred: list[bool], human: list[bool]) -> PropertyReport:
    prec, rec = precision_recall(pred, human)
    return PropertyReport(
        name,
        len(pred),
        raw_agreement(pred, human),
        balanced_accuracy(pred, human),
        prec,
        rec,
    )


def build_card(
    reports: list[PropertyReport], consistency: float | None, thresholds: dict
) -> dict:
    return {
        "properties": [r.to_dict() for r in reports],
        "consistency": consistency,
        "thresholds": thresholds,
    }
