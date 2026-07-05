# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep coverage ledger (L2.4 Progress / Coverage).

Coverage is the honest "how much of the exam have you started" signal. In L2 a
blueprint category is covered once it has at least one reviewed card, and
``overall_pct`` is the summed blueprint weight of the covered categories (the
table sums to 1.0). Coverage is a thin ledger on top of ``anki.pgrep.memory``:
the reviewed-card counts and the per-topic Memory point come straight from
``memory_score`` (``null`` while a topic still abstains). The ``gate`` (0.70) is
the Readiness coverage gate, shown here but only enforced from L5.

The response shape is fixed by ``docs_pgrep/contracts/L2-api-contract.md`` §3
(L2.4). Data is built like ``test_pgrep_memory.py`` (cards with FSRS memory
state + ``topic::`` tags).
"""

from __future__ import annotations

import itertools
import time

from anki import cards_pb2
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki.pgrep.blueprint import BLUEPRINT_PERCENT, CATEGORY_SLUGS
from anki.pgrep.coverage import COVERAGE_GATE, coverage
from anki.pgrep.memory import K_MEM_DEFAULT, memory_score
from tests.shared import getEmptyCol

_counter = itertools.count()


def _add_reviewed_card(
    col,
    topic: str | None,
    *,
    stability: float = 20.0,
    days_ago: int = 15,
):
    """Add one card with real FSRS memory state so Memory counts it as reviewed.

    Mirrors ``test_pgrep_memory.py``: promote to the review type/queue, attach an
    FSRS memory state, and set a past last-review time so the engine computes a
    retrievability (which is what makes the card count toward coverage).
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
    card.memory_state = cards_pb2.FsrsMemoryState(stability=stability, difficulty=5.0)
    card.last_review_time = int(time.time()) - days_ago * 86400
    col.update_card(card)
    return card


def _add_topic(col, topic: str, n: int):
    # Vary stability/recency a little so R is heterogeneous but deterministic.
    return [
        _add_reviewed_card(col, topic, stability=20.0 + 5.0 * i, days_ago=10 + i)
        for i in range(n)
    ]


def _entry(data: dict, category: str) -> dict:
    return next(t for t in data["by_topic"] if t["category"] == category)


def test_shape_matches_contract():
    col = getEmptyCol()
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT)

    data = coverage(col)

    assert set(data) == {"overall_pct", "gate", "by_topic", "abstain_note"}
    assert data["abstain_note"] == (
        "Readiness abstains until coverage reaches the gate."
    )
    # Every blueprint category is represented, in blueprint order.
    assert [t["category"] for t in data["by_topic"]] == list(CATEGORY_SLUGS)
    for entry in data["by_topic"]:
        assert set(entry) == {
            "category",
            "blueprint",
            "covered",
            "n_cards",
            "memory_point",
        }


def test_gate_is_the_readiness_coverage_gate():
    col = getEmptyCol()

    assert coverage(col)["gate"] == 0.70
    assert COVERAGE_GATE == 0.70


def test_covered_categories_are_exactly_those_with_a_reviewed_card():
    col = getEmptyCol()
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT)
    _add_topic(col, "topic::optics_waves::diffraction", 1)

    data = coverage(col)
    covered = {t["category"] for t in data["by_topic"] if t["covered"]}

    assert covered == {"mechanics", "optics_waves"}
    for entry in data["by_topic"]:
        if entry["category"] not in covered:
            assert entry["covered"] is False
            assert entry["n_cards"] == 0


def test_a_single_reviewed_card_covers_a_category():
    col = getEmptyCol()
    _add_reviewed_card(col, "topic::lab::instruments")

    lab = _entry(coverage(col), "lab")

    assert lab["covered"] is True
    assert lab["n_cards"] == 1


def test_overall_pct_is_the_blueprint_weight_of_covered_categories():
    col = getEmptyCol()
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT)
    _add_topic(col, "topic::optics_waves::diffraction", 1)

    data = coverage(col)
    covered = [t["category"] for t in data["by_topic"] if t["covered"]]
    expected = sum(BLUEPRINT_PERCENT[c] for c in covered) / sum(
        BLUEPRINT_PERCENT.values()
    )

    assert abs(data["overall_pct"] - expected) < 1e-9
    # Concretely mechanics (0.20) + optics_waves (0.08) over a blueprint of 1.0.
    assert abs(data["overall_pct"] - 0.28) < 1e-9


def test_zero_card_category_is_uncovered_with_null_memory_point():
    col = getEmptyCol()
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT)

    quantum = _entry(coverage(col), "quantum")

    assert quantum["covered"] is False
    assert quantum["n_cards"] == 0
    assert quantum["memory_point"] is None


def test_covered_but_below_k_mem_still_has_a_null_memory_point():
    col = getEmptyCol()
    # A single reviewed card covers the category, but Memory still abstains
    # (fewer than k_mem cards), so its memory_point is null.
    _add_reviewed_card(col, "topic::thermodynamics::entropy")

    thermo = _entry(coverage(col), "thermodynamics")

    assert thermo["covered"] is True
    assert thermo["n_cards"] == 1
    assert thermo["memory_point"] is None


def test_memory_point_reuses_memory_score():
    col = getEmptyCol()
    _add_topic(col, "topic::mechanics::kinematics", K_MEM_DEFAULT)

    mech_cov = _entry(coverage(col), "mechanics")
    mech_mem = _entry(memory_score(col), "mechanics")

    # The point is taken straight from memory_score (same value, allowing only
    # sub-second retrievability drift between the two independent calls).
    assert mech_cov["memory_point"] is not None
    assert 0.0 < mech_cov["memory_point"] < 1.0
    assert abs(mech_cov["memory_point"] - mech_mem["point"]) < 1e-6


def test_empty_collection_has_zero_coverage():
    col = getEmptyCol()

    data = coverage(col)

    assert data["overall_pct"] == 0.0
    assert data["gate"] == 0.70
    assert all(not t["covered"] for t in data["by_topic"])
    assert all(t["n_cards"] == 0 for t in data["by_topic"])
    assert all(t["memory_point"] is None for t in data["by_topic"])


def test_full_coverage_reaches_one():
    col = getEmptyCol()
    for slug in CATEGORY_SLUGS:
        _add_reviewed_card(col, f"topic::{slug}::x")

    data = coverage(col)

    assert all(t["covered"] for t in data["by_topic"])
    assert abs(data["overall_pct"] - 1.0) < 1e-9
