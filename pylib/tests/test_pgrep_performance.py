# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep Performance score (L5.2).

Performance is the honest ``P(correct on a new, unseen exam-style problem)``
signal: a calibrated PFA logistic over mastery (FSRS R), item difficulty, and
recent successes/failures, with an 80% Bayesian interval and a precision-based
abstain. It is pure math over the attempt log + FSRS + the authored difficulty
tag: no AI, no schedule mutation.

Most tests exercise the pure math directly (no Collection). A handful use a
Collection fixture (mirroring ``test_pgrep_memory.py``) to cover the attempt-log
plumbing, the range/abstain behavior, and the empty-log (n=1) reality.

The math is fixed by ``performance-model.md``; the response shape mirrors Memory
(``three-scores.md`` §2).
"""

from __future__ import annotations

import inspect
import itertools
import time

from anki import cards_pb2
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki.pgrep import performance
from anki.pgrep.attempt_log import append_attempt
from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.performance import (
    DEFAULT_CALIBRATION,
    DEFAULT_COEFFICIENTS,
    K_PERF_DEFAULT,
    BetaCalibration,
    PFACoefficients,
    _beta_interval,
    _beta_ppf,
    _betainc,
    _sigmoid,
    performance_probability,
    performance_score,
)
from tests.shared import getEmptyCol

_counter = itertools.count()


# --- pure math: logistic + beta calibration ---------------------------------


def test_sigmoid_known_values():
    assert _sigmoid(0.0) == 0.5
    assert abs(_sigmoid(2.0) + _sigmoid(-2.0) - 1.0) < 1e-12  # symmetry
    assert 0.0 < _sigmoid(-50.0) < 1e-9  # overflow-safe, no exception
    assert 1.0 - 1e-9 < _sigmoid(50.0) <= 1.0


def test_beta_calibration_contains_the_identity():
    # Beta calibration with a=1, b=1, c=0 is the identity map (Kull et al. 2017:
    # "contains the identity", so an already-calibrated model is left alone).
    identity = BetaCalibration(a=1.0, b=1.0, c=0.0)
    for s in (0.05, 0.3, 0.5, 0.72, 0.95):
        assert abs(identity.calibrate(s) - s) < 1e-9


def test_beta_calibration_shifts_probabilities():
    # A positive intercept pushes probabilities up; the map stays in (0, 1).
    cal = BetaCalibration(a=1.0, b=1.0, c=1.0)
    for s in (0.1, 0.4, 0.8):
        out = cal.calibrate(s)
        assert 0.0 < out < 1.0
        assert out > s


def test_performance_probability_in_unit_interval():
    for mastery in (0.0, 0.5, 1.0):
        for difficulty in (1.0, 3.0, 5.0):
            for succ, fail in ((0, 0), (8, 0), (0, 8), (4, 4)):
                p = performance_probability(mastery, difficulty, succ, fail)
                assert 0.0 < p < 1.0


# --- pure math: the incomplete beta + its inverse (interval engine) ----------


def test_betainc_known_values():
    # I_x(1,1) = x (uniform CDF); I_0.5(2,3) = 0.6875 (exact).
    assert abs(_betainc(0.5, 1.0, 1.0) - 0.5) < 1e-9
    assert abs(_betainc(0.3, 1.0, 1.0) - 0.3) < 1e-9
    assert abs(_betainc(0.5, 2.0, 3.0) - 0.6875) < 1e-9
    assert _betainc(0.0, 2.0, 3.0) == 0.0
    assert _betainc(1.0, 2.0, 3.0) == 1.0


def test_beta_ppf_inverts_betainc():
    assert abs(_beta_ppf(0.1, 1.0, 1.0) - 0.1) < 1e-6
    assert abs(_beta_ppf(0.5, 2.0, 2.0) - 0.5) < 1e-6
    for q, a, b in ((0.1, 6.1, 2.9), (0.9, 6.1, 2.9), (0.5, 8.1, 0.9)):
        x = _beta_ppf(q, a, b)
        assert abs(_betainc(x, a, b) - q) < 1e-6


def test_beta_interval_brackets_point_and_tightens_with_evidence():
    point = 0.7
    lo_thin, hi_thin = _beta_interval(point, n_eff=4.0)
    lo_rich, hi_rich = _beta_interval(point, n_eff=200.0)
    # Always a real, ordered interval inside [0, 1] that brackets the point.
    for lo, hi in ((lo_thin, hi_thin), (lo_rich, hi_rich)):
        assert 0.0 <= lo <= point <= hi <= 1.0
    # More evidence -> a tighter interval.
    assert (hi_rich - lo_rich) < (hi_thin - lo_thin)


# --- pure math: monotonicity (the interpretable coefficients) ----------------


def test_higher_mastery_raises_probability():
    low = performance_probability(0.2, 3.0, 3, 3)
    high = performance_probability(0.9, 3.0, 3, 3)
    assert high > low


def test_more_recent_successes_raise_probability():
    fewer = performance_probability(0.5, 3.0, 1, 3)
    more = performance_probability(0.5, 3.0, 6, 3)
    assert more > fewer


def test_more_recent_failures_lower_probability():
    fewer = performance_probability(0.5, 3.0, 3, 1)
    more = performance_probability(0.5, 3.0, 3, 6)
    assert more < fewer


def test_harder_difficulty_lowers_probability():
    easy = performance_probability(0.5, 1.0, 3, 3)
    hard = performance_probability(0.5, 5.0, 3, 3)
    assert hard < easy


def test_default_coefficients_have_the_designed_signs():
    # The shipped defaults must keep the interpretable directions (a bad re-fit
    # that flips a sign would break the whole "reasons" story).
    assert DEFAULT_COEFFICIENTS.b_mastery > 0
    assert DEFAULT_COEFFICIENTS.b_difficulty > 0  # subtracted -> harder lowers P
    assert DEFAULT_COEFFICIENTS.g_success > 0
    assert DEFAULT_COEFFICIENTS.g_failure < 0
    assert isinstance(DEFAULT_CALIBRATION, BetaCalibration)


# --- Collection fixture helpers (mirror test_pgrep_memory.py) ----------------


def _add_reviewed_card(col, topic, *, stability=40.0, difficulty=5.0, days_ago=10):
    """Add one card with real FSRS memory state so the topic carries mastery."""
    note = col.newNote()
    note["Front"] = f"q{next(_counter)}"
    if topic:
        note.tags = [topic]
    col.addNote(note)
    card = note.cards()[0]
    card.type = CARD_TYPE_REV
    card.queue = QUEUE_TYPE_REV
    card.due = 0
    card.ivl = max(1, int(stability))
    card.memory_state = cards_pb2.FsrsMemoryState(
        stability=stability, difficulty=difficulty
    )
    card.last_review_time = int(time.time()) - days_ago * 86400
    col.update_card(card)
    return card


def _add_mastery(col, topic, n=5, **kwargs):
    for _ in range(n):
        _add_reviewed_card(col, topic, **kwargs)


def _append_attempts(col, topic, results, *, difficulty=None):
    """Append clean attempts for ``topic``; ``results`` is a list of bools.

    Each attempt gets a distinct ``item_note_id`` (so topic coverage is full) and
    an increasing ``answered_at`` (so the recency window is well ordered).
    """
    base = next(_counter) * 1000
    start = int(time.time()) - len(results) * 3600
    for i, correct in enumerate(results):
        event = {
            "topic": topic,
            "correct": bool(correct),
            "item_note_id": base + i,
            "answered_at": start + i * 60,
            "ladder_depth": 0,
        }
        if difficulty is not None:
            event["difficulty"] = difficulty
        append_attempt(col, event)


def _topic(data: dict, category: str) -> dict:
    return next(t for t in data["by_topic"] if t["category"] == category)


# --- Collection integration: shape, range, abstain ---------------------------


def test_shape_matches_contract():
    col = getEmptyCol()
    _add_mastery(col, "topic::mechanics::kinematics")
    _append_attempts(col, "topic::mechanics::kinematics", [True] * K_PERF_DEFAULT)

    data = performance_score(col)

    assert set(data) == {
        "overall",
        "by_topic",
        "k_perf",
        "coverage_pct",
        "coverage_gate",
        "last_updated",
    }
    assert data["k_perf"] == K_PERF_DEFAULT
    assert set(data["overall"]) == {"point", "low", "high", "abstain", "reason"}
    assert [t["category"] for t in data["by_topic"]] == list(CATEGORY_SLUGS)
    for entry in data["by_topic"]:
        assert set(entry) == {
            "category",
            "blueprint",
            "point",
            "low",
            "high",
            "n_attempts",
            "abstain",
            "reason",
        }


def test_topic_with_enough_attempts_scores_with_a_range():
    col = getEmptyCol()
    _add_mastery(col, "topic::mechanics::kinematics")
    _append_attempts(
        col, "topic::mechanics::kinematics", [True, False] * K_PERF_DEFAULT
    )

    mech = _topic(performance_score(col), "mechanics")

    assert mech["abstain"] is False
    assert mech["reason"] is None
    assert mech["n_attempts"] == 2 * K_PERF_DEFAULT
    # A real point in (0, 1) with a bracketing 80% range inside [0, 1].
    assert 0.0 < mech["point"] < 1.0
    assert 0.0 <= mech["low"] <= mech["point"] <= mech["high"] <= 1.0
    assert mech["low"] < mech["high"]


def test_range_is_always_present_when_scored():
    col = getEmptyCol()
    _add_mastery(col, "topic::quantum::spin")
    _append_attempts(col, "topic::quantum::spin", [True] * (K_PERF_DEFAULT + 4))

    quantum = _topic(performance_score(col), "quantum")

    assert quantum["abstain"] is False
    assert quantum["low"] is not None and quantum["high"] is not None


def test_topic_below_threshold_abstains():
    col = getEmptyCol()
    _add_mastery(col, "topic::quantum::spin")
    _append_attempts(col, "topic::quantum::spin", [True] * (K_PERF_DEFAULT - 1))

    quantum = _topic(performance_score(col), "quantum")

    assert quantum["n_attempts"] == K_PERF_DEFAULT - 1
    assert quantum["abstain"] is True
    assert quantum["point"] is None
    assert quantum["low"] is None
    assert quantum["high"] is None
    assert quantum["reason"] == "Not enough attempts yet"


def test_empty_collection_abstains_everywhere():
    # The n=1 reality: with no attempt log, the model abstains everywhere. This is
    # correct behavior and is demonstrated here.
    col = getEmptyCol()

    data = performance_score(col)

    assert data["overall"]["abstain"] is True
    assert data["overall"]["point"] is None
    assert data["last_updated"] is None
    assert all(t["abstain"] and t["n_attempts"] == 0 for t in data["by_topic"])


def test_k_perf_is_a_parameter():
    col = getEmptyCol()
    _add_mastery(col, "topic::quantum::spin")
    _append_attempts(col, "topic::quantum::spin", [True, False, True, False, True])

    assert _topic(performance_score(col), "quantum")["abstain"] is True
    # Lowering the threshold lets the same topic score.
    scored = _topic(performance_score(col, k_perf=5), "quantum")
    assert scored["abstain"] is False
    assert scored["point"] is not None


def test_coverage_is_exposed_honestly():
    col = getEmptyCol()
    data = performance_score(col)
    assert 0.0 <= data["coverage_pct"] <= 1.0
    assert data["coverage_gate"] == performance.COVERAGE_GATE


# --- Collection integration: monotonicity end-to-end ------------------------


def test_more_successes_scores_higher_than_more_failures():
    col = getEmptyCol()
    # Same mastery, same (absent) difficulty; only the win/loss record differs.
    _add_mastery(col, "topic::mechanics::kinematics")
    _add_mastery(col, "topic::electromagnetism::circuits")
    _append_attempts(col, "topic::mechanics::kinematics", [True] * K_PERF_DEFAULT)
    _append_attempts(col, "topic::electromagnetism::circuits", [False] * K_PERF_DEFAULT)

    data = performance_score(col)
    winners = _topic(data, "mechanics")
    losers = _topic(data, "electromagnetism")

    assert winners["abstain"] is False and losers["abstain"] is False
    assert winners["point"] > losers["point"]


def test_harder_authored_difficulty_scores_lower_end_to_end():
    col = getEmptyCol()
    _add_mastery(col, "topic::mechanics::kinematics")
    _add_mastery(col, "topic::quantum::spin")
    # Identical records; only the authored difficulty tag on the attempts differs.
    _append_attempts(
        col, "topic::mechanics::kinematics", [True] * K_PERF_DEFAULT, difficulty=1
    )
    _append_attempts(col, "topic::quantum::spin", [True] * K_PERF_DEFAULT, difficulty=5)

    data = performance_score(col)
    easy = _topic(data, "mechanics")
    hard = _topic(data, "quantum")

    assert easy["abstain"] is False and hard["abstain"] is False
    assert easy["point"] > hard["point"]


# --- AI-off by construction --------------------------------------------------


def test_ai_off_no_ai_imports():
    # The scoring path is pure arithmetic. Guard against any AI / network import
    # sneaking into the shipped module (AI-off by construction; three-scores.md §0).
    source = inspect.getsource(performance)
    forbidden = (
        "pgrep.ai",
        "import openai",
        "import anthropic",
        "import httpx",
        "import requests",
        "import torch",
        "urllib",
    )
    for token in forbidden:
        assert token not in source, f"unexpected AI/network import: {token}"


def test_scoring_a_topic_does_not_touch_custom_coefficients():
    # Passing custom coefficients changes the point (they are real config, not
    # hidden magic), proving the coefficients are a tunable seam.
    strong = PFACoefficients(
        b0=0.0, b_mastery=5.0, b_difficulty=0.0, g_success=0.0, g_failure=0.0
    )
    weak = PFACoefficients(
        b0=0.0, b_mastery=-5.0, b_difficulty=0.0, g_success=0.0, g_failure=0.0
    )
    hi = performance_probability(0.9, 3.0, 0, 0, coefficients=strong)
    lo = performance_probability(0.9, 3.0, 0, 0, coefficients=weak)
    assert hi > 0.9 > lo
