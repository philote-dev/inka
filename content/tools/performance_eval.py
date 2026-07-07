#!/usr/bin/env python3
"""L5.2 Performance model — offline held-out evaluation (methodology validation).

This validates the **pipeline** for the Performance score (``P(correct on a new,
unseen exam-style problem)``) described in ``docs_pgrep/research/performance-model.md``
and ``three-scores.md`` §2: a **Performance Factors Analysis (PFA)** logistic over
four interpretable predictors, post-hoc **beta calibration** (Kull et al. 2017),
measured on a held-out split against the per-topic **base-rate (batting average)**
baseline.

Why synthetic data (n=1 reality). At n=1 the real attempt log is EMPTY, so there
is nothing to fit or measure. We therefore validate the *methodology* on a
**seeded, documented synthetic dataset** whose outcomes are
``y ~ Bernoulli(sigma(w·x + b))`` with **pre-registered** coefficients plus label
noise (``performance-model.md`` §6). This proves the fit -> calibrate -> held-out
machinery is correct and that a PFA logistic beats the base-rate baseline when the
signal is real. It does **not** claim the coefficients are the true population
coefficients: real coefficients need a real cohort (the bonus Step-4 validation).
The fitted coefficients here feed the *defaults* baked into
``pylib/anki/pgrep/performance.py``.

Splitting (no leakage; ``performance-model.md`` §6, hard constraints).
  * Each synthetic item is one attempt event with a unique id and a time index.
  * We split **by item id + time order, never random**: earliest 60% by time ->
    FIT (learn coefficients), next 20% -> CAL (fit beta calibration), latest 20%
    -> HELD-OUT (never seen while fitting).
  * Every feature is computed **causally**, from attempts strictly *before* the
    item, and item difficulty comes from the item's *authored* tag (never
    estimated on the eval data). So the held-out outcomes never inform the fit.

Metrics on held-out (``performance-model.md`` §6): Brier (primary), log-loss,
accuracy, AUC, a reliability diagram + ECE (equal-mass bins), each with a
**95% bootstrap CI** (the eval convention; the shipped per-topic range is an 80%
interval — two different conventions, both stated). The **calibrated PFA model**
and the **base-rate baseline** are reported side by side, and the pre-registered
rule is checked:

    PASS  <=>  Brier(model) < Brier(baseline)  AND  accuracy(model) > accuracy(baseline)

Run (one re-runnable command):

    conda run -n pgrep-ai --no-capture-output python content/tools/performance_eval.py

Outputs:
    content/run/performance_results.json   (metrics + coeffs + beta-cal + seed + splits)
    content/run/performance.md             (short summary + model-vs-baseline table)
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

# The eval helpers live next to this file; make the import work regardless of the
# current working directory (content/ is a symlink, so __file__ is the anchor).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_metrics import bootstrap_ci  # noqa: E402  (reused read-only)

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
RUN_DIR = os.path.join(CONTENT, "run")

# --- configuration (all pre-registered; change here to re-run a variant) -----

SEED = 20260705

# ~800 items so the held-out split (~20%) fills equal-mass reliability bins.
N_ITEMS = 800

# The nine blueprint categories (duplicated locally on purpose; the shipped
# blueprint table is intentionally per-language and must not be imported here).
CATEGORIES = (
    "mechanics",
    "electromagnetism",
    "quantum",
    "thermodynamics",
    "atomic",
    "optics_waves",
    "special_relativity",
    "lab",
    "specialized",
)

# Pre-registered TRUE data-generating coefficients (interpretable, literature
# plausible; PFA form, features scaled exactly as the model uses them). These are
# what a correct pipeline should approximately recover.
TRUE_COEF = {
    "b0": -0.30,   # intercept: a touch below even odds at neutral inputs
    "b_m": 2.60,   # mastery in [0,1]: strong positive (the memory->transfer bridge)
    "b_d": 2.00,   # difficulty (normalized [0,1]): SUBTRACTED, so harder -> lower
    "g_s": 0.25,   # recent successes: positive (R-PFA)
    "g_f": -0.30,  # recent failures: negative (PFA weights wins/misses separately)
}

# Recency window for M3/M4 (M7): count clean wins/misses over the last N in-topic
# attempts. A simple fixed window (no decay knob) per the v1 decision.
RECENCY_WINDOW = 8

# Label noise: flip this fraction of drawn outcomes so the model cannot be perfect
# (a realistic Bayes error; the base-rate baseline still must lose).
LABEL_NOISE = 0.06

# Split fractions by time order (fit / calibration / held-out).
FIT_FRAC, CAL_FRAC = 0.60, 0.20

# Ridge (L2) strength for the PFA fit. The synthetic set is large, so a weak
# penalty recovers the true coefficients cleanly; a real small cohort would use a
# stronger ridge (smaller C) for stability (performance-model.md §3).
FIT_C = 1.0e3
# The beta-calibration logistic has three params; fit it with a very weak penalty.
CAL_C = 1.0e6

# Reliability diagram / ECE: equal-mass bins.
N_BINS = 10
# Bootstrap for the held-out metric CIs (95%, the eval convention).
N_BOOT = 2000
BOOT_ALPHA = 0.05

_EPS = 1.0e-6


def _sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-x))


def _diff_norm(difficulty: np.ndarray | float) -> np.ndarray | float:
    """Authored difficulty 1..5 -> [0,1]; must match the shipped model exactly."""
    return (np.asarray(difficulty, dtype=float) - 1.0) / 4.0


# --- synthetic data-generating process ---------------------------------------


@dataclass
class Item:
    """One synthetic attempt event: an item, its causal features, its outcome."""

    item_id: int
    t: int
    category: str
    difficulty: int
    mastery: float
    recent_successes: int
    recent_failures: int
    p_true: float
    y: int

    def features(self) -> list[float]:
        """Feature vector in the model's order: [mastery, diff_norm, succ, fail]."""
        return [
            self.mastery,
            float(_diff_norm(self.difficulty)),
            float(self.recent_successes),
            float(self.recent_failures),
        ]


def generate_dataset(seed: int = SEED, n_items: int = N_ITEMS) -> list[Item]:
    """A seeded, time-ordered synthetic attempt log with causal features.

    Each item is drawn in time order. For its topic we look only at *prior*
    attempts to build the recency-windowed success/failure counts, and mastery
    grows with prior practice in the topic (a mean-FSRS-retrievability stand-in in
    ``[0,1]``). The outcome is ``Bernoulli(sigma(w_true·x + b_true))`` with the
    pre-registered coefficients, then flipped with probability ``LABEL_NOISE``.
    Nothing about an item's own outcome enters its features -> no leakage.
    """
    rng = np.random.default_rng(seed)
    # A latent per-topic base skill. Kept deliberately SMALL so most of the signal
    # is *within* topic (mastery, difficulty, recency) rather than between topics.
    # That is the honest hard case for the base-rate baseline, which can only see
    # the topic average: it should barely beat chance while the PFA model does not.
    base_skill = {c: rng.normal(0.0, 0.30) for c in CATEGORIES}
    # Per-topic causal history of clean outcomes, oldest -> newest.
    history: dict[str, list[int]] = {c: [] for c in CATEGORIES}

    items: list[Item] = []
    for t in range(n_items):
        category = CATEGORIES[rng.integers(0, len(CATEGORIES))]
        difficulty = int(rng.integers(1, 6))  # authored tag in {1,2,3,4,5}

        past = history[category]
        n_prior = len(past)
        window = past[-RECENCY_WINDOW:]
        recent_successes = int(sum(window))
        recent_failures = int(len(window) - recent_successes)

        # Mastery in [0,1]: mostly idiosyncratic per item (the learner's state when
        # they meet this item), around the topic's small base skill, with a mild
        # practice drift. The wide idiosyncratic spread keeps mastery only loosely
        # collinear with the recency counts, so the fit can separate the terms.
        # This is the synthetic stand-in for mean FSRS retrievability R.
        mastery = float(
            _sigmoid(base_skill[category] + rng.normal(0.0, 1.1) + 0.03 * n_prior)
        )

        logit = (
            TRUE_COEF["b0"]
            + TRUE_COEF["b_m"] * mastery
            - TRUE_COEF["b_d"] * float(_diff_norm(difficulty))
            + TRUE_COEF["g_s"] * recent_successes
            + TRUE_COEF["g_f"] * recent_failures
        )
        p_true = float(_sigmoid(logit))
        y = int(rng.random() < p_true)
        if rng.random() < LABEL_NOISE:
            y = 1 - y  # label noise: a realistic Bayes error floor

        items.append(
            Item(
                item_id=t,
                t=t,
                category=category,
                difficulty=difficulty,
                mastery=mastery,
                recent_successes=recent_successes,
                recent_failures=recent_failures,
                p_true=p_true,
                y=y,
            )
        )
        history[category].append(y)
    return items


def time_item_split(items: list[Item]) -> tuple[list[Item], list[Item], list[Item]]:
    """Split by item id + time order (never random): fit / cal / held-out."""
    ordered = sorted(items, key=lambda it: it.t)
    n = len(ordered)
    n_fit = int(round(n * FIT_FRAC))
    n_cal = int(round(n * CAL_FRAC))
    fit = ordered[:n_fit]
    cal = ordered[n_fit : n_fit + n_cal]
    held = ordered[n_fit + n_cal :]
    return fit, cal, held


# --- the PFA model + beta calibration ----------------------------------------


@dataclass
class Coefficients:
    b0: float
    b_m: float
    b_d: float  # stored POSITIVE; the model subtracts it (harder -> lower)
    g_s: float
    g_f: float

    def logit(self, X: np.ndarray) -> np.ndarray:
        mastery, diff_norm, succ, fail = X[:, 0], X[:, 1], X[:, 2], X[:, 3]
        return (
            self.b0
            + self.b_m * mastery
            - self.b_d * diff_norm
            + self.g_s * succ
            + self.g_f * fail
        )

    def raw_prob(self, X: np.ndarray) -> np.ndarray:
        return _sigmoid(self.logit(X))

    def as_dict(self) -> dict:
        return {"b0": self.b0, "b_m": self.b_m, "b_d": self.b_d,
                "g_s": self.g_s, "g_f": self.g_f}


@dataclass
class BetaCal:
    """Beta calibration (Kull et al. 2017): p = sigma(c + a·ln s - b·ln(1-s))."""

    a: float
    b: float
    c: float

    def calibrate(self, s: np.ndarray) -> np.ndarray:
        s = np.clip(np.asarray(s, dtype=float), _EPS, 1.0 - _EPS)
        return _sigmoid(self.c + self.a * np.log(s) - self.b * np.log(1.0 - s))

    def as_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "c": self.c}


def fit_pfa(fit_items: list[Item]) -> Coefficients:
    """Fit the four-term PFA logistic on the fit split (L2 ridge)."""
    X = np.array([it.features() for it in fit_items], dtype=float)
    y = np.array([it.y for it in fit_items], dtype=int)
    clf = LogisticRegression(C=FIT_C, max_iter=10000)
    clf.fit(X, y)
    b_m, b_d_raw, g_s, g_f = clf.coef_[0]
    # The model form subtracts difficulty, so store its magnitude with the sign
    # flipped: b_d POSITIVE means "harder lowers P" (the fit learns b_d_raw < 0).
    return Coefficients(
        b0=float(clf.intercept_[0]),
        b_m=float(b_m),
        b_d=float(-b_d_raw),
        g_s=float(g_s),
        g_f=float(g_f),
    )


def fit_beta_calibration(coef: Coefficients, cal_items: list[Item]) -> BetaCal:
    """Fit 3-param beta calibration on the calibration split's raw scores."""
    X = np.array([it.features() for it in cal_items], dtype=float)
    y = np.array([it.y for it in cal_items], dtype=int)
    s = np.clip(coef.raw_prob(X), _EPS, 1.0 - _EPS)
    # Features for the calibration logistic: ln(s) and ln(1-s).
    feats = np.column_stack([np.log(s), np.log(1.0 - s)])
    clf = LogisticRegression(C=CAL_C, max_iter=10000)
    clf.fit(feats, y)
    w1, w2 = clf.coef_[0]
    # p = sigma(c + a·ln s - b·ln(1-s)); the fit gives coef on ln(s), ln(1-s).
    return BetaCal(a=float(w1), b=float(-w2), c=float(clf.intercept_[0]))


# --- the base-rate (batting average) baseline --------------------------------


def fit_base_rates(fit_items: list[Item]) -> tuple[dict[str, float], float]:
    """Per-topic base rate (batting average) from the fit split, + global mean.

    The baseline the model must beat: it ignores mastery, difficulty and recency
    and just predicts each topic's historical clean-correct rate. Topics unseen in
    fit fall back to the global rate.
    """
    by_topic: dict[str, list[int]] = {}
    for it in fit_items:
        by_topic.setdefault(it.category, []).append(it.y)
    global_rate = float(np.mean([it.y for it in fit_items]))
    rates = {c: float(np.mean(ys)) for c, ys in by_topic.items()}
    return rates, global_rate


def base_rate_predict(
    items: list[Item], rates: dict[str, float], global_rate: float
) -> np.ndarray:
    return np.array([rates.get(it.category, global_rate) for it in items], dtype=float)


# --- metrics -----------------------------------------------------------------


def _accuracy_items(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    return (np.asarray(p) >= 0.5).astype(float) == np.asarray(y).astype(float)


def _brier_items(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    return (np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2


def _logloss_items(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), _EPS, 1.0 - _EPS)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))


def _auc_ci(y: np.ndarray, p: np.ndarray, n_boot: int = N_BOOT,
            alpha: float = BOOT_ALPHA, seed: int = 0) -> dict:
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    point = float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan")
    rng = np.random.default_rng(seed)
    n = len(y)
    aucs: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        yb = y[idx]
        if len(np.unique(yb)) < 2:
            continue
        aucs.append(float(roc_auc_score(yb, p[idx])))
    if not aucs:
        return {"point": point, "low": float("nan"), "high": float("nan")}
    return {"point": point, "low": float(np.quantile(aucs, alpha / 2)),
            "high": float(np.quantile(aucs, 1 - alpha / 2))}


def equal_mass_reliability(y: np.ndarray, p: np.ndarray, n_bins: int = N_BINS
                           ) -> tuple[list[dict], float]:
    """Reliability diagram (equal-mass bins) + ECE.

    Equal-mass bins (quantile edges) keep every bin populated at small n, which is
    why we prefer them over equal-width bins (``performance-model.md`` §6).
    """
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n = len(p)
    order = np.argsort(p)
    p_sorted, y_sorted = p[order], y[order]
    edges = np.linspace(0, n, n_bins + 1).astype(int)
    diagram: list[dict] = []
    ece = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        if hi <= lo:
            continue
        pb, yb = p_sorted[lo:hi], y_sorted[lo:hi]
        conf, acc, count = float(pb.mean()), float(yb.mean()), int(hi - lo)
        ece += (count / n) * abs(acc - conf)
        diagram.append({"bin": i + 1, "n": count, "mean_pred": conf,
                        "mean_obs": acc, "gap": acc - conf})
    return diagram, float(ece)


def evaluate(name: str, y: np.ndarray, p: np.ndarray, seed: int = 0) -> dict:
    """All held-out metrics for one predictor, with 95% bootstrap CIs."""
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    brier_items = _brier_items(y, p)
    acc_items = _accuracy_items(y, p)
    ll_items = _logloss_items(y, p)
    diagram, ece = equal_mass_reliability(y, p)
    return {
        "name": name,
        "n": int(len(y)),
        "brier": bootstrap_ci(brier_items, n_boot=N_BOOT, alpha=BOOT_ALPHA,
                              seed=seed).as_dict(),
        "log_loss": bootstrap_ci(ll_items, n_boot=N_BOOT, alpha=BOOT_ALPHA,
                                 seed=seed).as_dict(),
        "accuracy": bootstrap_ci(acc_items, n_boot=N_BOOT, alpha=BOOT_ALPHA,
                                 seed=seed).as_dict(),
        "auc": _auc_ci(y, p, seed=seed),
        # Point values from sklearn as an independent cross-check of the means.
        "brier_sklearn": float(brier_score_loss(y, p)),
        "log_loss_sklearn": float(log_loss(y, p, labels=[0, 1])),
        "ece": ece,
        "reliability": diagram,
    }


@dataclass
class Results:
    seed: int
    n_items: int
    split_sizes: dict[str, int]
    coefficients: dict
    true_coefficients: dict
    beta_calibration: dict
    base_rates: dict
    config: dict
    model: dict = field(default_factory=dict)
    baseline: dict = field(default_factory=dict)
    beats_baseline: dict = field(default_factory=dict)


def run() -> Results:
    items = generate_dataset()
    fit, cal, held = time_item_split(items)

    coef = fit_pfa(fit)
    beta = fit_beta_calibration(coef, cal)
    rates, global_rate = fit_base_rates(fit)

    Xh = np.array([it.features() for it in held], dtype=float)
    yh = np.array([it.y for it in held], dtype=int)

    raw = coef.raw_prob(Xh)
    p_model = beta.calibrate(raw)
    p_base = base_rate_predict(held, rates, global_rate)

    model_metrics = evaluate("pfa_beta_calibrated", yh, p_model, seed=SEED)
    base_metrics = evaluate("base_rate_baseline", yh, p_base, seed=SEED)

    # Pre-registered success rule (Isabella's): strictly better Brier AND accuracy.
    brier_ok = model_metrics["brier"]["point"] < base_metrics["brier"]["point"]
    acc_ok = model_metrics["accuracy"]["point"] > base_metrics["accuracy"]["point"]
    beats = {
        "rule": "Brier(model) < Brier(baseline) AND accuracy(model) > accuracy(baseline)",
        "brier_model": model_metrics["brier"]["point"],
        "brier_baseline": base_metrics["brier"]["point"],
        "brier_better": bool(brier_ok),
        "accuracy_model": model_metrics["accuracy"]["point"],
        "accuracy_baseline": base_metrics["accuracy"]["point"],
        "accuracy_better": bool(acc_ok),
        "passes": bool(brier_ok and acc_ok),
    }

    return Results(
        seed=SEED,
        n_items=len(items),
        split_sizes={"fit": len(fit), "calibration": len(cal), "held_out": len(held)},
        coefficients=coef.as_dict(),
        true_coefficients=dict(TRUE_COEF),
        beta_calibration=beta.as_dict(),
        base_rates={"per_topic": rates, "global": global_rate},
        config={
            "recency_window": RECENCY_WINDOW,
            "label_noise": LABEL_NOISE,
            "fit_frac": FIT_FRAC,
            "cal_frac": CAL_FRAC,
            "fit_C": FIT_C,
            "cal_C": CAL_C,
            "n_bins": N_BINS,
            "n_boot": N_BOOT,
            "ci": "95% bootstrap (eval); shipped range is an 80% interval",
            "difficulty_scale": "authored 1..5 normalized to [0,1] as (d-1)/4",
            "feature_order": ["mastery", "difficulty_norm",
                              "recent_successes", "recent_failures"],
        },
        model=model_metrics,
        baseline=base_metrics,
        beats_baseline=beats,
    )


# --- reporting ---------------------------------------------------------------


def _fmt_ci(m: dict) -> str:
    return f"{m['point']:.4f} [{m['low']:.4f}, {m['high']:.4f}]"


def write_outputs(res: Results) -> tuple[str, str]:
    os.makedirs(RUN_DIR, exist_ok=True)
    json_path = os.path.join(RUN_DIR, "performance_results.json")
    md_path = os.path.join(RUN_DIR, "performance.md")

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(res.__dict__, fh, indent=2, sort_keys=True)
        fh.write("\n")

    m, b = res.model, res.baseline
    verdict = "PASS" if res.beats_baseline["passes"] else "DOES NOT PASS"
    c = res.coefficients
    lines = [
        "# Performance model — held-out evaluation (methodology validation)",
        "",
        "**Status: synthetic-data pipeline validation.** At n=1 the real attempt "
        "log is empty, so this validates the PFA fit -> beta-calibration -> "
        "held-out **methodology** on a seeded synthetic dataset. It is **not** a "
        "claim about real coefficients; those need a real cohort (Step-4). The "
        "fitted coefficients below ship as the *defaults* in "
        "`pylib/anki/pgrep/performance.py`.",
        "",
        f"- Seed: `{res.seed}`  |  items: {res.n_items}  |  splits (by item id + "
        f"time order): fit={res.split_sizes['fit']}, "
        f"calibration={res.split_sizes['calibration']}, "
        f"held-out={res.split_sizes['held_out']}",
        f"- Model: PFA logistic (4 predictors) + beta calibration (Kull et al. 2017)",
        f"- Baseline: per-topic base rate (batting average) from the fit split",
        "- CIs below are **95% bootstrap** (eval convention); the shipped per-topic "
        "range is an **80%** interval.",
        "",
        "## Model vs baseline (held-out)",
        "",
        "| Metric | PFA + beta cal | Base-rate baseline | Model better? |",
        "|---|---|---|---|",
        f"| Brier (primary) ↓ | {_fmt_ci(m['brier'])} | {_fmt_ci(b['brier'])} | "
        f"{'yes' if res.beats_baseline['brier_better'] else 'no'} |",
        f"| Accuracy ↑ | {_fmt_ci(m['accuracy'])} | {_fmt_ci(b['accuracy'])} | "
        f"{'yes' if res.beats_baseline['accuracy_better'] else 'no'} |",
        f"| Log-loss ↓ | {_fmt_ci(m['log_loss'])} | {_fmt_ci(b['log_loss'])} | "
        f"{'yes' if m['log_loss']['point'] < b['log_loss']['point'] else 'no'} |",
        f"| AUC ↑ | {_fmt_ci(m['auc'])} | {_fmt_ci(b['auc'])} | "
        f"{'yes' if m['auc']['point'] > b['auc']['point'] else 'no'} |",
        f"| ECE (equal-mass) ↓ | {m['ece']:.4f} | {b['ece']:.4f} | "
        f"{'yes' if m['ece'] < b['ece'] else 'no'} |",
        "",
        f"### Pre-registered rule: **{verdict}**",
        "",
        f"> {res.beats_baseline['rule']}",
        "",
        f"Brier {res.beats_baseline['brier_model']:.4f} < "
        f"{res.beats_baseline['brier_baseline']:.4f} "
        f"({'holds' if res.beats_baseline['brier_better'] else 'fails'}); "
        f"accuracy {res.beats_baseline['accuracy_model']:.4f} > "
        f"{res.beats_baseline['accuracy_baseline']:.4f} "
        f"({'holds' if res.beats_baseline['accuracy_better'] else 'fails'}).",
        "",
        "## Fitted coefficients (ship as defaults)",
        "",
        "PFA logit = `b0 + b_m·mastery - b_d·difficulty_norm + g_s·succ + g_f·fail`, "
        "difficulty_norm = (difficulty-1)/4.",
        "",
        "| Coef | Fitted | True (DGP) |",
        "|---|---|---|",
        f"| b0 | {c['b0']:.4f} | {res.true_coefficients['b0']:.4f} |",
        f"| b_m (mastery) | {c['b_m']:.4f} | {res.true_coefficients['b_m']:.4f} |",
        f"| b_d (difficulty) | {c['b_d']:.4f} | {res.true_coefficients['b_d']:.4f} |",
        f"| g_s (recent successes) | {c['g_s']:.4f} | {res.true_coefficients['g_s']:.4f} |",
        f"| g_f (recent failures) | {c['g_f']:.4f} | {res.true_coefficients['g_f']:.4f} |",
        "",
        f"Beta calibration: a={res.beta_calibration['a']:.4f}, "
        f"b={res.beta_calibration['b']:.4f}, c={res.beta_calibration['c']:.4f}  "
        f"(p_cal = sigma(c + a·ln s - b·ln(1-s))).",
        "",
        "## Honest n=1 caveat",
        "",
        "These numbers validate the **pipeline**, not the learner. With one real "
        "user the attempt log is empty today, so the live model **abstains "
        "everywhere** (correct behavior). The coefficients above are recovered "
        "from a synthetic DGP and ship only as reasonable defaults; a real cohort "
        "is required to learn trustworthy population coefficients.",
        "",
    ]
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return json_path, md_path


def main() -> None:
    res = run()
    json_path, md_path = write_outputs(res)
    b = res.beats_baseline
    print("Performance model eval (synthetic methodology validation)")
    print(f"  seed={res.seed} items={res.n_items} splits={res.split_sizes}")
    print(f"  fitted coeffs: {json.dumps(res.coefficients)}")
    print(f"  beta cal:      {json.dumps(res.beta_calibration)}")
    print(f"  Brier   model={b['brier_model']:.4f}  base={b['brier_baseline']:.4f}"
          f"  better={b['brier_better']}")
    print(f"  Accuracy model={b['accuracy_model']:.4f}  base={b['accuracy_baseline']:.4f}"
          f"  better={b['accuracy_better']}")
    print(f"  AUC     model={res.model['auc']['point']:.4f}  "
          f"base={res.baseline['auc']['point']:.4f}")
    print(f"  ECE     model={res.model['ece']:.4f}  base={res.baseline['ece']:.4f}")
    print(f"  PRE-REGISTERED RULE: {'PASS' if b['passes'] else 'FAIL'}")
    print(f"  wrote {json_path}")
    print(f"  wrote {md_path}")


if __name__ == "__main__":
    main()
