# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the Home knowledge-manifold read model (L5.9).

The manifold is a qualitative map that must stay honest: the nine areas always
sit on it, a fresh collection shows the unlit syllabus (no peaks or holes), and
the terrain follows the learner's real Memory and diagnostic placement. These
cover the JSON shape and the honesty invariants, driving the terrain through the
stored diagnostic placement so no FSRS review state is needed.
"""

from __future__ import annotations

import itertools
import time

from anki import cards_pb2
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki.pgrep import diagnostic, manifold
from anki.pgrep.attempt_log import append_attempt
from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.performance import K_PERF_DEFAULT, performance_score
from tests.shared import getEmptyCol

_SURFACE_KEYS = {"boundary", "spread", "bumps", "dips", "holes", "glows", "labels"}
_counter = itertools.count(1)


def _add_mastery(col, topic, n=5):
    """Give ``topic`` real FSRS memory state so it carries a Memory point (amber)."""
    for _ in range(n):
        note = col.newNote()
        note.fields[0] = f"q{next(_counter)}"
        note.tags = [topic]
        col.addNote(note)
        card = note.cards()[0]
        card.type = CARD_TYPE_REV
        card.queue = QUEUE_TYPE_REV
        card.due = 0
        card.ivl = 40
        card.memory_state = cards_pb2.FsrsMemoryState(stability=40.0, difficulty=5.0)
        card.last_review_time = int(time.time()) - 10 * 86400
        col.update_card(card)


def _append_attempts(col, topic, results):
    """Append clean problem attempts for ``topic`` so it earns a Performance point."""
    base = next(_counter) * 1000
    start = int(time.time()) - len(results) * 3600
    for i, correct in enumerate(results):
        append_attempt(
            col,
            {
                "topic": topic,
                "correct": bool(correct),
                "item_note_id": base + i,
                "answered_at": start + i * 60,
                "ladder_depth": 0,
            },
        )


def _glow_at(surface, pos):
    return next((g["c"] for g in surface["glows"] if (g["x"], g["y"]) == pos), None)


def test_manifold_surface_shape_matches_the_renderer():
    col = getEmptyCol()

    surface = manifold.manifold_surface(col)

    assert set(surface) == _SURFACE_KEYS
    assert len(surface["labels"]) == len(CATEGORY_SLUGS)
    assert len(surface["bumps"]) == len(CATEGORY_SLUGS)
    assert {label["topic"] for label in surface["labels"]} == set(CATEGORY_SLUGS)
    for label in surface["labels"]:
        assert {"name", "x", "y", "dx", "dy", "tf", "topic"} <= set(label)


def test_manifold_is_honest_on_a_fresh_collection():
    # No reviews and no diagnostic: an unlit, even syllabus. Nothing is invented,
    # so there are no glows (mastery) and no holes (known gaps).
    col = getEmptyCol()

    surface = manifold.manifold_surface(col)

    assert surface["glows"] == []
    assert surface["holes"] == []
    assert all(bump["h"] == manifold._BASE_HEIGHT for bump in surface["bumps"])


def test_manifold_reflects_the_diagnostic_placement():
    col = getEmptyCol()
    col.set_config(
        diagnostic.DIAGNOSTIC_CONFIG_KEY,
        {"mechanics": "strong", "quantum": "rusty"},
    )

    surface = manifold.manifold_surface(col)
    pos = {label["topic"]: (label["x"], label["y"]) for label in surface["labels"]}

    # A strong area lights up and rises above the unlit base.
    mechanics = pos["mechanics"]
    assert any((g["x"], g["y"]) == mechanics for g in surface["glows"])
    mech_bump = next(b for b in surface["bumps"] if (b["x"], b["y"]) == mechanics)
    assert mech_bump["h"] > manifold._BASE_HEIGHT

    # A rusty area opens a hole (a known gap) and never lights up.
    quantum = pos["quantum"]
    assert any((h["x"], h["y"]) == quantum for h in surface["holes"])
    assert not any((g["x"], g["y"]) == quantum for g in surface["glows"])


def test_manifold_colors_by_progression_stage():
    # The map travels amber -> blue -> lilac as an area progresses from memorized
    # to practiced to exam-ready, so the coloring reflects real progress, not just
    # a single Memory hue.
    col = getEmptyCol()
    # Memorized only (reviews, no problem attempts): amber.
    _add_mastery(col, "topic::mechanics::kinematics")
    # Practiced but not ready (attempts, mostly wrong): blue.
    _add_mastery(col, "topic::electromagnetism::circuits")
    _append_attempts(
        col, "topic::electromagnetism::circuits", [False] * (K_PERF_DEFAULT + 4)
    )
    # Well practiced (attempts, all correct): lilac.
    _add_mastery(col, "topic::optics_waves::ray")
    _append_attempts(col, "topic::optics_waves::ray", [True] * (K_PERF_DEFAULT + 4))

    surface = manifold.manifold_surface(col)
    perf = {t["category"]: t["point"] for t in performance_score(col)["by_topic"]}
    pos = {label["topic"]: (label["x"], label["y"]) for label in surface["labels"]}

    # Memorized only stays amber (no measured performance).
    assert perf["mechanics"] is None
    assert _glow_at(surface, pos["mechanics"]) == manifold._MEMORY_HUE

    # Practiced areas leave amber for the measured performance/readiness hue,
    # following the progression rule on their real performance point.
    for cat in ("electromagnetism", "optics_waves"):
        assert perf[cat] is not None
        glow = _glow_at(surface, pos[cat])
        assert glow != manifold._MEMORY_HUE
        assert glow == manifold._region_hue(None, perf[cat])
        assert glow in (manifold._PERFORMANCE_HUE, manifold._READINESS_HUE)
