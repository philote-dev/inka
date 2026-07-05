# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Performance (the honest per-topic transfer signal) for pgrep.

Performance answers "can you get a **new, unseen** exam-style problem right" per
topic, ``P(correct)``. It is *transfer*, not recall, so it is computed from the
**attempt log** (not FSRS alone). It is pure math over the attempt log + FSRS
retrievability + the item's authored difficulty: no AI, no schedule mutation
(``three-scores.md`` §2; ``performance-model.md``).

Model (``performance-model.md`` §3) — **Performance Factors Analysis (PFA)**, a
calibrated logistic over four interpretable predictors:

    raw = sigma( b0
               + b_m * mastery_t
               - b_d * difficulty_norm_j
               + g_s * recent_successes_t
               + g_f * recent_failures_t )

- ``mastery_t`` is the topic's mean FSRS retrievability ``R`` (the memory ->
  performance bridge), read from the **same** primitive Memory uses
  (:func:`anki.pgrep.memory.memory_score`), so Memory and Performance never
  disagree. Unknown mastery (Memory abstains) falls back to the max-entropy prior.
- ``difficulty_norm_j`` is the item's authored difficulty (numeric 1..5) mapped to
  ``[0,1]`` by ``(d-1)/4`` and **subtracted** (harder -> less likely). Read from
  the attempt payload; a neutral default is used when it is absent.
- ``recent_successes_t`` / ``recent_failures_t`` are the counts of clean
  correct / incorrect attempts over the last ``recency_window`` in-topic attempts
  (kept separate — full PFA; R-PFA recency via a simple window, no decay knob).

Latency (M5) is a data-quality **filter** (drop rapid-guess / laddered attempts),
never a term. Coverage (M6) is the abstain gate + interval widener, never a term.

Calibration (``performance-model.md`` §4). Post-hoc **beta calibration** (Kull et
al. 2017): ``p = sigma(c + a*ln(raw) - b*ln(1-raw))``. Shipped params are
constants from the offline fit.

Uncertainty & abstain (``performance-model.md`` §5). Every score ships an **80%
central interval** (house convention). We form it as a **Bayesian (Beta) credible
interval that partially pools the topic toward the calibrated model prediction**:
the model prediction is the prior mean, and the topic's clean attempts add
evidence (a partial-pooling-style shrinkage — thin topics get honest wide
intervals). A topic **abstains** until it has ``k_perf`` clean attempts *and* its
interval is tighter than ``max_interval_width``. With an empty attempt log (the
n=1 reality today) every topic abstains — that is the correct behavior.

The learned coefficients and calibration params below are **defaults from the
offline synthetic fit** (``content/tools/performance_eval.py``, ``SEED``
stamped in ``content/run/performance_results.json``). The synthetic study
validates the *pipeline*, not the population coefficients; real coefficients need
a real cohort (``performance-model.md`` §6, §9).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from anki.pgrep.attempt_log import attempts
from anki.pgrep.blueprint import BLUEPRINT_PERCENT, CATEGORY_SLUGS
from anki.pgrep.coverage import COVERAGE_GATE, coverage
from anki.pgrep.memory import memory_score

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.pgrep.attempt_log import Event

# --- tunable thresholds (config, not magic; three-scores.md §8) --------------

# A topic needs at least this many clean attempts to show a Performance number
# (the precision proxy; ``performance-model.md`` §5/§9 #7).
K_PERF_DEFAULT = 8

# A scored topic must be at least this precise: an 80% interval wider than this
# abstains ("Estimate not precise enough yet"). Precision-based abstain.
MAX_INTERVAL_WIDTH_DEFAULT = 0.40

# M3/M4 recency window: count clean wins/misses over the last N in-topic attempts
# (M7 "simple recent window"). Must match the offline fit's window so the learned
# ``g_s`` / ``g_f`` stay on scale (eval RECENCY_WINDOW = 8).
RECENCY_WINDOW_DEFAULT = 8

# Partial-pooling prior strength: how many pseudo-observations of confidence the
# calibrated model prediction contributes before any attempts are seen. The model
# is a validated predictor (it beats the base-rate baseline), so it is worth a few
# observations; real attempts still gate the abstain (``k_perf``). Tunable.
POOLING_STRENGTH_DEFAULT = 4.0

# Latency data-quality filter (M5): attempts faster than this are rapid guesses
# and are excluded from scoring. Inert until ``response_ms`` is logged on attempts.
MIN_RESPONSE_MS_DEFAULT = 2000

# The Readiness coverage gate (0.70), surfaced honestly here; Readiness itself
# (which enforces it) lands in L5.3. Re-exported from :mod:`anki.pgrep.coverage`.
__all__ = ["performance_score", "COVERAGE_GATE"]

# z for the 80% two-sided central interval (the 10th/90th normal percentiles),
# used only for the overall aggregate (per-topic uses the Beta interval).
_Z_80 = 1.2816

# Central-interval mass for the per-topic Beta credible interval.
_INTERVAL_MASS = 0.80

_REASON_THIN = "Not enough attempts yet"
_REASON_IMPRECISE = "Estimate not precise enough yet"

# Neutral fallbacks. Mastery: max entropy when Memory abstains. Difficulty: the
# middle of the 1..5 authored scale when no attempt carries a difficulty.
_MASTERY_NEUTRAL = 0.5
_DIFFICULTY_NEUTRAL = 3.0

# Authored difficulty may arrive as a word or a number; map words to the 1..5 scale.
_DIFFICULTY_LABELS: dict[str, float] = {
    "very_easy": 1.0,
    "easy": 2.0,
    "medium": 3.0,
    "hard": 4.0,
    "very_hard": 5.0,
}


# --- learned model constants (defaults from the offline synthetic fit) --------


@dataclass(frozen=True)
class PFACoefficients:
    """The four PFA logistic coefficients plus the intercept.

    ``b_difficulty`` is stored **positive** and *subtracted* in the logit, matching
    the design's ``- b_d * difficulty`` (harder -> less likely). ``g_failure`` is
    data-signed (learned negative: more recent misses -> less likely).
    """

    b0: float
    b_mastery: float
    b_difficulty: float
    g_success: float
    g_failure: float

    def logit(
        self,
        mastery: float,
        difficulty_norm: float,
        recent_successes: float,
        recent_failures: float,
    ) -> float:
        return (
            self.b0
            + self.b_mastery * mastery
            - self.b_difficulty * difficulty_norm
            + self.g_success * recent_successes
            + self.g_failure * recent_failures
        )


@dataclass(frozen=True)
class BetaCalibration:
    """Beta calibration (Kull et al. 2017): ``sigma(c + a*ln s - b*ln(1-s))``."""

    a: float
    b: float
    c: float

    def calibrate(self, raw: float) -> float:
        s = _clamp(raw, 1e-6, 1.0 - 1e-6)
        return _sigmoid(self.c + self.a * math.log(s) - self.b * math.log(1.0 - s))


# Defaults produced by ``content/tools/performance_eval.py`` (synthetic fit).
# Placeholders until a real-cohort fit; the signs are the design's and are what
# the tests assert, so a bad re-fit that flips a sign is caught.
DEFAULT_COEFFICIENTS = PFACoefficients(
    b0=-0.3396,
    b_mastery=2.1080,
    b_difficulty=1.7265,
    g_success=0.1716,
    g_failure=-0.2200,
)
DEFAULT_CALIBRATION = BetaCalibration(a=1.4173, b=0.9346, c=0.8804)


# --- pure math (no Collection needed; unit-testable in isolation) ------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


def _sigmoid(x: float) -> float:
    # Overflow-safe logistic.
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _difficulty_norm(difficulty: float) -> float:
    """Authored difficulty 1..5 -> [0,1] via (d-1)/4 (matches the offline fit)."""
    return _clamp01((difficulty - 1.0) / 4.0)


def performance_probability(
    mastery: float,
    difficulty: float,
    recent_successes: float,
    recent_failures: float,
    coefficients: PFACoefficients = DEFAULT_COEFFICIENTS,
    calibration: BetaCalibration = DEFAULT_CALIBRATION,
) -> float:
    """Calibrated ``P(correct)`` for one topic's feature vector (the PFA point).

    ``difficulty`` is on the authored 1..5 scale (normalized internally). This is
    the pure model output: the raw PFA logistic passed through beta calibration.
    """
    raw = _sigmoid(
        coefficients.logit(
            mastery, _difficulty_norm(difficulty), recent_successes, recent_failures
        )
    )
    return calibration.calibrate(raw)


def _betacf(
    x: float, a: float, b: float, itmax: int = 200, eps: float = 3e-12
) -> float:
    """Continued fraction for the incomplete beta (Lentz's method, NR §6.4)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta ``I_x(a, b)`` in ``[0, 1]`` (NR §6.4)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - ln_beta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(x, a, b) / a
    return 1.0 - front * _betacf(1.0 - x, b, a) / b


def _beta_ppf(q: float, a: float, b: float) -> float:
    """Inverse of :func:`_betainc` in ``x`` via bisection (monotone in x)."""
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _betainc(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _posterior_alpha_beta(point: float, n_eff: float) -> tuple[float, float]:
    """Beta posterior params: prior centered at ``point`` with concentration
    ``n_eff`` plus a Jeffreys ``+0.5`` (partial pooling toward the model)."""
    p = _clamp(point, 1e-6, 1.0 - 1e-6)
    kappa = max(n_eff, 0.0)
    return kappa * p + 0.5, kappa * (1.0 - p) + 0.5


def _beta_interval(
    point: float, n_eff: float, mass: float = _INTERVAL_MASS
) -> tuple[float, float]:
    """The ``mass`` central Beta credible interval, guaranteed to bracket ``point``."""
    a, b = _posterior_alpha_beta(point, n_eff)
    tail = (1.0 - mass) / 2.0
    low = _beta_ppf(tail, a, b)
    high = _beta_ppf(1.0 - tail, a, b)
    # The reported point must always sit inside its own interval.
    return min(low, point), max(high, point)


def _beta_variance(point: float, n_eff: float) -> float:
    """Variance of the topic's Beta posterior (for the overall aggregate)."""
    a, b = _posterior_alpha_beta(point, n_eff)
    total = a + b
    return (a * b) / (total * total * (total + 1.0))


# --- attempt-log feature extraction (through the read-model seam) -------------


def _is_clean(event: Event, min_response_ms: float) -> bool:
    """Whether an attempt counts toward the score (M5 data-quality filter).

    Only clean, committed, first-try attempts score: ``ladder_depth == 0`` (a
    hinted/laddered attempt informs the tutor, not the score) and not a rapid
    guess (``response_ms`` below the floor). Missing fields are treated as clean,
    so today's attempts (which log neither a deeper ladder nor latency) all count.
    """
    payload = event.payload
    try:
        if int(payload.get("ladder_depth", 0) or 0) != 0:
            return False
    except (TypeError, ValueError):
        pass
    response_ms = payload.get("response_ms")
    if response_ms is not None:
        try:
            if float(response_ms) < min_response_ms:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _attempt_difficulty(payload: dict[str, Any]) -> float | None:
    """The item's authored difficulty (1..5) from the attempt payload, or ``None``.

    Accepts a number in 1..5 or a word ("easy".."very_hard"). Returns ``None`` when
    absent/unparseable so the caller can fall back to a neutral difficulty.
    """
    raw = payload.get("difficulty")
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return _clamp(float(raw), 1.0, 5.0)
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in _DIFFICULTY_LABELS:
            return _DIFFICULTY_LABELS[key]
        try:
            return _clamp(float(key), 1.0, 5.0)
        except ValueError:
            return None
    return None


def _topic_features(
    events: list[Event], mastery: float, recency_window: int
) -> tuple[float, float, int, int, int]:
    """(mastery, mean_difficulty, recent_successes, recent_failures, distinct_items).

    ``events`` are the topic's clean attempts, oldest first. Successes/failures are
    counted over the last ``recency_window``; difficulty is averaged over all of
    the topic's clean attempts that carry one (neutral when none do).
    """
    window = events[-recency_window:] if recency_window > 0 else events
    recent_successes = sum(1 for e in window if e.correct)
    recent_failures = len(window) - recent_successes

    diffs = [
        d for d in (_attempt_difficulty(e.payload) for e in events) if d is not None
    ]
    difficulty = sum(diffs) / len(diffs) if diffs else _DIFFICULTY_NEUTRAL

    item_ids = {
        e.payload.get("item_note_id")
        for e in events
        if e.payload.get("item_note_id") is not None
    }
    distinct_items = len(item_ids)
    return mastery, difficulty, recent_successes, recent_failures, distinct_items


# --- the seam (three-scores.md §2; performance-model.md) ----------------------


def performance_score(
    col: Collection,
    deck_id: int | None = None,
    k_perf: int = K_PERF_DEFAULT,
    recency_window: int = RECENCY_WINDOW_DEFAULT,
    max_interval_width: float = MAX_INTERVAL_WIDTH_DEFAULT,
    pooling_strength: float = POOLING_STRENGTH_DEFAULT,
    min_response_ms: float = MIN_RESPONSE_MS_DEFAULT,
    coefficients: PFACoefficients = DEFAULT_COEFFICIENTS,
    calibration: BetaCalibration = DEFAULT_CALIBRATION,
) -> dict:
    """Return the Performance score for the collection.

    The result is JSON-serializable: ``overall`` plus a per-category ``by_topic``
    breakdown (in blueprint order), each with a point ``P(correct)``, an 80%
    ``low``/``high`` range, an ``n_attempts`` count, and an ``abstain`` flag +
    ``reason``. ``coverage_pct`` and ``coverage_gate`` surface Coverage honestly
    (Readiness, which enforces the gate, is L5.3). ``deck_id`` scopes only the
    mastery (FSRS card) component; the attempt log is collection-wide.

    Everything is arithmetic over the attempt log + FSRS + the authored difficulty
    tag: AI-off, and no scheduling state is read or written.
    """
    now = int(time.time())

    # Mastery per category from the SAME primitive Memory uses (bridge; consistent
    # by construction). ``None`` where Memory abstains (too few reviewed cards).
    mem = memory_score(col, deck_id=deck_id)
    mastery_by_category = {
        entry["category"]: entry["point"] for entry in mem["by_topic"]
    }

    cov = coverage(col)

    # Group clean attempts by category through the read-model seam (K4). Attempts
    # come back oldest-first, which the recency window relies on.
    clean_by_category: dict[str, list[Event]] = {}
    for event in attempts(col):
        if event.category not in BLUEPRINT_PERCENT:
            continue  # untagged / unknown / off-blueprint
        if not _is_clean(event, min_response_ms):
            continue
        clean_by_category.setdefault(event.category, []).append(event)

    by_topic: list[dict[str, Any]] = []
    scored: list[tuple[float, float, float]] = []  # (blueprint, point, variance)
    total_attempts = 0

    for category in CATEGORY_SLUGS:
        blueprint = BLUEPRINT_PERCENT[category]
        events = clean_by_category.get(category, [])
        n = len(events)
        total_attempts += n

        if n < k_perf:
            by_topic.append(_topic_entry(category, blueprint, n, reason=_REASON_THIN))
            continue

        raw_mastery = mastery_by_category.get(category)
        mastery = raw_mastery if raw_mastery is not None else _MASTERY_NEUTRAL
        mastery, difficulty, succ, fail, distinct = _topic_features(
            events, mastery, recency_window
        )
        point = performance_probability(
            mastery, difficulty, succ, fail, coefficients, calibration
        )

        # Coverage (M6) as interval widener: attempts spread over few repeated
        # items carry less information, so deflate their evidence contribution.
        coverage_factor = min(1.0, distinct / k_perf) if distinct > 0 else 1.0
        n_eff = pooling_strength + n * coverage_factor
        low, high = _beta_interval(point, n_eff)

        if (high - low) > max_interval_width:
            by_topic.append(
                _topic_entry(category, blueprint, n, reason=_REASON_IMPRECISE)
            )
            continue

        by_topic.append(
            {
                "category": category,
                "blueprint": blueprint,
                "point": point,
                "low": low,
                "high": high,
                "n_attempts": n,
                "abstain": False,
                "reason": None,
            }
        )
        scored.append((blueprint, point, _beta_variance(point, n_eff)))

    return {
        "overall": _overall(scored),
        "by_topic": by_topic,
        "k_perf": k_perf,
        "coverage_pct": cov["overall_pct"],
        "coverage_gate": COVERAGE_GATE,
        "last_updated": now if total_attempts > 0 else None,
    }


def _topic_entry(
    category: str, blueprint: float, n_attempts: int, reason: str
) -> dict[str, Any]:
    """An abstaining per-topic entry (no number, names what is missing)."""
    return {
        "category": category,
        "blueprint": blueprint,
        "point": None,
        "low": None,
        "high": None,
        "n_attempts": n_attempts,
        "abstain": True,
        "reason": reason,
    }


def _overall(scored: list[tuple[float, float, float]]) -> dict[str, Any]:
    """Blueprint-weighted overall Performance over the scored topics.

    ``scored`` is ``(blueprint_weight, point, variance)`` per scored category. The
    point is the weight-normalized mean; the 80% range propagates the per-topic
    Beta variances with the same normalized weights (topics independent), matching
    Memory's overall. Abstains when nothing is scored.
    """
    if not scored:
        return {
            "point": None,
            "low": None,
            "high": None,
            "abstain": True,
            "reason": _REASON_THIN,
        }
    total_weight = sum(weight for weight, _, _ in scored)
    point = sum(weight * pt for weight, pt, _ in scored) / total_weight
    variance = sum((weight / total_weight) ** 2 * var for weight, _, var in scored)
    sd = math.sqrt(variance)
    return {
        "point": point,
        "low": _clamp01(point - _Z_80 * sd),
        "high": _clamp01(point + _Z_80 * sd),
        "abstain": False,
        "reason": None,
    }
