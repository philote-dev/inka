# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep Readiness score (L5.3).

Readiness is the projected PGRE **scaled score** (200-990) with an 80% range, an
explicit coverage, and an abstain when coverage is thin. It leans on Performance:
per-topic ``p_t`` -> expected raw (Poisson-binomial) -> scaled via the embedded
official conversion table, gated on coverage (``three-scores.md`` §3).

Most tests exercise the pure math directly (no Collection): the table lookup, the
Poisson-binomial mean/variance, the formula-scoring raw transform, and the 80%
interval propagation. A handful use a Collection fixture (mirroring
``test_pgrep_performance.py``) to cover the coverage-gate abstain and the empty-log
(n=1) reality.
"""

from __future__ import annotations

import inspect
import itertools
import time

from anki.pgrep import readiness, readiness_constants
from anki.pgrep.attempt_log import append_attempt
from anki.pgrep.blueprint import BLUEPRINT_PERCENT, CATEGORY_SLUGS
from anki.pgrep.coverage import COVERAGE_GATE
from anki.pgrep.performance import K_PERF_DEFAULT
from anki.pgrep.readiness import (
    GUESS_BASELINE,
    correct_to_raw,
    poisson_binomial_stats,
    project_scaled_score,
    raw_to_scaled,
    readiness_score,
)
from anki.pgrep.readiness_constants import (
    RAW_MAX,
    RAW_MIN,
    RAW_TO_SCALED_TABLE,
    SCORED_QUESTION_COUNT,
)
from tests.shared import getEmptyCol

_counter = itertools.count()


# --- embedded constants integrity (guards a bad regeneration) ----------------


def test_conversion_table_is_contiguous_and_monotonic():
    # 64 rows covering raw 0..100 with no gaps/overlaps, scaled strictly rising.
    assert len(RAW_TO_SCALED_TABLE) == 64
    rows = sorted(RAW_TO_SCALED_TABLE, key=lambda r: r[0])
    assert rows[0][0] == RAW_MIN == 0
    assert rows[-1][1] == RAW_MAX == 100
    prev_max = -1
    prev_scaled = -1
    for raw_min, raw_max, scaled in rows:
        assert raw_min == prev_max + 1  # contiguous, no gap or overlap
        assert raw_min <= raw_max
        assert scaled > prev_scaled  # strictly increasing with raw
        prev_max = raw_max
        prev_scaled = scaled


def test_scored_question_count_is_one_hundred():
    assert SCORED_QUESTION_COUNT == 100


# --- pure math: the table lookup at boundaries -------------------------------


def test_raw_to_scaled_at_row_boundaries():
    # Endpoints of representative rows map to their scaled value.
    assert raw_to_scaled(100) == 990
    assert raw_to_scaled(84) == 990  # bottom of the top (84..100) row
    assert raw_to_scaled(83) == 980
    assert raw_to_scaled(50) == 730  # inside the 49..50 row
    assert raw_to_scaled(49) == 730
    assert raw_to_scaled(38) == 640  # inside the 37..38 row
    assert raw_to_scaled(1) == 370
    assert raw_to_scaled(0) == 360


def test_raw_to_scaled_clamps_out_of_domain():
    # Below 0 clamps to the floor row (360); above 100 clamps to the ceiling (990).
    assert raw_to_scaled(-25) == 360
    assert raw_to_scaled(-1) == 360
    assert raw_to_scaled(101) == 990
    assert raw_to_scaled(500) == 990


def test_raw_to_scaled_rounds_half_up():
    # A continuous raw is rounded to the nearest integer (halves up) before lookup;
    # 37.5 -> 38 (the 37..38 row -> 640), 36.5 -> 37 (also 37..38 -> 640).
    assert raw_to_scaled(37.5) == 640
    assert raw_to_scaled(36.5) == 640
    assert raw_to_scaled(36.4) == 630  # rounds down to 36 (the 36..36 row)


def test_raw_to_scaled_is_monotonic_across_the_whole_domain():
    scaled = [raw_to_scaled(r) for r in range(RAW_MIN, RAW_MAX + 1)]
    assert scaled == sorted(scaled)
    assert scaled[0] == 360 and scaled[-1] == 990


# --- pure math: the Poisson-binomial mean/variance ---------------------------


def test_poisson_binomial_stats_single_topic():
    mean, var = poisson_binomial_stats([(10.0, 0.5)])
    assert abs(mean - 5.0) < 1e-12
    assert abs(var - 2.5) < 1e-12  # 10 * 0.5 * 0.5


def test_poisson_binomial_stats_sums_heterogeneous_topics():
    # A certain topic (p=1) adds to the mean but nothing to the variance.
    mean, var = poisson_binomial_stats([(20.0, 0.5), (10.0, 1.0)])
    assert abs(mean - 20.0) < 1e-12  # 10 + 10
    assert abs(var - 5.0) < 1e-12  # 20*0.25 + 10*0


def test_poisson_binomial_variance_is_zero_at_the_extremes():
    _, var0 = poisson_binomial_stats([(30.0, 0.0)])
    _, var1 = poisson_binomial_stats([(30.0, 1.0)])
    assert var0 == 0.0 and var1 == 0.0


# --- pure math: the formula-scoring raw transform ----------------------------


def test_correct_to_raw_all_attempted_matches_the_table_formula():
    # raw = correct - incorrect/4 = 1.25*correct - 0.25*n.
    assert correct_to_raw(100.0, 100.0) == 100.0  # all right
    assert correct_to_raw(50.0, 100.0) == 37.5  # half right -> formula raw 37.5
    assert correct_to_raw(20.0, 100.0) == 0.0  # 5-choice guessing -> ~0 raw
    assert correct_to_raw(0.0, 100.0) == -25.0  # all attempted, all wrong


def test_correct_to_raw_rights_only_alternative():
    # The documented alternative (post-2011 GRE convention): raw = correct.
    assert correct_to_raw(50.0, 100.0, assume_all_attempted=False) == 50.0
    assert correct_to_raw(20.0, 100.0, assume_all_attempted=False) == 20.0


def test_all_attempted_scores_a_guesser_lower_than_rights_only():
    # The core reason all-attempted is the faithful default: it penalizes guessing.
    guess_correct = GUESS_BASELINE * 100.0  # 20 expected correct
    formula = raw_to_scaled(correct_to_raw(guess_correct, 100.0))
    rights = raw_to_scaled(correct_to_raw(guess_correct, 100.0, False))
    assert formula < rights
    assert formula == 360  # guessing bottoms out under formula scoring


# --- pure math: the 80% interval propagation + monotonicity ------------------


def test_project_brackets_the_point_inside_its_interval():
    proj = project_scaled_score([(100.0, 0.5, 0.05)], n_total=100.0)
    assert proj["low"] <= proj["scaled"] <= proj["high"]
    assert proj["raw_low"] <= proj["raw"] <= proj["raw_high"]


def test_project_higher_p_gives_a_higher_scaled_score():
    lo = project_scaled_score([(100.0, 0.4, 0.0)], n_total=100.0)
    hi = project_scaled_score([(100.0, 0.6, 0.0)], n_total=100.0)
    assert hi["scaled"] > lo["scaled"]
    assert hi["expected_correct"] > lo["expected_correct"]


def test_project_guessing_floor_and_perfect_ceiling():
    floor = project_scaled_score([(100.0, GUESS_BASELINE, 0.0)], n_total=100.0)
    ceiling = project_scaled_score([(100.0, 1.0, 0.0)], n_total=100.0)
    assert floor["scaled"] == 360
    assert ceiling["scaled"] == 990
    assert ceiling["low"] == ceiling["high"] == 990  # no spread at p=1


def test_project_model_uncertainty_widens_the_interval():
    # Same point, but a larger per-topic model sd propagates to a wider scaled band
    # ("thin coverage widens it" — marginal topics carry wide Performance ranges).
    tight = project_scaled_score([(100.0, 0.5, 0.0)], n_total=100.0)
    wide = project_scaled_score([(100.0, 0.5, 0.1)], n_total=100.0)
    assert (wide["high"] - wide["low"]) > (tight["high"] - tight["low"])
    assert wide["scaled"] == tight["scaled"]  # the point is unchanged


def test_project_sampling_spread_alone_gives_a_real_interval():
    # Even with zero model uncertainty, exam randomness (Poisson-binomial) yields a
    # non-degenerate interval around a mid-range point.
    proj = project_scaled_score([(100.0, 0.5, 0.0)], n_total=100.0)
    assert proj["low"] < proj["scaled"] < proj["high"]


# --- Collection fixture helpers (mirror test_pgrep_performance.py) ------------


def _append_attempts(col, topic, results, *, difficulty=None, distinct=None):
    """Append clean attempts for ``topic``; ``results`` is a list of bools."""
    base = next(_counter) * 1000
    start = int(time.time()) - len(results) * 3600
    for i, correct in enumerate(results):
        item_offset = i % distinct if distinct else i
        event = {
            "topic": topic,
            "correct": bool(correct),
            "item_note_id": base + item_offset,
            "answered_at": start + i * 60,
            "ladder_depth": 0,
        }
        if difficulty is not None:
            event["difficulty"] = difficulty
        append_attempt(col, event)


def _cover(col, categories, results=None):
    """Give each category enough clean attempts to clear the Performance gate."""
    if results is None:
        results = [True, False, True, True, False, True, True, True]  # 8, 6 correct
    for category in categories:
        _append_attempts(col, f"topic::{category}::x", results)


# --- Collection integration: shape, coverage gate, abstain -------------------


def test_shape_has_score_range_coverage_and_assumptions():
    col = getEmptyCol()
    # Cover the five heaviest topics (0.71 of the blueprint) -> clears the gate.
    _cover(
        col, ["mechanics", "electromagnetism", "quantum", "thermodynamics", "atomic"]
    )

    data = readiness_score(col)

    for key in (
        "scaled",
        "low",
        "high",
        "raw",
        "raw_low",
        "raw_high",
        "expected_correct",
        "coverage_pct",
        "coverage_gate",
        "abstain",
        "reason",
        "uncovered_topics",
        "raw_formula",
        "assume_all_attempted",
        "by_topic",
    ):
        assert key in data, f"missing key: {key}"
    assert data["coverage_gate"] == COVERAGE_GATE
    assert data["assume_all_attempted"] is True
    assert [t["category"] for t in data["by_topic"]] == list(CATEGORY_SLUGS)


def test_covered_profile_produces_a_scaled_score_with_a_range():
    col = getEmptyCol()
    covered = ["mechanics", "electromagnetism", "quantum", "thermodynamics", "atomic"]
    _cover(col, covered)

    data = readiness_score(col)

    assert data["abstain"] is False
    assert data["reason"] is None
    # A real scaled point in the band, with a bracketing 80% range.
    assert 360 <= data["scaled"] <= 990
    assert data["low"] <= data["scaled"] <= data["high"]
    # Coverage is the blueprint weight of topics with >= k_perf attempts (0.71).
    assert abs(data["coverage_pct"] - 0.71) < 1e-9
    assert data["coverage_pct"] >= data["coverage_gate"]
    # The uncovered minority is still named honestly (filled with the guess base).
    assert set(data["uncovered_topics"]) == {
        "optics_waves",
        "special_relativity",
        "lab",
        "specialized",
    }


def test_below_gate_abstains_and_names_uncovered_topics():
    col = getEmptyCol()
    # Cover only 0.61 of the blueprint (mechanics+em+quantum+thermo) -> below 0.70.
    _cover(col, ["mechanics", "electromagnetism", "quantum", "thermodynamics"])

    data = readiness_score(col)

    assert data["abstain"] is True
    assert data["reason"] == "Not enough of the exam is covered yet"
    assert data["scaled"] is None
    assert data["low"] is None and data["high"] is None
    assert data["raw"] is None
    assert data["coverage_pct"] < data["coverage_gate"]
    # Names exactly the topics that lack enough scored attempts.
    assert set(data["uncovered_topics"]) == {
        "atomic",
        "optics_waves",
        "special_relativity",
        "lab",
        "specialized",
    }


def test_empty_collection_abstains_everywhere():
    # The n=1 reality: with no attempt log, coverage is 0 and Readiness abstains,
    # naming every blueprint topic as uncovered.
    col = getEmptyCol()

    data = readiness_score(col)

    assert data["abstain"] is True
    assert data["scaled"] is None
    assert data["coverage_pct"] == 0.0
    assert data["last_updated"] is None
    assert set(data["uncovered_topics"]) == set(CATEGORY_SLUGS)


def test_readiness_coverage_is_attempts_based_not_memory_based():
    col = getEmptyCol()
    # Clear the gate with attempts on the five heaviest topics...
    _cover(
        col, ["mechanics", "electromagnetism", "quantum", "thermodynamics", "atomic"]
    )
    # ...then give 'lab' plenty of reviewed cards but too few scored attempts.
    _append_attempts(col, "topic::lab::instruments", [True] * (K_PERF_DEFAULT - 1))

    data = readiness_score(col)
    lab = next(t for t in data["by_topic"] if t["category"] == "lab")

    # Memory coverage would count 'lab' (it has attempts/cards), but Readiness
    # coverage requires >= k_perf scored attempts, so 'lab' stays uncovered.
    assert lab["covered"] is False
    assert lab["source"] == "guess"
    assert "lab" in data["uncovered_topics"]


def test_more_correct_attempts_score_higher_end_to_end():
    strong = getEmptyCol()
    weak = getEmptyCol()
    covered = ["mechanics", "electromagnetism", "quantum", "thermodynamics", "atomic"]
    _cover(strong, covered, results=[True] * (K_PERF_DEFAULT + 2))
    _cover(weak, covered, results=[False] * (K_PERF_DEFAULT + 2))

    strong_data = readiness_score(strong)
    weak_data = readiness_score(weak)

    assert strong_data["abstain"] is False and weak_data["abstain"] is False
    assert strong_data["scaled"] > weak_data["scaled"]


def test_by_topic_reports_the_per_topic_projection_inputs():
    col = getEmptyCol()
    _cover(
        col, ["mechanics", "electromagnetism", "quantum", "thermodynamics", "atomic"]
    )

    data = readiness_score(col)
    mech = next(t for t in data["by_topic"] if t["category"] == "mechanics")

    assert mech["covered"] is True
    assert mech["source"] == "performance"
    assert 0.0 < mech["p"] < 1.0
    # n_questions is blueprint% * 100 (mechanics 0.20 -> 20 questions).
    assert abs(mech["n_questions"] - BLUEPRINT_PERCENT["mechanics"] * 100) < 1e-9


# --- AI-off by construction --------------------------------------------------


def test_ai_off_no_ai_or_heavy_imports():
    # The scoring path is pure arithmetic over Performance + embedded constants.
    # Guard against any AI/network/heavy-numeric import in the shipped modules
    # (AI-off + plain-Python by construction; three-scores.md §0).
    forbidden = (
        "pgrep.ai",
        "import openai",
        "import anthropic",
        "import httpx",
        "import requests",
        "import torch",
        "import numpy",
        "import pandas",
        "import scipy",
        "urllib",
    )
    for module in (readiness, readiness_constants):
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source, (
                f"unexpected import {token} in {module.__name__}"
            )


def test_readiness_does_not_reference_the_private_content_root_at_runtime():
    # "Constants only": the shipped scoring path must not read content/ (gitignored,
    # absent in the shipped app). The numeric table is embedded, so the runtime
    # module never touches a private root.
    source = inspect.getsource(readiness)
    assert "content/tier3" not in source
    assert "open(" not in source
    assert "json.load" not in source
