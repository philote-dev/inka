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

from anki.pgrep import diagnostic, manifold
from anki.pgrep.blueprint import CATEGORY_SLUGS
from tests.shared import getEmptyCol

_SURFACE_KEYS = {"boundary", "spread", "bumps", "dips", "holes", "glows", "labels"}


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
