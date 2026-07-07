"""Tests for the Memory calibration pipeline (L5.1).

Two groups:

1. Pure calibration metrics (Brier, log-loss, equal-mass ECE, reliability
   binning) checked against hand-computed known values. A perfectly calibrated
   synthetic input must give ~0 ECE; a perfect predictor must give ~0 Brier.

2. FSRS-6 reconstruction fidelity. The engine computes retrievability with the
   `fsrs` Rust crate (v5.2.0) using default parameters. The crate ships its own
   unit-test vectors (``rslib`` -> ``fsrs-5.2.0/src/model.rs``); we reproduce
   those exact numbers here, so the Python reimplementation is provably faithful
   to the shipped engine, not merely "an FSRS".

Run:
    conda run -n pgrep-ai --no-capture-output python -m pytest \
        content/tools/test_memory_calibration.py -q
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import memory_calibration as mc

TOL = 1e-5


# --------------------------------------------------------------------------- #
# 1. Pure metric functions                                                    #
# --------------------------------------------------------------------------- #


def test_brier_perfect_is_zero():
    p = np.array([1.0, 0.0, 1.0, 0.0])
    y = np.array([1.0, 0.0, 1.0, 0.0])
    assert mc.brier_score(p, y) == pytest.approx(0.0, abs=TOL)


def test_brier_known_values():
    # mean of (0.5-1)^2 and (0.5-0)^2 = mean(0.25, 0.25) = 0.25
    assert mc.brier_score(np.array([0.5, 0.5]), np.array([1.0, 0.0])) == pytest.approx(0.25)
    # mean((0.8-1)^2, (0.3-0)^2) = mean(0.04, 0.09) = 0.065
    assert mc.brier_score(np.array([0.8, 0.3]), np.array([1.0, 0.0])) == pytest.approx(0.065)


def test_brier_constant_equals_variance_of_outcome():
    # Predicting the base rate p0 gives Brier = p0 * (1 - p0) for 0/1 outcomes.
    y = np.array([1.0] * 70 + [0.0] * 30)
    p0 = y.mean()
    assert mc.brier_score(np.full_like(y, p0), y) == pytest.approx(p0 * (1 - p0))


def test_log_loss_known_value():
    # both correct with prob 0.9 -> -ln(0.9)
    got = mc.log_loss_score(np.array([0.9, 0.1]), np.array([1.0, 0.0]))
    assert got == pytest.approx(-math.log(0.9), abs=TOL)


def test_log_loss_clips_no_inf():
    # A confident-wrong 0/1 prediction must be finite thanks to clipping.
    got = mc.log_loss_score(np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    assert math.isfinite(got)
    assert got > 10.0  # heavily penalised


def test_log_loss_perfect_near_zero():
    got = mc.log_loss_score(np.array([1.0, 0.0, 1.0]), np.array([1.0, 0.0, 1.0]))
    assert got == pytest.approx(0.0, abs=1e-6)


def test_equal_mass_bins_are_balanced():
    p = np.linspace(0, 1, 100)
    groups = mc.equal_mass_bin_indices(p, n_bins=10)
    sizes = [len(g) for g in groups]
    assert sum(sizes) == 100
    assert max(sizes) - min(sizes) <= 1  # balanced


def test_ece_perfectly_calibrated_is_zero():
    # Two groups: predicted 0.2 with 20% ones, predicted 0.8 with 80% ones.
    p = np.array([0.2] * 100 + [0.8] * 100)
    y = np.array([1.0] * 20 + [0.0] * 80 + [1.0] * 80 + [0.0] * 20)
    ece = mc.ece_equal_mass(p, y, n_bins=2)
    assert ece == pytest.approx(0.0, abs=TOL)


def test_ece_fully_miscalibrated():
    # Predict 0.9 everywhere but only half recall -> ECE = 0.4. Outcomes
    # alternate so every equal-mass bin stays ~50% (a constant predictor has
    # tied confidences, so bin membership is order-defined; alternating keeps
    # the bins balanced and the answer clean).
    p = np.full(100, 0.9)
    y = np.array([1.0, 0.0] * 50)
    assert mc.ece_equal_mass(p, y, n_bins=1) == pytest.approx(0.4, abs=TOL)
    assert mc.ece_equal_mass(p, y, n_bins=5) == pytest.approx(0.4, abs=TOL)


def test_reliability_table_shapes_and_values():
    p = np.array([0.2] * 100 + [0.8] * 100)
    y = np.array([1.0] * 20 + [0.0] * 80 + [1.0] * 80 + [0.0] * 20)
    table = mc.reliability_table(p, y, n_bins=2, n_boot=200, seed=0)
    assert len(table) == 2
    assert sum(b["count"] for b in table) == 200
    assert table[0]["p_mean"] == pytest.approx(0.2)
    assert table[0]["o_mean"] == pytest.approx(0.2)
    assert table[1]["p_mean"] == pytest.approx(0.8)
    assert table[1]["o_mean"] == pytest.approx(0.8)
    for b in table:
        assert b["ci_low"] <= b["o_mean"] <= b["ci_high"]


# --------------------------------------------------------------------------- #
# 2. FSRS-6 reconstruction fidelity (against fsrs-rs 5.2.0 crate test vectors) #
# --------------------------------------------------------------------------- #

W = mc.DEFAULT_PARAMETERS


def test_default_params_match_crate():
    # Exact values from fsrs-5.2.0/src/inference.rs DEFAULT_PARAMETERS.
    assert len(W) == 21
    assert W[0] == pytest.approx(0.212)
    assert W[20] == pytest.approx(0.1542)
    assert mc.FSRS6_DEFAULT_DECAY == pytest.approx(0.1542)


def test_power_forgetting_curve_matches_crate():
    # fsrs-5.2.0/src/model.rs::tests::power_forgetting_curve
    delta_t = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    stability = np.array([1.0, 2.0, 3.0, 4.0, 4.0, 2.0])
    expected = np.array([1.0, 0.9403443, 0.9253786, 0.9185229, 0.9, 0.8261359])
    got = mc.power_forgetting_curve(delta_t, stability, W)
    np.testing.assert_allclose(got, expected, atol=TOL)


def test_retrievability_is_0_9_at_t_equals_s():
    # FSRS invariant: R = 0.9 when elapsed == stability.
    got = mc.power_forgetting_curve(np.array([7.0]), np.array([7.0]), W)
    assert got[0] == pytest.approx(0.9, abs=TOL)


def test_init_stability_matches_crate():
    for rating in (1, 2, 3, 4):
        assert mc.init_stability(rating, W) == pytest.approx(W[rating - 1])


def test_init_difficulty_matches_crate():
    # init_difficulty(r) = w4 - exp(w5*(r-1)) + 1
    for rating in (1, 2, 3, 4):
        expected = W[4] - math.exp(W[5] * (rating - 1)) + 1.0
        assert mc.init_difficulty(rating, W) == pytest.approx(expected, abs=TOL)


def test_next_difficulty_and_mean_reversion_match_crate():
    # fsrs-5.2.0/src/model.rs::tests::next_difficulty
    ratings = [1, 2, 3, 4]
    nd = [mc.next_difficulty(5.0, r, W) for r in ratings]
    np.testing.assert_allclose(nd, [8.354889, 6.6774445, 5.0, 3.3225555], atol=1e-4)
    mr = [mc.mean_reversion(x, W) for x in nd]
    np.testing.assert_allclose(mr, [8.341763, 6.6659956, 4.990228, 3.3144615], atol=1e-4)


def test_next_stability_success_failure_shortterm_match_crate():
    # fsrs-5.2.0/src/model.rs::tests::next_stability
    difficulty = [1.0, 2.0, 3.0, 4.0]
    r = [0.9, 0.8, 0.7, 0.6]
    rating = [1, 2, 3, 4]
    s_recall = [
        mc.stability_after_success(5.0, difficulty[i], r[i], rating[i], W) for i in range(4)
    ]
    np.testing.assert_allclose(
        s_recall, [25.602541, 28.226582, 58.656002, 127.226685], atol=1e-3
    )
    s_forget = [mc.stability_after_failure(5.0, difficulty[i], r[i], W) for i in range(4)]
    np.testing.assert_allclose(s_forget, [1.0525396, 1.1894329, 1.3680838, 1.584989], atol=1e-4)
    s_short = [mc.stability_short_term(5.0, rating[i], W) for i in range(4)]
    np.testing.assert_allclose(s_short, [1.596818, 2.7470093, 5.0, 8.12961], atol=1e-4)


def test_forward_trajectory_matches_crate():
    # fsrs-5.2.0/src/model.rs::tests::forward. Six independent length-2
    # sequences; we compare the final (stability, difficulty) of each.
    seqs = [
        ([1, 1], [0, 1]),
        ([2, 2], [0, 1]),
        ([3, 3], [0, 1]),
        ([4, 4], [0, 1]),
        ([1, 1], [0, 2]),
        ([2, 2], [0, 2]),
    ]
    exp_s = [0.10088589, 3.2494123, 7.3153, 18.014914, 0.112798266, 4.4694576]
    exp_d = [8.806304, 6.7404594, 2.1112142, 1.0, 8.806304, 6.7404594]
    for i, (ratings, deltas) in enumerate(seqs):
        s, d = mc.fsrs_forward_states(np.array(ratings), np.array(deltas, dtype=float), W)
        assert s[-1] == pytest.approx(exp_s[i], abs=1e-3)
        assert d[-1] == pytest.approx(exp_d[i], abs=1e-3)


def test_card_predictions_are_causal():
    # A simple 3-review card: prediction for review i must depend only on
    # reviews < i (past never sees future), and the first review yields no
    # prediction (no prior memory state).
    ratings = np.array([3, 3, 1])
    deltas = np.array([0.0, 5.0, 3.0])
    states = np.array([0, 2, 2])  # new, review, review
    preds = mc.card_predictions(ratings, deltas, states)
    # first review (new, delta 0) excluded; two review-state predictions remain.
    idxs = [p["index"] for p in preds]
    assert idxs == [1, 2]
    # R strictly in (0,1) for elapsed > 0
    for p in preds:
        assert 0.0 < p["r"] < 1.0
    assert preds[0]["outcome"] == 1  # rating 3 -> pass
    assert preds[1]["outcome"] == 0  # rating 1 -> fail


# --------------------------------------------------------------------------- #
# 3. Pipeline glue: split, per-user reconstruction (+ guards), baselines       #
# --------------------------------------------------------------------------- #


def _make_user(rows):
    """rows: list of (card_id, day_offset, state, rating, elapsed_days)."""
    a = np.array(rows, dtype=np.int64)
    return {
        "card_id": a[:, 0],
        "day_offset": a[:, 1],
        "state": a[:, 2],
        "rating": a[:, 3],
        "elapsed_days": a[:, 4],
    }


# Two interleaved cards; row order deliberately shuffled to prove the
# reconstruction sorts by day_offset itself and does not ride on a global pre-sort.
_GOOD_ROWS = [
    (10, 0, 0, 3, -1),   # card 10: new
    (20, 1, 0, 3, -1),   # card 20: new
    (10, 5, 2, 3, 5),    # card 10: review (pass)
    (20, 9, 2, 2, 8),    # card 20: review (pass)
    (10, 15, 2, 1, 10),  # card 10: review (fail)
]


def test_split_boundary_and_disjoint():
    preds = [{"day": d, "r": 0.7, "t": 5.0, "outcome": 1} for d in range(1, 11)]
    split = mc.split_and_collect(preds, train_frac=0.8)
    assert split["degenerate"] is False
    assert split["n_train"] == 8
    assert split["n_test"] == 2
    assert split["boundary_day"] == pytest.approx(8.2)


def test_split_is_leakage_free_by_day():
    preds = [{"day": d, "r": 0.7, "t": 5.0, "outcome": 1} for d in range(1, 11)]
    split = mc.split_and_collect(preds, train_frac=0.8)
    boundary = split["boundary_day"]
    train_days = [p["day"] for p in preds if p["day"] <= boundary]
    test_days = [p["day"] for p in preds if p["day"] > boundary]
    # Time split: every train day strictly precedes every test day, no overlap.
    assert set(train_days).isdisjoint(test_days)
    assert max(train_days) < min(test_days)
    assert float(np.min(split["day_test"])) > boundary


def test_split_degenerate_when_single_day():
    preds = [{"day": 5, "r": 0.7, "t": 5.0, "outcome": 1} for _ in range(10)]
    split = mc.split_and_collect(preds, train_frac=0.8)
    assert split["degenerate"] is True


def test_user_predictions_causal_and_isolated_regardless_of_row_order():
    # Sorted vs shuffled input must give identical predictions (explicit day sort).
    data_sorted = _make_user(sorted(_GOOD_ROWS, key=lambda r: (r[0], r[1])))
    data_shuffled = _make_user(list(reversed(_GOOD_ROWS)))
    ps = mc.user_predictions(data_sorted, user_id="t")
    pr = mc.user_predictions(data_shuffled, user_id="t")

    def key(ps):
        return sorted((p["day"], round(p["r"], 9), p["outcome"]) for p in ps)

    assert key(ps) == key(pr)

    # First review of each card yields no prediction; 3 scored reviews remain.
    assert len(ps) == 3
    days = sorted(p["day"] for p in ps)
    assert days == [5, 9, 15]  # the three non-first review-state rows

    # Isolation + causality: card 10's predictions must equal those computed from
    # card 10 alone (so card 20's rows cannot leak in), using only prior reviews.
    card10 = mc.card_predictions(
        np.array([3, 3, 1]), np.array([0.0, 5.0, 10.0]), np.array([0, 2, 2])
    )
    got10 = sorted((p["day"], round(p["r"], 9)) for p in ps if p["day"] in (5, 15))
    exp10 = sorted((d, round(c["r"], 9)) for d, c in zip((5, 15), card10))
    assert got10 == exp10


def test_user_predictions_guard_first_row_not_new():
    bad = _make_user([(30, 0, 2, 3, 5), (30, 5, 2, 3, 5)])  # first row is review, not new
    with pytest.raises(ValueError, match=r"card=30.*first row has state"):
        mc.user_predictions(bad, user_id="99")


def test_user_predictions_guard_elapsed_disagrees_with_day_offset():
    # Non-first review: elapsed_days=3 but day_offset jumped 10 -> corrupted/reordered.
    bad = _make_user([(40, 0, 0, 3, -1), (40, 10, 2, 3, 3)])
    with pytest.raises(ValueError, match=r"card=40.*disagrees with day_offset diff"):
        mc.user_predictions(bad, user_id="99")


def test_fit_global_stability_recovers_known_value():
    rng = np.random.default_rng(0)
    s_true = 10.0
    t = rng.integers(1, 31, size=6000).astype(float)
    r = mc.power_forgetting_curve(t, np.full_like(t, s_true))
    y = (rng.random(t.size) < r).astype(float)
    s_hat = mc.fit_global_stability(t, y)
    # A correctly specified 1-parameter fit recovers S* (loose bound vs noise).
    assert 6.0 < s_hat < 16.0


def test_recalibration_is_monotonic():
    rng = np.random.default_rng(1)
    r_train = rng.random(4000)
    y_train = (rng.random(4000) < r_train).astype(float)  # higher R -> more recall
    model = mc.fit_recalibration(r_train, y_train)
    grid = np.linspace(0.02, 0.98, 60)
    p = mc.recalibrate(grid, model)
    assert np.all(np.diff(p) >= -1e-9)  # non-decreasing


def test_recalibration_is_fit_on_train_only():
    rng = np.random.default_rng(2)
    grid = np.linspace(0.02, 0.98, 40)
    r_train = rng.random(3000)
    y_train = (rng.random(3000) < r_train).astype(float)
    # A "test" set with the OPPOSITE relationship (higher R -> less recall).
    r_test = rng.random(3000)
    y_test = (rng.random(3000) < (1.0 - r_test)).astype(float)

    m_train = mc.fit_recalibration(r_train, y_train)
    # Deterministic: the map depends only on the train data.
    m_train2 = mc.fit_recalibration(r_train, y_train)
    np.testing.assert_allclose(mc.recalibrate(grid, m_train), mc.recalibrate(grid, m_train2))
    # Fitting on the (leaky) test labels would yield a different map, which is
    # exactly why we fit on train only.
    m_leak = mc.fit_recalibration(r_test, y_test)
    assert not np.allclose(mc.recalibrate(grid, m_train), mc.recalibrate(grid, m_leak))


def test_recalibration_single_class_returns_none():
    r = np.array([0.4, 0.6, 0.8])
    assert mc.fit_recalibration(r, np.array([1.0, 1.0, 1.0])) is None
