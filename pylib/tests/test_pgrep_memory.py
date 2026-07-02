# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep Memory score (L2.2 Home / Readiness).

Memory is the honest ``P(recall now)`` signal: per-topic ``mean(R)`` over that
topic's reviewed cards (``R`` is FSRS retrievability from the engine), a
blueprint-weighted overall, an 80% likely range from the Poisson-binomial, and
an abstain when a topic has fewer than ``k_mem`` reviewed cards. It is pure math
over FSRS state and topic tags: no AI, no attempt log, no schedule mutation.

The response shape is fixed by ``docs/pgrep/planning/l2-api-contract.md`` §3
(L2.2); the math by ``scoring-and-readiness.md`` §1.
"""

from __future__ import annotations

import itertools
import time

from anki import cards_pb2
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki.pgrep.blueprint import BLUEPRINT_PERCENT, CATEGORY_SLUGS
from anki.pgrep.memory import K_MEM_DEFAULT, memory_score
from tests.shared import getEmptyCol

_counter = itertools.count()


def _add_reviewed_card(
    col,
    topic: str | None,
    *,
    stability: float = 20.0,
    difficulty: float = 5.0,
    days_ago: int = 15,
    deck_id: int | None = None,
):
    """Add one card with real FSRS memory state so it carries a retrievability.

    Mirrors ``test_pgrep_selector.py`` / ``seed.py``: promote to the review
    type/queue, attach an FSRS memory state, and set a past last-review time so
    the engine computes ``R`` in (0, 1). ``days_ago >= 1`` keeps ``R < 1``.
    """
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
    if deck_id is not None:
        card.did = deck_id
    col.update_card(card)
    return card


def _add_topic(col, topic: str, n: int, *, base_stability: float = 20.0, **kwargs):
    # Vary stability a little across the topic so R is heterogeneous (a real
    # Poisson-binomial range), but stay deterministic.
    return [
        _add_reviewed_card(
            col, topic, stability=base_stability + 5.0 * i, days_ago=10 + i, **kwargs
        )
        for i in range(n)
    ]


def _topic(data: dict, category: str) -> dict:
    return next(t for t in data["by_topic"] if t["category"] == category)


def test_shape_matches_contract():
    col = getEmptyCol()
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT)

    data = memory_score(col)

    assert set(data) == {"overall", "by_topic", "k_mem", "last_updated"}
    assert data["k_mem"] == K_MEM_DEFAULT
    assert set(data["overall"]) == {"point", "low", "high", "abstain", "reason"}
    # Every blueprint category is represented, in blueprint order.
    assert [t["category"] for t in data["by_topic"]] == list(CATEGORY_SLUGS)
    for entry in data["by_topic"]:
        assert set(entry) == {
            "category",
            "blueprint",
            "point",
            "low",
            "high",
            "n_cards",
            "abstain",
            "reason",
        }


def test_topic_with_enough_cards_scores_with_a_range():
    col = getEmptyCol()
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT)

    mech = _topic(memory_score(col), "mechanics")

    assert mech["abstain"] is False
    assert mech["reason"] is None
    assert mech["n_cards"] == K_MEM_DEFAULT
    assert mech["blueprint"] == BLUEPRINT_PERCENT["mechanics"]
    # A real point in (0, 1) with a bracketing 80% range inside [0, 1].
    assert 0.0 < mech["point"] < 1.0
    assert 0.0 <= mech["low"] <= mech["point"] <= mech["high"] <= 1.0
    assert mech["low"] < mech["high"]


def test_topic_below_threshold_abstains():
    col = getEmptyCol()
    _add_topic(col, "topic::quantum::spin", K_MEM_DEFAULT - 1)

    quantum = _topic(memory_score(col), "quantum")

    assert quantum["n_cards"] == K_MEM_DEFAULT - 1
    assert quantum["abstain"] is True
    assert quantum["point"] is None
    assert quantum["low"] is None
    assert quantum["high"] is None
    assert quantum["reason"] == "Not enough cards yet"


def test_k_mem_is_a_parameter():
    col = getEmptyCol()
    _add_topic(col, "topic::quantum::spin", 3)

    assert _topic(memory_score(col), "quantum")["abstain"] is True
    # Lowering the threshold lets the same topic score.
    assert _topic(memory_score(col, k_mem=3), "quantum")["abstain"] is False


def test_untagged_and_unknown_cards_are_excluded():
    col = getEmptyCol()
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT)
    # Untagged reviewed card, and a card whose category is not on the blueprint.
    _add_reviewed_card(col, None)
    _add_reviewed_card(col, "topic::not_a_real_category")

    data = memory_score(col)

    assert "unknown" not in [t["category"] for t in data["by_topic"]]
    # Only the tagged, on-blueprint cards are counted anywhere.
    assert sum(t["n_cards"] for t in data["by_topic"]) == K_MEM_DEFAULT
    assert _topic(data, "mechanics")["n_cards"] == K_MEM_DEFAULT


def test_overall_is_blueprint_weighted_over_scored_topics():
    col = getEmptyCol()
    # Two topics score; give them different R so the weighting is observable.
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT, base_stability=120.0)
    _add_topic(
        col, "topic::electromagnetism::circuits", K_MEM_DEFAULT, base_stability=6.0
    )
    # A third topic stays below threshold and must not enter the overall.
    _add_topic(col, "topic::quantum::spin", K_MEM_DEFAULT - 1)

    data = memory_score(col)
    scored = {t["category"]: t for t in data["by_topic"] if not t["abstain"]}

    assert set(scored) == {"mechanics", "electromagnetism"}
    num = sum(BLUEPRINT_PERCENT[c] * scored[c]["point"] for c in scored)
    den = sum(BLUEPRINT_PERCENT[c] for c in scored)
    assert data["overall"]["abstain"] is False
    assert abs(data["overall"]["point"] - num / den) < 1e-6
    assert 0.0 <= data["overall"]["low"] <= data["overall"]["point"]
    assert data["overall"]["point"] <= data["overall"]["high"] <= 1.0


def test_overall_abstains_when_no_topic_qualifies():
    col = getEmptyCol()
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT - 1)
    _add_topic(col, "topic::quantum::spin", K_MEM_DEFAULT - 1)

    overall = memory_score(col)["overall"]

    assert overall["abstain"] is True
    assert overall["point"] is None
    assert overall["low"] is None
    assert overall["high"] is None
    assert overall["reason"]


def test_empty_collection_abstains_everywhere():
    col = getEmptyCol()

    data = memory_score(col)

    assert data["overall"]["abstain"] is True
    assert data["last_updated"] is None
    assert all(t["abstain"] and t["n_cards"] == 0 for t in data["by_topic"])


def test_higher_stability_and_recency_yield_higher_memory():
    col = getEmptyCol()
    # Strong: high stability, reviewed yesterday -> R near 1.
    _add_topic(
        col, "topic::mechanics::kinematics", K_MEM_DEFAULT, base_stability=300.0
    )
    for _ in range(K_MEM_DEFAULT):
        _add_reviewed_card(
            col, "topic::mechanics::kinematics", stability=300.0, days_ago=1
        )
    # Weak: low stability, reviewed long ago -> R low.
    for _ in range(K_MEM_DEFAULT):
        _add_reviewed_card(col, "topic::quantum::spin", stability=2.0, days_ago=120)

    data = memory_score(col)
    strong = _topic(data, "mechanics")["point"]
    weak = _topic(data, "quantum")["point"]

    assert strong > weak
    assert 0.0 < weak < strong < 1.0


def test_deck_scope_restricts_the_cards():
    col = getEmptyCol()
    other = col.decks.id("Scoped")
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT)
    _add_topic(
        col, "topic::electromagnetism::circuits", K_MEM_DEFAULT, deck_id=other
    )

    scoped = memory_score(col, deck_id=other)

    # Only the electromagnetism cards live in the scoped deck.
    assert _topic(scoped, "electromagnetism")["abstain"] is False
    assert _topic(scoped, "electromagnetism")["n_cards"] == K_MEM_DEFAULT
    assert _topic(scoped, "mechanics")["n_cards"] == 0
    assert _topic(scoped, "mechanics")["abstain"] is True
