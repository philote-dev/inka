# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep Diagnostic v0 topic placement (L2.3).

The Diagnostic places every blueprint category as ``strong`` or ``rusty`` (the
persona is post-undergraduate, so there is no cold bucket). Placement combines
the FSRS-R Memory signal (that category's ``memory_point``; ``>= 0.7`` leans
strong) with an objective quick-check ``outcome`` (``correct`` leans strong,
``wrong`` leans rusty). The quick-check outcome is the fresh, decisive signal
when present; otherwise the Memory prior decides; with neither the category
defaults to ``rusty`` (needs work). The snapshot is stored in the collection
config so it is re-runnable and survives reopen.

The response shapes are fixed by ``docs_pgrep/plan/l2-api-contract.md`` §3
(L2.3). Card data is built exactly as in ``test_pgrep_memory.py``.
"""

from __future__ import annotations

import itertools
import time

from anki import cards_pb2
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki.pgrep.blueprint import BLUEPRINT_PERCENT, CATEGORY_SLUGS
from anki.pgrep.diagnostic import (
    DIAGNOSTIC_CONFIG_KEY,
    STRONG_MEMORY_POINT,
    place,
    topics,
)
from tests.shared import getEmptyCol

_counter = itertools.count()


def _add_reviewed_card(
    col,
    topic: str | None,
    *,
    stability: float = 20.0,
    difficulty: float = 5.0,
    days_ago: int = 15,
):
    """Add one card with real FSRS memory state so it carries a retrievability.

    Mirrors ``test_pgrep_memory.py`` / ``seed.py``: promote to the review
    type/queue, attach an FSRS memory state, and set a past last-review time so
    the engine computes ``R`` in (0, 1).
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
    col.update_card(card)
    return card


def _add_strong_topic(col, topic: str, n: int = 6):
    """High stability, reviewed yesterday -> Memory point near 1 (>= 0.7)."""
    return [
        _add_reviewed_card(col, topic, stability=300.0, days_ago=1) for _ in range(n)
    ]


def _placement(data: dict, category: str):
    return next(t for t in data["topics"] if t["category"] == category)["placement"]


def _by_category(data: dict) -> dict:
    return {t["category"]: t for t in data["topics"]}


def test_topics_shape_matches_contract():
    col = getEmptyCol()

    data = topics(col)

    assert set(data) == {"topics"}
    # Every blueprint category is represented, in blueprint order.
    assert [t["category"] for t in data["topics"]] == list(CATEGORY_SLUGS)
    for entry in data["topics"]:
        assert set(entry) == {"category", "blueprint", "placement", "n_cards"}
        assert entry["blueprint"] == BLUEPRINT_PERCENT[entry["category"]]
        assert isinstance(entry["n_cards"], int)


def test_place_shape_matches_contract():
    col = getEmptyCol()

    data = place(col, [])

    assert set(data) == {"topics"}
    assert [t["category"] for t in data["topics"]] == list(CATEGORY_SLUGS)
    for entry in data["topics"]:
        assert set(entry) == {"category", "placement"}
        assert entry["placement"] in {"strong", "rusty"}


def test_fresh_collection_has_null_placements():
    col = getEmptyCol()

    data = topics(col)

    assert all(t["placement"] is None for t in data["topics"])
    assert all(t["n_cards"] == 0 for t in data["topics"])


def test_n_cards_is_derived_from_memory():
    col = getEmptyCol()
    _add_reviewed_card(col, "topic::mechanics::kinematics")
    _add_reviewed_card(col, "topic::mechanics::dynamics")
    _add_reviewed_card(col, "topic::quantum::spin")

    by_cat = _by_category(topics(col))

    assert by_cat["mechanics"]["n_cards"] == 2
    assert by_cat["quantum"]["n_cards"] == 1
    assert by_cat["thermodynamics"]["n_cards"] == 0


def test_place_stores_and_topics_reads_back():
    col = getEmptyCol()

    place(
        col,
        [
            {"category": "mechanics", "outcome": "correct"},
            {"category": "quantum", "outcome": "wrong"},
        ],
    )

    # A brand-new topics() call reflects the stored snapshot (non-null now).
    after = topics(col)
    assert all(t["placement"] in {"strong", "rusty"} for t in after["topics"])
    assert _placement(after, "mechanics") == "strong"
    assert _placement(after, "quantum") == "rusty"


def test_correct_outcome_places_strong():
    col = getEmptyCol()
    # No card data for mechanics, so only the quick-check drives the placement.
    result = place(col, [{"category": "mechanics", "outcome": "correct"}])

    assert _placement(result, "mechanics") == "strong"


def test_high_memory_point_places_strong_without_a_quick_check():
    col = getEmptyCol()
    _add_strong_topic(col, "topic::mechanics::kinematics")
    # Confirm the Memory prior is genuinely high for this category.
    assert _by_category(topics(col))["mechanics"]["n_cards"] > 0

    # No quick-check result for mechanics; the FSRS-R prior alone places it.
    result = place(col, [])

    assert _placement(result, "mechanics") == "strong"


def test_wrong_outcome_places_rusty():
    col = getEmptyCol()

    result = place(col, [{"category": "electromagnetism", "outcome": "wrong"}])

    assert _placement(result, "electromagnetism") == "rusty"


def test_no_data_and_no_result_defaults_to_rusty():
    col = getEmptyCol()

    result = place(col, [])

    # Every category lacks both card data and a quick-check result here.
    assert all(t["placement"] == "rusty" for t in result["topics"])


def test_quick_check_outcome_is_decisive_over_memory():
    col = getEmptyCol()
    # A strong Memory prior, but the fresh quick-check says wrong -> rusty.
    _add_strong_topic(col, "topic::mechanics::kinematics")

    result = place(col, [{"category": "mechanics", "outcome": "wrong"}])

    assert _placement(result, "mechanics") == "rusty"


def test_place_is_rerunnable_and_overwrites():
    col = getEmptyCol()

    place(col, [{"category": "mechanics", "outcome": "correct"}])
    assert _placement(topics(col), "mechanics") == "strong"

    # A second pass with the opposite outcome overwrites the snapshot.
    place(col, [{"category": "mechanics", "outcome": "wrong"}])
    assert _placement(topics(col), "mechanics") == "rusty"


def test_snapshot_is_persisted_in_collection_config():
    col = getEmptyCol()

    place(
        col,
        [
            {"category": "mechanics", "outcome": "correct"},
            {"category": "quantum", "outcome": "wrong"},
        ],
    )

    stored = col.get_config(DIAGNOSTIC_CONFIG_KEY)
    assert isinstance(stored, dict)
    assert stored["mechanics"] == "strong"
    assert stored["quantum"] == "rusty"
    # All blueprint categories are captured in the rolled-up snapshot.
    assert set(stored) == set(CATEGORY_SLUGS)


def test_unknown_categories_in_results_are_ignored():
    col = getEmptyCol()

    result = place(
        col,
        [
            {"category": "not_a_real_category", "outcome": "correct"},
            {"category": "mechanics", "outcome": "correct"},
        ],
    )

    categories = [t["category"] for t in result["topics"]]
    assert "not_a_real_category" not in categories
    assert categories == list(CATEGORY_SLUGS)
    assert _placement(result, "mechanics") == "strong"


def test_strong_memory_threshold_is_exposed():
    # The documented FSRS-R lean threshold is a module constant (tunable).
    assert 0.0 < STRONG_MEMORY_POINT <= 1.0
