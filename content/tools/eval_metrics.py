"""Scoring metrics for the gold-set gate (L4.0e).

Pure functions over per-item judgments: the headline rates, bootstrap confidence
intervals, the paired beat-baseline advantage, per-area breakdowns, and
inter-rater agreement (Cohen's kappa). No I/O, no model calls, so this is unit
testable on its own.

Definitions follow ``docs_pgrep/ai/gold-set-spec.md`` section 5:
  - fact precision: fraction of items with zero wrong-facts.
  - useful-yield: fraction that are correct and useful.
  - key correctness (problems): fraction whose key is correct.
  - distractor quality (problems): per-distractor pass rate (all four criteria)
    and the stricter per-problem rate (all four distractors pass).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class Interval:
    point: float
    low: float
    high: float

    def as_dict(self) -> dict:
        return {"point": self.point, "low": self.low, "high": self.high}


def _quantile(sorted_values: list[float], quantile: float) -> float:
    index = (len(sorted_values) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[lower]
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def bootstrap_ci(values, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> Interval:
    """Percentile bootstrap CI for the mean of 0/1 (or real) values."""
    sample = [float(value) for value in values]
    if not sample:
        return Interval(float("nan"), float("nan"), float("nan"))
    point = sum(sample) / len(sample)
    rng = random.Random(seed)
    means = sorted(
        sum(sample[rng.randrange(len(sample))] for _ in sample) / len(sample)
        for _ in range(n_boot)
    )
    return Interval(
        point,
        _quantile(means, alpha / 2),
        _quantile(means, 1 - alpha / 2),
    )


def paired_advantage_ci(ai_values, base_values, n_boot: int = 2000,
                        alpha: float = 0.05, seed: int = 0) -> Interval:
    """Bootstrap CI for (AI mean - baseline mean), paired by item index.

    Resamples items (rows) with replacement and recomputes the difference of
    means, so the CI reflects the paired comparison on the same targets.
    """
    import numpy as np

    ai = np.asarray(list(ai_values), dtype=float)
    base = np.asarray(list(base_values), dtype=float)
    if ai.size == 0 or ai.size != base.size:
        return Interval(float("nan"), float("nan"), float("nan"))
    point = float(ai.mean() - base.mean())
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, ai.size, size=(n_boot, ai.size))
    diffs = ai[idx].mean(axis=1) - base[idx].mean(axis=1)
    return Interval(point, float(np.quantile(diffs, alpha / 2)),
                    float(np.quantile(diffs, 1 - alpha / 2)))


def cohens_kappa(labels_a, labels_b) -> float:
    """Cohen's kappa for two raters over aligned categorical labels."""
    import numpy as np

    a = list(labels_a)
    b = list(labels_b)
    if not a or len(a) != len(b):
        return float("nan")
    n = len(a)
    cats = sorted(set(a) | set(b))
    idx = {c: i for i, c in enumerate(cats)}
    conf = np.zeros((len(cats), len(cats)), dtype=float)
    for x, y in zip(a, b):
        conf[idx[x], idx[y]] += 1
    po = np.trace(conf) / n
    row = conf.sum(axis=1) / n
    col = conf.sum(axis=0) / n
    pe = float((row * col).sum())
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return float((po - pe) / (1 - pe))


# --- per-item contribution extractors --------------------------------------


def distractor_passes(distractor: dict) -> bool:
    """A distractor passes only if all four criteria hold."""
    return all(bool(distractor.get(c)) for c in
               ("plausible", "misconception_grounded", "non_overlapping", "source_grounded"))


def problem_all_four_pass(judgment: dict) -> bool:
    """The per-problem headline: every distractor passes all four criteria."""
    ds = judgment.get("distractors", [])
    if len(ds) < 4:
        return False
    return all(distractor_passes(d) for d in ds)


def headline_value(judgment: dict, kind: str) -> float:
    """The 0/1 headline contribution for one item: useful-yield (cards) or the
    per-problem all-four-pass rate (problems)."""
    if kind == "problem":
        return 1.0 if problem_all_four_pass(judgment) else 0.0
    return 1.0 if judgment.get("useful") else 0.0


# --- batch aggregation -----------------------------------------------------


def summarize(judgments: list[dict], kind: str, seed: int = 0) -> dict:
    """All gate metrics for one system's batch of judgments (same ``kind``)."""
    if not judgments:
        return {"n": 0}
    fact = [1.0 if j.get("fact_precision") else 0.0 for j in judgments]
    useful = [1.0 if j.get("useful") else 0.0 for j in judgments]
    out: dict = {
        "n": len(judgments),
        "fact_precision": bootstrap_ci(fact, seed=seed).as_dict(),
        "useful_yield": bootstrap_ci(useful, seed=seed).as_dict(),
    }
    if kind == "problem":
        key = [1.0 if j.get("key_correct") else 0.0 for j in judgments]
        per_prob = [1.0 if problem_all_four_pass(j) else 0.0 for j in judgments]
        all_distractors = [1.0 if distractor_passes(d) else 0.0
                           for j in judgments for d in j.get("distractors", [])]
        out["key_correctness"] = bootstrap_ci(key, seed=seed).as_dict()
        out["distractor_quality_per_problem"] = bootstrap_ci(per_prob, seed=seed).as_dict()
        out["distractor_quality_per_distractor"] = bootstrap_ci(all_distractors, seed=seed).as_dict()
        out["headline_metric"] = "distractor_quality_per_problem"
    else:
        out["headline_metric"] = "useful_yield"
    return out


def per_area_breakdown(judgments: list[dict], kind: str, seed: int = 0) -> dict:
    """Headline metric split by blueprint area."""
    areas: dict[str, list[float]] = {}
    for j in judgments:
        area = j.get("blueprint_area") or j.get("area") or "unknown"
        areas.setdefault(area, []).append(headline_value(j, kind))
    return {area: bootstrap_ci(vals, seed=seed).as_dict() for area, vals in sorted(areas.items())}


def beat_baseline(ai_judgments: list[dict], baseline_judgments: dict[str, list[dict]],
                  kind: str, margin: float = 0.10, seed: int = 0) -> dict:
    """Compare the AI headline to each baseline, paired by target id.

    The AI beats a baseline when the advantage point is at least ``margin`` and
    the bootstrap CI of the advantage excludes zero. The gate uses the better
    (harder to beat) baseline.
    """
    import numpy as np

    ai_by_target = {j.get("target_id"): headline_value(j, kind) for j in ai_judgments}
    results: dict[str, dict] = {}
    best_name = None
    best_point = -1.0
    for name, judgs in baseline_judgments.items():
        base_by_target = {j.get("target_id"): headline_value(j, kind) for j in judgs}
        common = [t for t in ai_by_target if t in base_by_target]
        if not common:
            continue
        ai_vals = [ai_by_target[t] for t in common]
        base_vals = [base_by_target[t] for t in common]
        adv = paired_advantage_ci(ai_vals, base_vals, seed=seed)
        base_point = float(np.mean(base_vals))
        beats = adv.point >= margin and adv.low > 0
        results[name] = {
            "baseline_headline": base_point,
            "advantage": adv.as_dict(),
            "beats": beats,
            "n_paired": len(common),
        }
        if base_point > best_point:
            best_point, best_name = base_point, name
    overall = bool(results.get(best_name, {}).get("beats")) if best_name else False
    return {
        "margin_required": margin,
        "ci_rule": "advantage CI excludes 0",
        "best_baseline": best_name,
        "per_baseline": results,
        "passes": overall,
    }
