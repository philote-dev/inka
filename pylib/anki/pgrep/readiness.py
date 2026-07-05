# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Readiness (the projected PGRE scaled score, with a range) for pgrep.

Readiness answers "what would you score" — the projected PGRE **scaled score**
(the 200-990 band) with an explicit **range**, an explicit **coverage**, and an
**abstain** when coverage is too thin. It leans on **Performance** (transfer
under exam conditions), not Memory (Soderstrom & Bjork: the test measures
transfer, not recall). It is pure math over the Performance model + the blueprint
+ the embedded raw->scaled constants: no AI, no schedule mutation, no
user-confidence capture (``three-scores.md`` §3; ``statistics-and-evaluation.md``).

Pipeline (``three-scores.md`` §3):

1. **Per topic** ``p_t`` is ``P(correct)`` from the Performance model
   (:func:`anki.pgrep.performance.performance_score`); ``n_t`` is the number of
   exam questions the topic contributes, ``blueprint%(topic) * exam_question_count``
   over the PGRE's 100 scored questions.
2. **Expected raw** treats each of the ``n_t`` questions as ``Bernoulli(p_t)``;
   the total number correct is a **Poisson-binomial** across topics, with mean
   ``Sum n_t*p_t`` and variance ``Sum n_t*p_t*(1-p_t)``.
3. **Raw -> scaled** maps the raw point and the raw interval endpoints through the
   official raw->scaled conversion table, embedded as tracked constants in
   :mod:`anki.pgrep.readiness_constants` (see that module for the "constants only"
   / firewall rationale). The table's raw axis is **formula-scored**
   (``round(correct - incorrect/4)``), so expected-*correct* must be converted to
   the table's raw first (see the raw-formula assumption below).
4. **Range** propagates uncertainty two ways and adds them (law of total
   variance): the Poisson-binomial **sampling** spread (exam randomness even if
   ``p_t`` were known) plus the **model** spread carried by each topic's 80%
   Performance interval. Endpoints go through the table to give an **80% scaled
   interval** (the house convention). Thin coverage widens it: uncovered topics
   fall back to the guessing baseline (high sampling spread) and marginal topics
   carry wide Performance intervals (high model spread).
5. **Coverage gate + abstain.** ``coverage`` is the fraction of blueprint weight
   whose topics have at least ``k_perf`` scored attempts. Below ``coverage_gate``
   (70%) Readiness **abstains** ("Not enough of the exam is covered yet") and
   names the uncovered topics. You cannot fake readiness over a hole.

**Raw-formula assumption (documented, and it materially affects the number).**
The table's raw axis is ``correct - incorrect/4`` but the Performance model yields
expected *correct*. We assume **all questions are attempted**, so
``incorrect = n - correct`` and

    raw = correct - (n - correct)/4 = 1.25*correct - 0.25*n ,

clamped to the table's raw domain and rounded to the nearest integer. This mirrors
the classic formula-scored PGRE (random guessing on a 5-choice item is
expected-neutral: ``0.2 - 0.8/4 = 0``), so unstudied topics filled with the
guessing baseline contribute ~0 raw. The alternative, **rights-only**
(``raw = correct``, the post-2011 GRE convention), is exposed via
``assume_all_attempted=False`` but is **not** the default because it does not match
*this* table's stated formula; it would score a guesser far too high.

Uncovered topics (the minority allowed below the gate) are filled with the
5-choice **guessing baseline** (``p_t = 0.2``) rather than dropped, so the
projection still spans all 100 questions; they are named in ``uncovered_topics``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from anki.pgrep.coverage import COVERAGE_GATE
from anki.pgrep.performance import K_PERF_DEFAULT, performance_score
from anki.pgrep.readiness_constants import (
    RAW_MAX,
    RAW_MIN,
    RAW_SCORE_FORMULA,
    RAW_TO_SCALED_TABLE,
    SCORED_QUESTION_COUNT,
)

if TYPE_CHECKING:
    from anki.collection import Collection

# Re-export the gate so callers can read it from Readiness directly.
__all__ = ["readiness_score", "raw_to_scaled", "COVERAGE_GATE"]

# z for the 80% two-sided central interval (the house convention; matches Memory
# and Performance so every range is built the same way).
_Z_80 = 1.2816

# Number of answer choices on a PGRE item; random guessing is 1/this.
CHOICES_PER_QUESTION = 5
GUESS_BASELINE = 1.0 / CHOICES_PER_QUESTION

_REASON_ABSTAIN = "Not enough of the exam is covered yet"

# Human-readable statement of the raw-formula assumption, surfaced in the output.
_RAW_FORMULA_NOTE = (
    "expected raw assumes all questions attempted: "
    "raw = correct - (n - correct)/4, rounded and clamped to [0, 100]"
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _round_half_up(value: float) -> int:
    """Round to the nearest integer, halves up (the table's ``round(...)``).

    The raw axis is non-negative once clamped, so ``floor(x + 0.5)`` gives a
    deterministic round-half-up (Python's built-in ``round`` is banker's rounding,
    which would break exact ``.5`` boundaries).
    """
    return math.floor(value + 0.5)


# --- the table lookup (pure; the embedded Tier-3 constants) ------------------


def raw_to_scaled(raw: float) -> int:
    """Map a formula-scored raw to its PGRE scaled score via the official table.

    ``raw`` is rounded to the nearest integer and clamped to the table's raw
    domain ``[RAW_MIN, RAW_MAX]`` before lookup. The table is contiguous over that
    domain, so exactly one row matches. ``scaled`` is monotonic in ``raw``.
    """
    r = _round_half_up(_clamp(raw, float(RAW_MIN), float(RAW_MAX)))
    for raw_min, raw_max, scaled in RAW_TO_SCALED_TABLE:
        if raw_min <= r <= raw_max:
            return scaled
    # Unreachable: the table covers the whole clamped domain. Fail loudly if not.
    raise ValueError(f"raw {r} not covered by the conversion table")


# --- the raw math (pure; Poisson-binomial + the formula-scoring transform) ---


def poisson_binomial_stats(
    contributions: list[tuple[float, float]],
) -> tuple[float, float]:
    """Mean and variance of the total-correct Poisson-binomial.

    ``contributions`` is ``(n_t, p_t)`` per topic (``n_t`` questions each correct
    with independent probability ``p_t``). The total number correct has mean
    ``Sum n_t*p_t`` and variance ``Sum n_t*p_t*(1-p_t)`` (Le Cam). This is the
    sampling spread only; model uncertainty on ``p_t`` is added separately.
    """
    mean = sum(n * p for n, p in contributions)
    variance = sum(n * p * (1.0 - p) for n, p in contributions)
    return mean, variance


def correct_to_raw(
    correct: float, n_total: float, assume_all_attempted: bool = True
) -> float:
    """Convert an expected-*correct* count to the table's formula-scored raw.

    With ``assume_all_attempted`` (the default, matching this table's
    ``round(correct - incorrect/4)``): ``incorrect = n_total - correct`` and
    ``raw = 1.25*correct - 0.25*n_total``. The rights-only alternative
    (``assume_all_attempted=False``) returns ``correct`` unchanged. The result is
    the continuous raw *before* rounding/clamping (the caller does that).
    """
    if assume_all_attempted:
        return 1.25 * correct - 0.25 * n_total
    return correct


def project_scaled_score(
    contributions: list[tuple[float, float, float]],
    n_total: float,
    assume_all_attempted: bool = True,
    z: float = _Z_80,
) -> dict[str, Any]:
    """Project the scaled score + 80% interval from per-topic contributions.

    ``contributions`` is ``(n_t, p_t, p_sd_t)`` per topic, where ``p_sd_t`` is the
    model standard deviation on ``p_t`` (from the topic's Performance interval; 0
    for the guessing baseline). The total-correct variance combines the
    Poisson-binomial sampling term with the model term ``Sum (n_t*p_sd_t)^2``
    (topics independent; law of total variance). The point and the ``z``-scaled
    endpoints are mapped through the formula-scoring transform and the table.
    """
    sampling_pairs = [(n, p) for n, p, _ in contributions]
    mean_correct, var_sampling = poisson_binomial_stats(sampling_pairs)
    var_model = sum((n * p_sd) ** 2 for n, _, p_sd in contributions)
    sd_correct = math.sqrt(var_sampling + var_model)

    lo_correct = mean_correct - z * sd_correct
    hi_correct = mean_correct + z * sd_correct

    raw_point = correct_to_raw(mean_correct, n_total, assume_all_attempted)
    raw_low = correct_to_raw(lo_correct, n_total, assume_all_attempted)
    raw_high = correct_to_raw(hi_correct, n_total, assume_all_attempted)

    return {
        "expected_correct": mean_correct,
        "correct_sd": sd_correct,
        "raw": _round_half_up(_clamp(raw_point, float(RAW_MIN), float(RAW_MAX))),
        "raw_low": _round_half_up(_clamp(raw_low, float(RAW_MIN), float(RAW_MAX))),
        "raw_high": _round_half_up(_clamp(raw_high, float(RAW_MIN), float(RAW_MAX))),
        "scaled": raw_to_scaled(raw_point),
        "low": raw_to_scaled(raw_low),
        "high": raw_to_scaled(raw_high),
    }


# --- attempt-log / Performance -> per-topic contributions --------------------


def _topic_sd(entry: dict[str, Any]) -> float:
    """Model sd on ``p_t`` from a scored topic's 80% Performance interval.

    ``(high - low)`` is the 80% central width, so ``sd ~= width / (2*z)``. Returns
    0 when the topic has no interval (it is abstaining and will fall back to the
    guessing baseline, whose spread is captured by the sampling term).
    """
    low, high = entry.get("low"), entry.get("high")
    if low is None or high is None:
        return 0.0
    return (high - low) / (2.0 * _Z_80)


# --- the seam (three-scores.md §3) -------------------------------------------


def readiness_score(
    col: Collection,
    deck_id: int | None = None,
    k_perf: int = K_PERF_DEFAULT,
    coverage_gate: float = COVERAGE_GATE,
    exam_question_count: int = SCORED_QUESTION_COUNT,
    guess_baseline: float = GUESS_BASELINE,
    assume_all_attempted: bool = True,
) -> dict:
    """Return the Readiness score for the collection (projected scaled score).

    The result is JSON-serializable. When coverage clears the gate it carries the
    scaled ``point`` (as ``scaled``), the 80% ``low``/``high`` scaled interval, the
    underlying ``raw``/``raw_low``/``raw_high`` and ``expected_correct``,
    ``coverage_pct`` + ``coverage_gate``, ``abstain=False``, the documented
    ``raw_formula`` assumption, the topics filled with the guessing baseline in
    ``uncovered_topics``, and a per-topic ``by_topic`` breakdown. Below the gate it
    **abstains**: ``scaled``/``low``/``high``/``raw`` are ``None``, ``abstain`` is
    ``True``, ``reason`` explains, and ``uncovered_topics`` names what is missing.

    ``deck_id`` scopes only the mastery (FSRS) component of Performance; the
    attempt log is collection-wide. Everything is arithmetic over Performance + the
    blueprint + the embedded conversion constants: AI-off, no scheduling state read
    or written, no user-confidence captured.
    """
    perf = performance_score(col, deck_id=deck_id, k_perf=k_perf)

    contributions: list[tuple[float, float, float]] = []
    by_topic: list[dict[str, Any]] = []
    uncovered_topics: list[str] = []
    covered_weight = 0.0
    total_weight = 0.0

    for entry in perf["by_topic"]:
        category = entry["category"]
        blueprint = entry["blueprint"]
        n_attempts = entry["n_attempts"]
        n_questions = blueprint * exam_question_count
        total_weight += blueprint

        covered = n_attempts >= k_perf
        if covered:
            covered_weight += blueprint
        else:
            uncovered_topics.append(category)

        point = entry["point"]
        if point is not None:
            p_t = point
            p_sd = _topic_sd(entry)
            source = "performance"
        else:
            # Uncovered or too-imprecise: fall back to the guessing baseline so the
            # projection still spans this topic's questions (contributes ~0 raw
            # under formula scoring). Its uncertainty rides the sampling term.
            p_t = guess_baseline
            p_sd = 0.0
            source = "guess"

        contributions.append((n_questions, p_t, p_sd))
        by_topic.append(
            {
                "category": category,
                "blueprint": blueprint,
                "n_questions": n_questions,
                "p": p_t,
                "p_sd": p_sd,
                "n_attempts": n_attempts,
                "covered": covered,
                "source": source,
            }
        )

    coverage_pct = covered_weight / total_weight if total_weight else 0.0

    result: dict[str, Any] = {
        "coverage_pct": coverage_pct,
        "coverage_gate": coverage_gate,
        "k_perf": k_perf,
        "uncovered_topics": uncovered_topics,
        "raw_formula": RAW_SCORE_FORMULA,
        "raw_formula_note": _RAW_FORMULA_NOTE,
        "assume_all_attempted": assume_all_attempted,
        "guess_baseline": guess_baseline,
        "by_topic": by_topic,
        "last_updated": perf["last_updated"],
    }

    if coverage_pct < coverage_gate:
        result.update(
            {
                "scaled": None,
                "low": None,
                "high": None,
                "raw": None,
                "raw_low": None,
                "raw_high": None,
                "expected_correct": None,
                "abstain": True,
                "reason": _REASON_ABSTAIN,
            }
        )
        return result

    projection = project_scaled_score(
        contributions,
        n_total=float(exam_question_count),
        assume_all_attempted=assume_all_attempted,
    )
    result.update(
        {
            "scaled": projection["scaled"],
            "low": projection["low"],
            "high": projection["high"],
            "raw": projection["raw"],
            "raw_low": projection["raw_low"],
            "raw_high": projection["raw_high"],
            "expected_correct": projection["expected_correct"],
            "abstain": False,
            "reason": None,
        }
    )
    return result
