"""Unit tests for the ablation simulation's pure helpers (L5.4).

These lock down two things before any simulation runs.

1. The FSRS-style ground-truth memory model (power forgetting curve, stability
   and difficulty updates) matches the crate's equations and default parameters.
2. The "full" arm's scorer reproduces the shipped selector in
   ``rslib/src/scheduler/queue/builder/points_at_stake.rs`` exactly. Several
   cases below are direct ports of that file's Rust unit tests, so a drift in
   worth, weakness, the desirable-difficulty band, or anti-blocking fails here.

Run:
    conda run -n pgrep-ai --no-capture-output python -m pytest \
        content/tools/test_ablation.py -q
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import ablation as ab


def approx(a: float, b: float, tol: float = 1e-9) -> None:
    assert abs(a - b) < tol, f"{a} != {b} (tol {tol})"


# --- forgetting curve -------------------------------------------------------


def test_power_curve_anchor_points():
    # R(0, S) = 1 for any stability.
    approx(ab.retrievability(0.0, 5.0), 1.0)
    approx(ab.retrievability(0.0, 100.0), 1.0)
    # By construction R(t=S) = 0.9 for any stability and decay. This is the
    # defining anchor of the FSRS power forgetting curve.
    approx(ab.retrievability(5.0, 5.0), 0.9, tol=1e-6)
    approx(ab.retrievability(100.0, 100.0), 0.9, tol=1e-6)


def test_power_curve_is_monotone_decreasing():
    s = 10.0
    rs = [ab.retrievability(t, s) for t in range(0, 200, 5)]
    assert all(later <= earlier for earlier, later in zip(rs, rs[1:]))
    assert rs[-1] < rs[0]


def test_factor_matches_crate_formula():
    # factor = 0.9 ** (1 / decay_exp) - 1, with decay_exp the negative exponent.
    expected = 0.9 ** (1.0 / ab.DECAY_EXP) - 1.0
    approx(ab.FACTOR, expected, tol=1e-12)


def test_next_interval_round_trips_desired_retention():
    # An interval chosen for retention 0.9 equals the stability itself, and the
    # curve returns exactly 0.9 after that interval.
    for s in (1.0, 3.5, 42.0):
        approx(ab.next_interval(s, 0.9), s, tol=1e-6)
        approx(ab.retrievability(ab.next_interval(s, 0.9), s), 0.9, tol=1e-6)
    # A stricter target yields a shorter interval.
    assert ab.next_interval(10.0, 0.95) < ab.next_interval(10.0, 0.9)


# --- FSRS state updates -----------------------------------------------------


def test_init_stability_reads_first_four_params():
    approx(ab.init_stability(1), ab.W[0])
    approx(ab.init_stability(2), ab.W[1])
    approx(ab.init_stability(3), ab.W[2])
    approx(ab.init_stability(4), ab.W[3])


def test_init_difficulty_values_and_clamp():
    # D0(rating) = w4 - exp(w5 (rating - 1)) + 1, clamped to [1, 10].
    approx(ab.init_difficulty(1), ab.W[4] - math.exp(0.0) + 1.0, tol=1e-6)
    approx(ab.init_difficulty(3), ab.W[4] - math.exp(ab.W[5] * 2) + 1.0, tol=1e-6)
    # Easy start underflows and clamps to the floor.
    approx(ab.init_difficulty(4), 1.0, tol=1e-9)


def test_stability_after_success_known_value_and_monotonicity():
    # Independently computed from the crate equation with default parameters.
    got = ab.stability_after_success(2.3065, 2.1184, 0.9, rating=3)
    approx(got, 11.9096, tol=1e-2)
    # Success never lowers stability.
    assert got > 2.3065
    # A lower retrievability at review yields a larger stability gain.
    low_r = ab.stability_after_success(5.0, 5.0, 0.70, rating=3)
    high_r = ab.stability_after_success(5.0, 5.0, 0.95, rating=3)
    assert low_r > high_r


def test_stability_after_failure_known_value_and_drop():
    got = ab.stability_after_failure(11.9096, 2.1184, 0.9)
    approx(got, 1.6029, tol=1e-2)
    # Failure reduces stability.
    assert got < 11.9096


def test_update_memory_success_grows_failure_shrinks():
    s0, d0 = 5.0, 5.0
    s_ok, _ = ab.update_memory(s0, d0, elapsed_days=5.0, success=True)
    s_no, d_no = ab.update_memory(s0, d0, elapsed_days=5.0, success=False)
    assert s_ok > s0
    assert s_no < s0
    # A lapse makes the card harder.
    assert d_no > d0
    # Stability stays within the FSRS clamps.
    assert ab.S_MIN <= s_ok <= ab.S_MAX


# --- selector fidelity: blueprint, band, worth, weakness --------------------


def test_blueprint_table_matches_selector():
    # The nine PGRE blueprint weights, duplicated from points_at_stake.rs.
    approx(ab.blueprint_weight("mechanics"), 0.20)
    approx(ab.blueprint_weight("electromagnetism"), 0.18)
    approx(ab.blueprint_weight("quantum"), 0.13)
    approx(ab.blueprint_weight("thermodynamics"), 0.10)
    approx(ab.blueprint_weight("atomic"), 0.10)
    approx(ab.blueprint_weight("optics_waves"), 0.08)
    approx(ab.blueprint_weight("special_relativity"), 0.06)
    approx(ab.blueprint_weight("lab"), 0.06)
    approx(ab.blueprint_weight("specialized"), 0.09)
    approx(ab.blueprint_weight("unknown"), 0.0)
    # The nine categories are a partition of the exam (weights sum to 1).
    approx(sum(ab.blueprint_weight(c) for c in ab.CATEGORIES), 1.0, tol=1e-9)


def test_band_factor_boundaries():
    # Ported from points_at_stake.rs::band_factor_boundaries.
    approx(ab.band_factor(0.60), 1.0)
    approx(ab.band_factor(0.85), 1.0)
    approx(ab.band_factor(0.75), 1.0)
    approx(ab.band_factor(0.5999), ab.OUT_OF_BAND_FACTOR)
    approx(ab.band_factor(0.8501), ab.OUT_OF_BAND_FACTOR)
    # Unknown retrievability is treated as out of band.
    approx(ab.band_factor(None), ab.OUT_OF_BAND_FACTOR)
    approx(ab.band_factor(float("nan")), ab.OUT_OF_BAND_FACTOR)


def test_worth_and_weakness_port_from_rust():
    # Ported from points_at_stake.rs::scoring_worth_and_band.
    inputs = [
        {"id": 1, "gather_index": 0, "category": "mechanics",
         "topic": "topic::mechanics::a", "blueprint": 0.20, "r": 0.5},
        {"id": 2, "gather_index": 1, "category": "mechanics",
         "topic": "topic::mechanics::a", "blueprint": 0.20, "r": 0.7},
        {"id": 3, "gather_index": 2, "category": "quantum",
         "topic": "topic::quantum::b", "blueprint": 0.13, "r": 0.9},
    ]
    weakness = ab.weakness_by_topic(inputs)
    approx(weakness["topic::mechanics::a"], 0.4)   # 1 - mean(0.5, 0.7)
    approx(weakness["topic::quantum::b"], 0.1)     # 1 - 0.9

    approx(ab.worth(0.20, weakness["topic::mechanics::a"]), 0.20 * 0.4)
    approx(ab.worth(0.13, weakness["topic::quantum::b"]), 0.13 * 0.1)
    assert ab.worth(0.20, 0.4) > ab.worth(0.13, 0.1)

    scored = {s["id"]: s for s in ab.score_inputs(inputs)}
    # Band factor separates the two mechanics cards: R=0.5 out, R=0.7 in.
    approx(scored[1]["score"], ab.worth(0.20, 0.4) * ab.OUT_OF_BAND_FACTOR)
    approx(scored[2]["score"], ab.worth(0.20, 0.4))
    approx(scored[3]["score"], ab.worth(0.13, 0.1) * ab.OUT_OF_BAND_FACTOR)


def test_topic_with_no_defined_r_has_zero_weakness():
    # Mirrors the selector: a topic we cannot read R for cannot be called weak.
    inputs = [
        {"id": 1, "gather_index": 0, "category": "lab",
         "topic": "topic::lab::x", "blueprint": 0.06, "r": None},
    ]
    scored = ab.score_inputs(inputs)
    approx(scored[0]["score"], 0.0)


# --- selector fidelity: anti-blocking and truncation ------------------------


def _max_run(cats: list[str]) -> int:
    best = run = 0
    prev = None
    for c in cats:
        run = run + 1 if c == prev else 1
        prev = c
        best = max(best, run)
    return best


def test_anti_blocking_caps_runs_at_three():
    # Ported from points_at_stake.rs::anti_blocking_caps_runs.
    cards = [
        {"id": 1, "gather_index": 0, "category": "mechanics", "score": 10.0},
        {"id": 2, "gather_index": 1, "category": "mechanics", "score": 9.0},
        {"id": 3, "gather_index": 2, "category": "mechanics", "score": 8.0},
        {"id": 4, "gather_index": 3, "category": "mechanics", "score": 7.0},
        {"id": 5, "gather_index": 4, "category": "electromagnetism", "score": 6.0},
        {"id": 6, "gather_index": 5, "category": "electromagnetism", "score": 5.0},
    ]
    ordered = ab.anti_block_order(cards)
    cats = [c["category"] for c in ordered]
    assert _max_run(cats) <= ab.MAX_CONSECUTIVE_SAME_CATEGORY
    # A lower-scored different-category card is pulled up to break the run.
    assert ordered[3]["category"] == "electromagnetism"


def test_in_band_card_ordered_before_equal_worth_out_of_band():
    # Ported from points_at_stake.rs::in_band_preferred_over_equal_worth.
    inputs = [
        {"id": 1, "gather_index": 0, "category": "mechanics",
         "topic": "topic::mechanics::x", "blueprint": 0.20, "r": 0.70},
        {"id": 2, "gather_index": 1, "category": "mechanics",
         "topic": "topic::mechanics::x", "blueprint": 0.20, "r": 0.95},
    ]
    scored = ab.score_inputs(inputs)
    ordered = ab.anti_block_order(scored)
    assert ordered[0]["id"] == 1


def test_truncation_keeps_top_scores_not_gather_order():
    # Ported from points_at_stake.rs::truncation_keeps_top_scores_not_gather_order.
    cards = [
        {"id": 1, "gather_index": 0, "category": "mechanics", "score": 1.0},
        {"id": 2, "gather_index": 1, "category": "electromagnetism", "score": 2.0},
        {"id": 3, "gather_index": 2, "category": "quantum", "score": 3.0},
        {"id": 4, "gather_index": 3, "category": "thermodynamics", "score": 4.0},
        {"id": 5, "gather_index": 4, "category": "atomic", "score": 5.0},
        {"id": 6, "gather_index": 5, "category": "lab", "score": 6.0},
    ]
    kept = [c["id"] for c in ab.select_top_n(cards, 3)]
    assert kept == [6, 5, 4]


# --- vectorised scorer matches the reference implementation -----------------


def test_vectorised_scores_match_reference():
    # The simulation's fast numpy scorer must equal the scalar reference port
    # of the selector on a random due set, so the fast path cannot silently
    # drift from points_at_stake.rs.
    rng = np.random.default_rng(7)
    n = 60
    n_groups = 9
    group = rng.integers(0, n_groups, size=n)
    r = rng.uniform(0.3, 0.99, size=n)
    blueprint = rng.choice([0.20, 0.18, 0.13, 0.10, 0.06], size=n)

    fast = ab.score_vectorised(group, r, blueprint, n_groups)

    inputs = []
    for i in range(n):
        inputs.append({
            "id": i, "gather_index": i, "category": str(group[i]),
            "topic": f"topic::{group[i]}", "blueprint": float(blueprint[i]),
            "r": float(r[i]),
        })
    ref = {s["id"]: s["score"] for s in ab.score_inputs(inputs)}
    ref_arr = np.array([ref[i] for i in range(n)])
    assert np.allclose(fast, ref_arr, atol=1e-12)


# --- the pre-stated primary metric ------------------------------------------


def test_blueprint_weighted_recall_full_coverage_equals_weighted_mean():
    # With every category present at recall r, BWER = r (weights sum to 1).
    r_by_card = {}
    cat_by_card = {}
    cid = 0
    for c in ab.CATEGORIES:
        for _ in range(3):
            r_by_card[cid] = 0.8
            cat_by_card[cid] = c
            cid += 1
    categories = np.array([ab.CATEGORIES.index(cat_by_card[i]) for i in range(cid)])
    r = np.array([r_by_card[i] for i in range(cid)])
    approx(ab.blueprint_weighted_recall(categories, r), 0.8, tol=1e-9)


def test_blueprint_weighted_recall_missing_categories_score_zero():
    # Only mechanics (0.20) and quantum (0.13) covered. Uncovered areas count 0.
    categories = np.array([
        ab.CATEGORIES.index("mechanics"),
        ab.CATEGORIES.index("mechanics"),
        ab.CATEGORIES.index("quantum"),
    ])
    r = np.array([0.8, 0.6, 0.9])
    expected = 0.20 * 0.7 + 0.13 * 0.9
    approx(ab.blueprint_weighted_recall(categories, r), expected, tol=1e-9)


# --- vectorised memory update matches the scalar reference (I2) --------------


def test_update_memory_vec_matches_scalar_success_and_lapse():
    # _update_memory_vec is the workhorse (warmup and every review). Pin it to
    # the scalar update_memory / stability_after_success / stability_after_failure
    # reference across many random states, for BOTH success and lapse.
    rng = np.random.default_rng(101)
    n = 800
    S = rng.uniform(ab.S_MIN, 250.0, size=n)
    D = rng.uniform(ab.D_MIN, ab.D_MAX, size=n)
    elapsed = rng.uniform(1.0, 500.0, size=n)
    success = rng.random(n) < 0.6

    vec_s, vec_d = ab._update_memory_vec(S, D, elapsed, success)
    scal_s = np.empty(n)
    scal_d = np.empty(n)
    for i in range(n):
        scal_s[i], scal_d[i] = ab.update_memory(
            float(S[i]), float(D[i]), float(elapsed[i]), bool(success[i]))

    # Both branches must be exercised, else the test proves nothing.
    assert success.any() and (~success).any()
    assert np.allclose(vec_s, scal_s, rtol=1e-9, atol=1e-12)
    assert np.allclose(vec_d, scal_d, rtol=1e-9, atol=1e-12)


def test_update_memory_vec_matches_scalar_all_success_and_all_lapse():
    # Cover the homogeneous batches used by warmup (all success) and a pure lapse
    # batch, so the np.where branch selection cannot hide a bug.
    rng = np.random.default_rng(202)
    n = 300
    S = rng.uniform(ab.S_MIN, 100.0, size=n)
    D = rng.uniform(ab.D_MIN, ab.D_MAX, size=n)
    elapsed = rng.uniform(1.0, 200.0, size=n)
    for flag in (True, False):
        success = np.full(n, flag)
        vec_s, vec_d = ab._update_memory_vec(S, D, elapsed, success)
        for i in range(n):
            ss, sd = ab.update_memory(float(S[i]), float(D[i]), float(elapsed[i]), flag)
            approx(float(vec_s[i]), ss, tol=1e-9 + 1e-9 * abs(ss))
            approx(float(vec_d[i]), sd, tol=1e-9 + 1e-9 * abs(sd))


# --- the executed selection path is the tested path (I1) ---------------------


def test_deterministic_top_n_matches_reference_selector():
    # The runtime selection primitive must equal the Rust-ported select_top_n
    # (score desc, gather_index asc, id asc), including under heavy ties (scores
    # quantised to 2 decimals so many cards share a score at the boundary).
    rng = np.random.default_rng(11)
    n = 90
    score = np.round(rng.uniform(0.0, 1.0, size=n), 2)
    gather = rng.permutation(n)   # stands in for the engine's due-order gather
    ids = np.arange(n)
    for k in (1, 5, 26, n):
        got = list(ab._deterministic_top_n(score, gather, ids, k))
        scored = [{"id": i, "gather_index": int(gather[i]), "category": "x",
                   "score": float(score[i])} for i in range(n)]
        ref = [s["id"] for s in ab.select_top_n(scored, k)]
        assert got == ref


def test_selection_tie_break_is_due_then_id_and_stable():
    # All-equal scores: ties break by gather order (due asc) then id, and the
    # result is identical across repeated calls (reproducible, unlike argpartition).
    score = np.zeros(6)
    gather = np.array([5.0, 5.0, 1.0, 1.0, 9.0, 9.0])  # due values
    ids = np.arange(6)
    first = ab._deterministic_top_n(score, gather, ids, 4).tolist()
    again = ab._deterministic_top_n(score, gather, ids, 4).tolist()
    # soonest due first (2,3 have due 1), then due 5 (0,1); id breaks within a due
    assert first == again == [2, 3, 0, 1]


def _demo_world():
    # n_cards 180 keeps the smallest category (~11 cards) above the test budgets.
    return ab.World(seed=3, n_cards=180, subtopics_per_cat=4, horizon=30)


def test_select_full_picks_top_worth_under_budget():
    world = _demo_world()
    state = world.fresh_state()
    budget = 20
    sel = ab._select_full(state, world, day=1, budget=budget)
    assert len(sel) == budget
    assert len(set(sel.tolist())) == budget

    s, _d, last_rev, _c = state
    r = ab.retrievability(1 - last_rev, s)
    score = ab.score_vectorised(world.subtopic, r, world.blueprint, world.n_subtopics)
    due = last_rev + ab.next_interval(s)
    expected = ab._deterministic_top_n(score, due, np.arange(world.n), budget)
    assert sel.tolist() == expected.tolist()
    # It is a genuine top-set: no unselected card outscores a selected one.
    chosen = set(sel.tolist())
    unchosen = [i for i in range(world.n) if i not in chosen]
    assert score[list(chosen)].min() >= score[unchosen].max()


def test_select_blocked_masses_one_category_per_day():
    world = _demo_world()
    state = world.fresh_state()
    schedule = world.block_schedule()
    for day in (1, 7, 20):
        sel = ab._select_blocked(state, world, day, budget=5, schedule=schedule)
        assert len(sel) == 5
        cats = set(world.category[sel].tolist())
        assert cats == {int(schedule[day - 1])}


def test_select_plain_is_soonest_due():
    world = _demo_world()
    state = world.fresh_state()
    budget = 15
    sel = ab._select_plain(state, world, day=1, budget=budget)
    s, _d, last_rev, _c = state
    due = last_rev + ab.next_interval(s)
    expected = np.lexsort((np.arange(world.n), due))[:budget]
    assert sel.tolist() == expected.tolist()
    # The selected cards are the soonest due.
    chosen = set(sel.tolist())
    unchosen = [i for i in range(world.n) if i not in chosen]
    assert due[list(chosen)].max() <= due[unchosen].min()


def test_equal_study_time_across_arms():
    # Every arm must spend exactly budget * horizon reviews (equal study time).
    world = ab.World(seed=1, n_cards=180, subtopics_per_cat=4, horizon=20)
    for arm in ab.ARMS:
        res = ab.run_arm(world, arm, budget=5, horizon=20, exam_gap=0)
        assert res["reviews"] == 5 * 20


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
