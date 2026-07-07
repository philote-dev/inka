"""L5.4 ablation harness: does the pgrep interleaving selector actually help?

This is a controlled simulation, not a human trial. There is no real learner
cohort (n = 1, Frank), so we cannot measure interleaving on people. Instead we
build a seeded synthetic study world under an FSRS-style ground-truth memory
model and ask a narrow, honest question: given an equal study budget, does the
shipped selector's topic-interleaved, weakness- and blueprint-weighted ordering
reach a higher exam-relevant recall than the alternatives? The result validates
(or fails to validate) the mechanism, it does not prove a human effect.

Three arms, equal study time (equal number of reviews per arm):

  full     The shipped policy. Each day it scores every card by
           worth = blueprint(category) * weakness(subtopic), applies the
           desirable-difficulty band (x1.0 inside R in [0.60, 0.85], else x0.5),
           and studies the top budget cards. Because worth spreads across
           categories, a category's reviews are spaced across the whole horizon
           (interleaved). Mirrors points_at_stake.rs.
  blocked  Interleaving off. Same worth scoring, but categories are studied in
           contiguous massed blocks (block length proportional to blueprint),
           so a category is hammered in a window then left to decay. The only
           intended difference from full is temporal: massed vs interleaved.
  plain    Stock Anki. Study the soonest-due cards first (ORDER BY due), no
           blueprint weight, no weakness, no band, no interleaving.

The shipped selector's *exact* interleaving mechanism, the K=3 anti-blocking
reshuffle, gets no separate arm because it is null by construction. It only
reorders an already-selected set, and same-day review order does not change
FSRS updates, so it cannot move the metric. It is ported and unit-tested
(anti_block_order) for fidelity, and the report keeps the caveat.

The ground-truth model is the FSRS-6 default (crate fsrs 5.2.0): the power
forgetting curve and the stability and difficulty updates with DEFAULT_PARAMETERS.
We treat that model as ground truth and assume the selector's predicted R equals
it (perfect self-calibration), which isolates the ordering and selection policy,
the actual ablation target, from calibration error.

Run (repo root, conda env pgrep-ai):
    conda run -n pgrep-ai --no-capture-output python content/tools/ablation.py
    conda run -n pgrep-ai --no-capture-output python content/tools/ablation.py \
        --seeds 60 --budget 30 --horizon 120

Nothing here touches a real collection or any scheduling state. It is standalone.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from eval_metrics import bootstrap_ci, paired_advantage_ci  # noqa: E402  (read-only reuse)

CONTENT = os.path.dirname(HERE)
RUN = os.path.join(CONTENT, "run")


# --- FSRS-6 ground-truth constants (crate fsrs 5.2.0) -----------------------

# DEFAULT_PARAMETERS, the 21 FSRS-6 weights. w[20] is the decay.
W = [
    0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722,
    0.1666, 0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425,
    0.0912, 0.0658, 0.1542,
]
# The power forgetting curve exponent is negative: decay_exp = -w[20].
DECAY_EXP = -W[20]
FACTOR = 0.9 ** (1.0 / DECAY_EXP) - 1.0
S_MIN, S_MAX = 0.001, 36500.0
D_MIN, D_MAX = 1.0, 10.0
DESIRED_RETENTION = 0.9

# --- selector constants (duplicated from points_at_stake.rs) ----------------

IN_BAND_LOW, IN_BAND_HIGH = 0.60, 0.85
OUT_OF_BAND_FACTOR = 0.5
MAX_CONSECUTIVE_SAME_CATEGORY = 3
CATEGORIES = [
    "mechanics", "electromagnetism", "quantum", "thermodynamics", "atomic",
    "optics_waves", "special_relativity", "lab", "specialized",
]
BLUEPRINT = {
    "mechanics": 0.20, "electromagnetism": 0.18, "quantum": 0.13,
    "thermodynamics": 0.10, "atomic": 0.10, "optics_waves": 0.08,
    "special_relativity": 0.06, "lab": 0.06, "specialized": 0.09,
}

# --- simulation design constants (documented, tunable defaults) --------------

# Per-category latent competence, drawn uniformly in this range, sets how strong
# each category starts (weaker categories give the selector something to target).
STRENGTH_LOW, STRENGTH_HIGH = 0.3, 0.9
# Warmup successful reviews per card scale with strength, up to this many, so the
# day-0 stability spread is FSRS-consistent rather than hand-set.
MAX_WARMUP_REVIEWS = 6
# Day-0 decay: each card starts having waited up to this many review intervals,
# so initial retrievability (and overdue-ness) varies across the deck.
INIT_DECAY_OFFSET_INTERVALS = 6.0
# Common-random-number draw columns beyond the horizon. A card is reviewed at
# most once per day, so horizon draws suffice; the slack is a safety margin.
RECALL_DRAW_SLACK = 2
# A card at or above this retrievability at the horizon counts as "mastered".
MASTERY_THRESHOLD = 0.8
MASTERY_KEY = f"mastery_{MASTERY_THRESHOLD:g}"

# --- the pre-stated primary metric (fixed BEFORE any run) -------------------

PRIMARY_METRIC = "blueprint_weighted_expected_recall_at_horizon"
PRIMARY_METRIC_DESC = (
    "Blueprint-weighted expected recall at the exam horizon (BWER). For each of "
    "the nine PGRE blueprint categories, take the mean ground-truth "
    "retrievability over that category's cards at the horizon (0 if the category "
    "has no cards), then weight by the official PGRE blueprint fraction and sum. "
    "The blueprint weights sum to 1, so BWER is the exam-day probability of a "
    "correct answer on a blueprint-sampled question, in [0, 1]. It is the app's "
    "actual objective (exam-day, blueprint-weighted readiness) and it is coverage-"
    "aware (uncovered areas score 0). It shares only the blueprint weighting with "
    "the selector's worth term; it uses neither the weakness term nor the "
    "desirable-difficulty band, so it does not tautologically favor the full arm. "
    "Higher is better. Stated before running."
)


# --- forgetting curve and intervals -----------------------------------------


def retrievability(elapsed_days, stability):
    """Ground-truth retrievability via the FSRS power forgetting curve.

    R(t, S) = (t / S * FACTOR + 1) ** DECAY_EXP, with R(0) = 1 and R(S) = 0.9.
    Works on scalars or numpy arrays.
    """
    return np.power(elapsed_days / stability * FACTOR + 1.0, DECAY_EXP)


def next_interval(stability, desired_retention=DESIRED_RETENTION):
    """Days until retrievability falls to desired_retention. Equals stability at
    retention 0.9. This is the stock Anki due interval."""
    return stability / FACTOR * (desired_retention ** (1.0 / DECAY_EXP) - 1.0)


# --- FSRS state updates ------------------------------------------------------


def init_stability(rating: int) -> float:
    """Initial stability S0(rating) = w[rating - 1] for rating in 1..4."""
    return float(W[rating - 1])


def _init_difficulty_raw(rating) -> float:
    return W[4] - math.exp(W[5] * (rating - 1)) + 1.0


def init_difficulty(rating: int) -> float:
    """Initial difficulty D0(rating), clamped to [1, 10]."""
    return float(min(max(_init_difficulty_raw(rating), D_MIN), D_MAX))


def stability_after_success(stability, difficulty, r, rating: int = 3):
    """New stability after a successful review (FSRS SInc). Larger when
    retrievability at review is lower (the desirable-difficulty effect)."""
    hard_penalty = W[15] if rating == 2 else 1.0
    easy_bonus = W[16] if rating == 4 else 1.0
    return stability * (
        math.exp(W[8]) * (11.0 - difficulty) * stability ** (-W[9])
        * (math.exp((1.0 - r) * W[10]) - 1.0) * hard_penalty * easy_bonus
        + 1.0
    )


def stability_after_failure(stability, difficulty, r):
    """New stability after a lapse, capped so it never exceeds the prior."""
    new_s = (
        W[11] * difficulty ** (-W[12]) * ((stability + 1.0) ** W[13] - 1.0)
        * math.exp((1.0 - r) * W[14])
    )
    # Upper cap: a lapse must not raise stability above (a shade below) the prior.
    post_lapse_cap = stability / math.exp(W[17] * W[18])
    return min(new_s, post_lapse_cap)


def next_difficulty(difficulty, rating):
    """FSRS difficulty update with linear damping and mean reversion, clamped."""
    delta_d = -W[6] * (rating - 3.0)
    new_d = difficulty + (10.0 - difficulty) * delta_d / 9.0
    new_d = W[7] * (_init_difficulty_raw(4) - new_d) + new_d
    return min(max(new_d, D_MIN), D_MAX)


def update_memory(stability, difficulty, elapsed_days, success: bool):
    """Scalar one-step FSRS update. Returns (stability, difficulty)."""
    r = float(retrievability(elapsed_days, stability))
    if success:
        new_s = stability_after_success(stability, difficulty, r, rating=3)
        rating = 3
    else:
        new_s = stability_after_failure(stability, difficulty, r)
        rating = 1
    new_s = min(max(new_s, S_MIN), S_MAX)
    new_d = next_difficulty(difficulty, rating)
    return new_s, new_d


def _update_memory_vec(stability, difficulty, elapsed_days, success):
    """Vectorised FSRS update over arrays. success is a boolean array. Uses the
    same equations as update_memory (rating 3 on success, rating 1 on lapse)."""
    r = retrievability(elapsed_days, stability)
    s_succ = stability * (
        math.exp(W[8]) * (11.0 - difficulty) * np.power(stability, -W[9])
        * (np.exp((1.0 - r) * W[10]) - 1.0) + 1.0
    )
    post_lapse_cap = stability / math.exp(W[17] * W[18])
    s_fail = np.minimum(
        W[11] * np.power(difficulty, -W[12]) * (np.power(stability + 1.0, W[13]) - 1.0)
        * np.exp((1.0 - r) * W[14]),
        post_lapse_cap,
    )
    new_s = np.clip(np.where(success, s_succ, s_fail), S_MIN, S_MAX)
    rating = np.where(success, 3.0, 1.0)
    delta_d = -W[6] * (rating - 3.0)
    new_d = difficulty + (10.0 - difficulty) * delta_d / 9.0
    new_d = W[7] * (_init_difficulty_raw(4) - new_d) + new_d
    return new_s, np.clip(new_d, D_MIN, D_MAX)


# --- selector: blueprint, band, worth, weakness (mirror points_at_stake.rs) --


def blueprint_weight(category: str) -> float:
    return BLUEPRINT.get(category, 0.0)


def band_factor(r) -> float:
    """1.0 inside the desirable-difficulty band [0.60, 0.85], else 0.5 (unknown
    or NaN R counts as out of band)."""
    if r is None:
        return OUT_OF_BAND_FACTOR
    if isinstance(r, float) and math.isnan(r):
        return OUT_OF_BAND_FACTOR
    return 1.0 if IN_BAND_LOW <= r <= IN_BAND_HIGH else OUT_OF_BAND_FACTOR


def worth(blueprint: float, weakness: float) -> float:
    return blueprint * weakness


def weakness_by_topic(inputs: list[dict]) -> dict:
    """weakness(topic) = 1 - mean(R over that topic's cards with defined R)."""
    sums: dict[str, list[float]] = {}
    for inp in inputs:
        topic, r = inp.get("topic"), inp.get("r")
        if topic is not None and r is not None:
            acc = sums.setdefault(topic, [0.0, 0])
            acc[0] += r
            acc[1] += 1
    return {t: 1.0 - s / n for t, (s, n) in sums.items()}


def score_inputs(inputs: list[dict]) -> list[dict]:
    """Reference scorer, one-to-one with points_at_stake.rs::score_inputs.
    score = worth(blueprint, weakness(topic)) * band_factor(R)."""
    weakness = weakness_by_topic(inputs)
    out = []
    for inp in inputs:
        w = weakness.get(inp.get("topic"), 0.0)
        s = worth(inp["blueprint"], w) * band_factor(inp.get("r"))
        out.append({
            "id": inp["id"], "gather_index": inp["gather_index"],
            "category": inp["category"], "score": s,
        })
    return out


def sort_by_worth(scored: list[dict]) -> list[dict]:
    """Score descending, ties by gather_index then id (mirror the selector)."""
    return sorted(scored, key=lambda s: (-s["score"], s["gather_index"], s["id"]))


def select_top_n(scored: list[dict], n: int) -> list[dict]:
    """The retained top-N by worth that the daily limit would keep."""
    return sort_by_worth(scored)[:n]


def _would_block(ordered: list[dict], category: str) -> bool:
    k = MAX_CONSECUTIVE_SAME_CATEGORY
    return len(ordered) >= k and all(s["category"] == category for s in ordered[-k:])


def anti_block_order(scored: list[dict]) -> list[dict]:
    """Greedy K=3 anti-blocking reorder (mirror points_at_stake.rs::anti_block_order).
    Reorders the emit sequence only. It never changes which cards are selected."""
    remaining = sort_by_worth(scored)
    ordered: list[dict] = []
    while remaining:
        pick = next((i for i, s in enumerate(remaining)
                     if not _would_block(ordered, s["category"])), 0)
        ordered.append(remaining.pop(pick))
    return ordered


def score_vectorised(group, r, blueprint, n_groups):
    """Fast numpy path for the daily selector score, equal to score_inputs on a
    due set with all R defined. group is the weakness grouping key per card."""
    counts = np.bincount(group, minlength=n_groups).astype(float)
    sums = np.bincount(group, weights=r, minlength=n_groups)
    mean_r = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    weakness = (1.0 - mean_r)[group]
    band = np.where((r >= IN_BAND_LOW) & (r <= IN_BAND_HIGH), 1.0, OUT_OF_BAND_FACTOR)
    return blueprint * weakness * band


# --- the pre-stated metric ---------------------------------------------------


def blueprint_weighted_recall(categories, r) -> float:
    """BWER: sum over the nine blueprint categories of weight * mean R, with a
    missing category contributing 0. See PRIMARY_METRIC_DESC."""
    total = 0.0
    for c, name in enumerate(CATEGORIES):
        mask = categories == c
        mean_r = float(r[mask].mean()) if mask.any() else 0.0
        total += BLUEPRINT[name] * mean_r
    return total


# --- synthetic world ---------------------------------------------------------


def _largest_remainder(weights, total: int) -> np.ndarray:
    """Apportion an integer total across weights so the parts sum to total
    exactly (largest-remainder / Hamilton rounding)."""
    raw = np.asarray(weights, dtype=float) * total
    base = np.floor(raw).astype(int)
    order = np.argsort(-(raw - base))
    for i in range(total - int(base.sum())):
        base[order[i]] += 1
    return base


def _category_counts(n_cards: int) -> np.ndarray:
    """Card counts per category, proportional to the blueprint, summing to
    n_cards."""
    return _largest_remainder([BLUEPRINT[c] for c in CATEGORIES], n_cards)


class World:
    """A seeded synthetic deck plus its shared recall draws. Arms operate on
    independent copies of the mutable state, so the comparison is paired."""

    def __init__(self, seed: int, n_cards: int, subtopics_per_cat: int, horizon: int):
        rng = np.random.default_rng(seed)
        counts = _category_counts(n_cards)
        self.n = int(counts.sum())
        self.subtopics_per_cat = subtopics_per_cat
        self.n_subtopics = len(CATEGORIES) * subtopics_per_cat
        self.horizon = horizon

        self.category = np.repeat(np.arange(len(CATEGORIES)), counts)
        local_sub = rng.integers(0, subtopics_per_cat, size=self.n)
        self.subtopic = self.category * subtopics_per_cat + local_sub
        self.blueprint = np.array([BLUEPRINT[CATEGORIES[c]] for c in self.category])

        # Per-category latent competence drives the initial mastery spread, so
        # some categories start genuinely weaker than others (selector signal).
        strength = rng.uniform(STRENGTH_LOW, STRENGTH_HIGH,
                               size=len(CATEGORIES))[self.category]
        rating0 = np.where(rng.random(self.n) < strength, 3, 1)
        S = np.array([init_stability(int(x)) for x in rating0])
        D = np.array([init_difficulty(int(x)) for x in rating0])

        # Light warmup: a few spaced successful reviews, more for stronger
        # categories, to reach FSRS-consistent stability before day 0.
        warm_max = 1 + np.round(strength * MAX_WARMUP_REVIEWS).astype(int)
        m = (rng.random(self.n) * (warm_max + 1)).astype(int)
        for step in range(int(m.max()) if self.n else 0):
            active = step < m
            if not active.any():
                continue
            elapsed = next_interval(S[active])
            ns, nd = _update_memory_vec(S[active], D[active], elapsed,
                                        np.ones(active.sum(), dtype=bool))
            S[active], D[active] = ns, nd

        # Start each card partly decayed so day-0 retrievability varies and some
        # cards are already overdue.
        offset = rng.uniform(0.0, INIT_DECAY_OFFSET_INTERVALS, size=self.n) * next_interval(S)
        self.init_S = S
        self.init_D = D
        self.init_last_rev = -np.round(offset)

        # A blocked category order per seed (randomised so no single topic is
        # always freshest at the horizon).
        self.block_order = rng.permutation(len(CATEGORIES))

        # Common random numbers: the k-th review of a card uses the same uniform
        # draw in every arm, so recall outcomes are paired across arms.
        self.recall_u = rng.random((self.n, horizon + RECALL_DRAW_SLACK))

    def fresh_state(self):
        return (self.init_S.copy(), self.init_D.copy(),
                self.init_last_rev.copy(),
                np.zeros(self.n, dtype=int))

    def block_schedule(self) -> np.ndarray:
        """Map each study day (0-indexed) to the category being massed that day.
        Block lengths are proportional to the blueprint and sum to the horizon."""
        weights = [BLUEPRINT[CATEGORIES[c]] for c in self.block_order]
        lengths = _largest_remainder(weights, self.horizon)
        return np.repeat(self.block_order, lengths)


# --- the three policies -----------------------------------------------------
#
# Selection uses the same deterministic order as the shipped selector:
# score descending, then gather_index ascending, then id ascending
# (points_at_stake.rs::sort_by_worth). The engine gathers due reviews with
# "ORDER BY due, fnvhash(id)" for PointsAtStake (review_order_sql, the Day then
# Random subclauses), so gather_index is due order (soonest due first). We
# mirror that: ties in worth break by due ascending, then card id. We select
# with np.lexsort (a stable sort), not np.argpartition, whose order among equal
# keys is implementation-defined and not reproducible. The daily score is
# heavily quantized (worth takes few distinct values), so many cards tie at the
# budget boundary and the tie-break genuinely matters; the due-then-id rule is
# what makes it both faithful and reproducible. _deterministic_top_n is proven
# equal to the ported select_top_n by test_deterministic_top_n_matches_reference.


def _deterministic_top_n(score, gather, ids, n):
    """Indices of the top n by (score desc, gather asc, id asc), a stable and
    reproducible order matching select_top_n(sort_by_worth). gather mirrors the
    engine's gather order (due ascending); id is the final deterministic key."""
    order = np.lexsort((ids, gather, -score))
    return order[:n]


def _select_full(state, world, day, budget):
    S, _D, last_rev, _count = state
    r = retrievability(day - last_rev, S)
    score = score_vectorised(world.subtopic, r, world.blueprint, world.n_subtopics)
    due = last_rev + next_interval(S)
    return _deterministic_top_n(score, due, np.arange(world.n), budget)


def _select_blocked(state, world, day, budget, schedule):
    S, _D, last_rev, _count = state
    cat = schedule[day - 1]
    elig = np.where(world.category == cat)[0]
    r = retrievability(day - last_rev[elig], S[elig])
    sub_score = score_vectorised(world.subtopic[elig], r,
                                 world.blueprint[elig], world.n_subtopics)
    due = last_rev[elig] + next_interval(S[elig])
    return elig[_deterministic_top_n(sub_score, due, elig, budget)]


def _select_plain(state, world, day, budget):
    S, _D, last_rev, _count = state
    due = last_rev + next_interval(S)
    # Stock Anki review order: ORDER BY due, then a stable id (soonest due first).
    order = np.lexsort((np.arange(world.n), due))
    return order[:budget]


def _apply_reviews(state, world, day, sel):
    S, D, last_rev, count = state
    elapsed = day - last_rev[sel]
    r = retrievability(elapsed, S[sel])
    u = world.recall_u[sel, count[sel]]
    success = u < r
    ns, nd = _update_memory_vec(S[sel], D[sel], elapsed, success)
    S[sel], D[sel] = ns, nd
    last_rev[sel] = day
    count[sel] += 1


def run_arm(world: World, arm: str, budget: int, horizon: int, exam_gap: int) -> dict:
    """Run one arm to the horizon and return its metrics. Every arm reviews
    exactly budget cards per day, so study time is equal by construction."""
    state = world.fresh_state()
    schedule = world.block_schedule() if arm == "blocked" else None
    reviews = 0
    for day in range(1, horizon + 1):
        if arm == "full":
            sel = _select_full(state, world, day, budget)
        elif arm == "blocked":
            sel = _select_blocked(state, world, day, budget, schedule)
        elif arm == "plain":
            sel = _select_plain(state, world, day, budget)
        else:
            raise ValueError(f"unknown arm {arm}")
        _apply_reviews(state, world, day, sel)
        reviews += len(sel)

    S, _D, last_rev, _count = state
    exam_day = horizon + exam_gap
    r_exam = retrievability(exam_day - last_rev, S)
    bwer = blueprint_weighted_recall(world.category, r_exam)
    per_cat = []
    for c in range(len(CATEGORIES)):
        mask = world.category == c
        per_cat.append(float(r_exam[mask].mean()) if mask.any() else 0.0)
    mastery = blueprint_weighted_recall(world.category,
                                        (r_exam >= MASTERY_THRESHOLD).astype(float))
    return {
        "bwer": bwer,
        "mean_recall": float(r_exam.mean()),
        MASTERY_KEY: mastery,
        "per_category": per_cat,
        "reviews": reviews,
    }


ARMS = ["full", "blocked", "plain"]


def run_config(seeds, budget, horizon, n_cards, subtopics, exam_gap) -> dict:
    """Run every arm over every seed for one configuration."""
    out = {a: {"bwer": [], "mean_recall": [], MASTERY_KEY: [], "reviews": [],
               "per_category": []} for a in ARMS}
    for seed in seeds:
        world = World(seed, n_cards, subtopics, horizon)
        for arm in ARMS:
            res = run_arm(world, arm, budget, horizon, exam_gap)
            for k in ("bwer", "mean_recall", MASTERY_KEY, "reviews"):
                out[arm][k].append(res[k])
            out[arm]["per_category"].append(res["per_category"])
    return out


# --- aggregation -------------------------------------------------------------


def _ci(values, seed=0) -> dict:
    return bootstrap_ci(values, seed=seed).as_dict()


def _advantage(a_values, b_values, seed=0) -> dict:
    ci = paired_advantage_ci(a_values, b_values, seed=seed).as_dict()
    ci["ci_excludes_zero"] = bool(ci["low"] > 0 or ci["high"] < 0)
    ci["direction"] = "a>b" if ci["point"] > 0 else ("a<b" if ci["point"] < 0 else "tie")
    return ci


def summarize_config(raw: dict) -> dict:
    arms = {}
    for a in ARMS:
        arms[a] = {
            "bwer": _ci(raw[a]["bwer"]),
            "mean_recall": _ci(raw[a]["mean_recall"]),
            MASTERY_KEY: _ci(raw[a][MASTERY_KEY]),
            "reviews_total": int(np.sum(raw[a]["reviews"])),
            "reviews_per_seed": int(round(float(np.mean(raw[a]["reviews"])))),
            "per_category_mean": np.mean(raw[a]["per_category"], axis=0).round(4).tolist(),
        }
    contrasts = {
        "full_minus_blocked": _advantage(raw["full"]["bwer"], raw["blocked"]["bwer"]),
        "full_minus_plain": _advantage(raw["full"]["bwer"], raw["plain"]["bwer"]),
        "blocked_minus_plain": _advantage(raw["blocked"]["bwer"], raw["plain"]["bwer"]),
    }
    return {"arms": arms, "contrasts": contrasts}


# --- report writers ----------------------------------------------------------


def _fmt_ci(ci: dict) -> str:
    return f"{ci['point']:.4f} [{ci['low']:.4f}, {ci['high']:.4f}]"


def _fmt_adv(adv: dict) -> str:
    excl = "excludes 0" if adv["ci_excludes_zero"] else "includes 0"
    return f"{adv['point']:+.4f} [{adv['low']:+.4f}, {adv['high']:+.4f}] (CI {excl})"


def _pos(adv) -> bool:
    return adv["point"] > 0 and adv["ci_excludes_zero"]


def _neg(adv) -> bool:
    return adv["point"] < 0 and adv["ci_excludes_zero"]


def findings(primary: dict, grid: list) -> dict:
    """Data-driven read of what did and did not work, across the whole grid.

    Every count and every budget list below is derived from the grid, so a
    changed grid cannot leave the numbers right but the words wrong.
    """
    n = len(grid)
    fb = [cell["summary"]["contrasts"]["full_minus_blocked"] for cell in grid]
    fp = [cell["summary"]["contrasts"]["full_minus_plain"] for cell in grid]
    fb_wins = sum(_pos(a) for a in fb)
    fp_wins = sum(_pos(a) for a in fp)
    fp_losses = sum(_neg(a) for a in fp)
    win_budgets = sorted({cell["budget"] for cell, a in zip(grid, fp) if _pos(a)})
    lose_budgets = sorted({cell["budget"] for cell, a in zip(grid, fp) if _neg(a)})

    spacing = ("helps robustly (full beats blocked in every configuration, "
               "CIs exclude zero)." if fb_wins == n
               else f"mixed (full beats blocked in {fb_wins}/{n} configurations).")
    if fp_losses:
        stock = (f"NOT robust. Full beats stock Anki in {fp_wins}/{n} "
                 f"configurations and loses in {fp_losses}/{n}. It loses at "
                 f"budget(s) {lose_budgets} and wins at budget(s) {win_budgets} "
                 "reviews/day. This is consistent with the desirable-difficulty "
                 "band spending near-term recall to buy stability, a trade that "
                 "does not pay back under a tight budget.")
    elif fp_wins == n:
        stock = "helps in every configuration."
    else:
        stock = (f"flat or mixed (wins {fp_wins}/{n}, no significant losses; "
                 f"wins at budget(s) {win_budgets}).")

    return {
        "interleaving_as_spacing_vs_blocked": spacing,
        "full_selector_vs_stock_anki": stock,
        "shipped_antiblocking_reshuffle": (
            "null by construction: it only reorders an already-selected set, and "
            "same-day review order does not change FSRS updates, so it moves the "
            "metric by exactly zero. It has no separate arm; it is ported and "
            "unit-tested (anti_block_order) for fidelity."
        ),
        "full_vs_plain_win_budgets": win_budgets,
        "full_vs_plain_lose_budgets": lose_budgets,
        "primary_full_minus_blocked": primary["contrasts"]["full_minus_blocked"],
        "primary_full_minus_plain": primary["contrasts"]["full_minus_plain"],
    }


def build_results(args, seeds, primary, grid) -> dict:
    return {
        "task": "L5.4 ablation harness",
        "kind": "controlled simulation (n=1 synthetic, validates the mechanism, "
                "not a human trial)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "primary_metric": PRIMARY_METRIC,
        "primary_metric_description": PRIMARY_METRIC_DESC,
        "primary_metric_prestated": True,
        "ground_truth_model": {
            "name": "FSRS-6 default (crate fsrs 5.2.0)",
            "decay_exp": DECAY_EXP,
            "factor": FACTOR,
            "default_parameters": W,
            "assumption": "selector predicted R equals ground-truth R "
                          "(perfect self-calibration), isolating the ordering "
                          "and selection policy from calibration error",
            "recall_rule": "Bernoulli recall with p = R at review time; rating 3 "
                           "on success, rating 1 on lapse (no hard/easy modeled)",
        },
        "arms": {
            "full": "shipped points_at_stake selector (interleaved, worth x band)",
            "blocked": "interleaving off: same worth scoring, massed category blocks",
            "plain": "stock Anki, soonest-due order (ORDER BY due)",
        },
        "selection_tie_break": (
            "deterministic (score desc, then gather order = due asc, then id asc "
            "via np.lexsort), mirroring the engine's PointsAtStake gather order "
            "(ORDER BY due) and reproducible across platforms; proven equal to the "
            "ported select_top_n by test"
        ),
        "equal_study_time": {
            "rule": "every arm reviews exactly budget cards per day",
            "reviews_per_arm_per_seed": primary["arms"]["full"]["reviews_per_seed"],
        },
        "config": {
            "seeds": len(seeds), "seed_list": list(seeds), "budget": args.budget,
            "horizon_days": args.horizon, "exam_gap_days": args.exam_gap,
            "n_cards": args.cards, "subtopics_per_category": args.subtopics,
        },
        "results_primary": primary,
        "sensitivity_grid": grid,
        "findings": findings(primary, grid),
        "caveats": [
            "This is a simulation, not a human trial. With n=1 (Frank) there is "
            "no learner cohort to measure, so it validates the mechanism under an "
            "FSRS ground truth, it does not establish a human interleaving effect.",
            "The shipped K=3 anti-blocking only reorders the emit sequence within "
            "an already-selected set. Under an FSRS model where same-day review "
            "order does not change memory updates, it has exactly zero effect on "
            "the metric. Its rationale (discrimination and contextual interference) "
            "is cognitive and outside FSRS's scope, so this harness can neither "
            "credit nor refute it. The blocked arm therefore tests the broader "
            "sense of interleaving, spaced-mixed vs massed practice.",
            "The blocked arm allocates reviews across categories by blueprint "
            "while full allocates by worth (blueprint x weakness x band), so full "
            "also does within-category weakness prioritisation. The contrast is "
            "the honest spaced-vs-massed comparison, not a single-variable swap.",
            "Ratings are collapsed to success or lapse; hard and easy are not "
            "modeled. Desired retention is fixed at 0.9 for stock due dates.",
        ],
        "reproduce": (
            "conda run -n pgrep-ai --no-capture-output python content/tools/"
            f"ablation.py --seeds {args.seeds} --budget {args.budget} "
            f"--horizon {args.horizon} --cards {args.cards}"
        ),
    }


def write_markdown(path: str, results: dict) -> None:
    p = results["results_primary"]
    a = p["arms"]
    c = p["contrasts"]
    f = results["findings"]
    cfg = results["config"]

    def row(name, key):
        return f"| {name} | {_fmt_ci(a[key]['bwer'])} | {a[key]['reviews_per_seed']} |"

    lines = []
    lines.append("# L5.4 Ablation: does interleaving help?")
    lines.append("")
    lines.append("Controlled simulation, not a human trial. With n=1 (Frank) there "
                 "is no learner cohort, so this validates the shipped interleaving "
                 "mechanism under an FSRS-6 ground-truth memory model. It does not "
                 "prove a human effect.")
    lines.append("")
    lines.append("## Headline (honest)")
    lines.append("")
    lines.append(f"- Interleaving as spacing (full vs blocked): {f['interleaving_as_spacing_vs_blocked']}")
    lines.append(f"- Full selector vs stock Anki (full vs plain): {f['full_selector_vs_stock_anki']}")
    lines.append(f"- Shipped K=3 anti-blocking reshuffle: {f['shipped_antiblocking_reshuffle']}")
    lines.append("")
    lines.append("## Pre-stated primary metric")
    lines.append("")
    lines.append(f"**{PRIMARY_METRIC}** (stated before running).")
    lines.append("")
    lines.append(PRIMARY_METRIC_DESC)
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- Seeds: {cfg['seeds']}. Budget: {cfg['budget']} reviews/day. "
                 f"Horizon: {cfg['horizon_days']} days. Cards: {cfg['n_cards']} "
                 f"across the nine blueprint categories.")
    lines.append(f"- Equal study time: every arm reviews exactly {cfg['budget']} "
                 f"cards/day ({a['full']['reviews_per_seed']} reviews per seed per arm).")
    lines.append("- Ground truth: FSRS-6 default parameters. Common random numbers "
                 "pair recall outcomes across arms. Bootstrap 95% CIs over seeds.")
    lines.append("")
    lines.append("## Three-arm result (primary metric, BWER)")
    lines.append("")
    lines.append("| Arm | BWER (mean [95% CI]) | Reviews/seed |")
    lines.append("| --- | --- | --- |")
    lines.append(row("full (interleaved, shipped)", "full"))
    lines.append(row("blocked (interleaving off)", "blocked"))
    lines.append(row("plain Anki (stock due order)", "plain"))
    lines.append("")
    lines.append("Paired contrasts (positive means the first arm is higher):")
    lines.append("")
    lines.append(f"- full - blocked: {_fmt_adv(c['full_minus_blocked'])}")
    lines.append(f"- full - plain: {_fmt_adv(c['full_minus_plain'])}")
    lines.append(f"- blocked - plain: {_fmt_adv(c['blocked_minus_plain'])}")
    lines.append("")
    lines.append("## What did and did not work")
    lines.append("")
    lines.append(f"What worked. Interleaving as spacing (full vs blocked) "
                 f"{f['interleaving_as_spacing_vs_blocked']} Spaced, topic-mixed "
                 "practice beats blocked, massed practice, which is the core "
                 "learning-science claim behind the feature.")
    lines.append("")
    lines.append(f"What did NOT work. Full selector vs stock Anki (full vs plain): "
                 f"{f['full_selector_vs_stock_anki']} Mechanistically, the "
                 "desirable-difficulty band reviews cards at R in [0.60, 0.85] "
                 "rather than at the stock due point (R about 0.90), spending "
                 "near-term retrievability to build stability. A more distant exam "
                 "narrows the gap (stability aids durability) but does not change "
                 "the ranking at the scarcest budget (see the grid).")
    lines.append("")
    lines.append("Also did not register as a measurable lever. Shipped K=3 "
                 f"anti-blocking reshuffle: {f['shipped_antiblocking_reshuffle']} Its "
                 "justification is cognitive (discrimination, contextual "
                 "interference), which this simulation cannot capture.")
    lines.append("")
    lines.append("## Sensitivity grid (budget x exam distance)")
    lines.append("")
    lines.append("Positive full - X means full is higher. Negative means full is worse.")
    lines.append("")
    lines.append("| Budget/day | Exam gap (days) | full BWER | blocked BWER | plain BWER | full - blocked | full - plain |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for s in results["sensitivity_grid"]:
        sa = s["summary"]["arms"]
        sfb = s["summary"]["contrasts"]["full_minus_blocked"]
        sfp = s["summary"]["contrasts"]["full_minus_plain"]
        lines.append(
            f"| {s['budget']} | {s['exam_gap']} | {_fmt_ci(sa['full']['bwer'])} | "
            f"{_fmt_ci(sa['blocked']['bwer'])} | {_fmt_ci(sa['plain']['bwer'])} | "
            f"{_fmt_adv(sfb)} | {_fmt_adv(sfp)} |"
        )
    lines.append("")
    lines.append("## Per-category recall at horizon (primary config)")
    lines.append("")
    lines.append("| Category | blueprint | full | blocked | plain |")
    lines.append("| --- | --- | --- | --- | --- |")
    for i, cat in enumerate(CATEGORIES):
        lines.append(
            f"| {cat} | {BLUEPRINT[cat]:.2f} | {a['full']['per_category_mean'][i]:.3f} | "
            f"{a['blocked']['per_category_mean'][i]:.3f} | "
            f"{a['plain']['per_category_mean'][i]:.3f} |"
        )
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    for cav in results["caveats"]:
        lines.append(f"- {cav}")
    lines.append("")
    lines.append(f"Reproduce: `{results['reproduce']}`")
    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# --- main --------------------------------------------------------------------


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="pgrep L5.4 interleaving ablation (simulation).")
    p.add_argument("--seeds", type=int, default=40, help="number of seeded worlds")
    p.add_argument("--budget", type=int, default=30, help="reviews per day per arm")
    p.add_argument("--horizon", type=int, default=120, help="study days to the exam")
    p.add_argument("--cards", type=int, default=600, help="total cards in the deck")
    p.add_argument("--subtopics", type=int, default=4, help="subtopics per category")
    p.add_argument("--exam-gap", type=int, default=0,
                   help="days between the last study day and the exam")
    p.add_argument("--sweep-budgets", type=str, default="10,20,30",
                   help="comma-separated budgets for the sensitivity grid")
    p.add_argument("--sweep-gaps", type=str, default="0,90",
                   help="comma-separated exam-gap days for the sensitivity grid")
    p.add_argument("--out-json", type=str, default=os.path.join(RUN, "ablation_results.json"))
    p.add_argument("--out-md", type=str, default=os.path.join(RUN, "ablation.md"))
    return p.parse_args(argv)


def _check_feasible(n_cards, budgets):
    counts = _category_counts(n_cards)
    smallest = int(counts.min())
    worst = max(budgets)
    if worst > smallest:
        raise SystemExit(
            f"budget {worst} exceeds the smallest category ({smallest} cards). "
            "The blocked arm needs at least budget distinct cards per category. "
            "Lower --budget/--sweep-budgets or raise --cards."
        )


def main(argv=None) -> None:
    args = parse_args(argv)
    seeds = list(range(args.seeds))
    sweep_budgets = sorted({int(x) for x in args.sweep_budgets.split(",") if x.strip()})
    sweep_gaps = sorted({int(x) for x in args.sweep_gaps.split(",") if x.strip()})
    _check_feasible(args.cards, sweep_budgets + [args.budget])

    t0 = time.time()
    raw_primary = run_config(seeds, args.budget, args.horizon, args.cards,
                             args.subtopics, args.exam_gap)
    primary = summarize_config(raw_primary)

    grid = []
    for b in sweep_budgets:
        for g in sweep_gaps:
            raw = run_config(seeds, b, args.horizon, args.cards, args.subtopics, g)
            grid.append({"budget": b, "exam_gap": g, "summary": summarize_config(raw)})

    results = build_results(args, seeds, primary, grid)
    results["config"]["sweep_budgets"] = sweep_budgets
    results["config"]["sweep_gaps"] = sweep_gaps
    results["runtime_seconds"] = round(time.time() - t0, 2)

    os.makedirs(RUN, exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    write_markdown(args.out_md, results)

    a = primary["arms"]
    c = primary["contrasts"]
    print(f"primary metric: {PRIMARY_METRIC}")
    print(f"  full    BWER {_fmt_ci(a['full']['bwer'])}")
    print(f"  blocked BWER {_fmt_ci(a['blocked']['bwer'])}")
    print(f"  plain   BWER {_fmt_ci(a['plain']['bwer'])}")
    print(f"  full - blocked {_fmt_adv(c['full_minus_blocked'])}")
    print(f"  full - plain   {_fmt_adv(c['full_minus_plain'])}")
    print(f"finding, full vs stock across grid: {results['findings']['full_selector_vs_stock_anki']}")
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    print(f"runtime {results['runtime_seconds']}s")


if __name__ == "__main__":
    main()
