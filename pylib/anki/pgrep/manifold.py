# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The knowledge-manifold read model for the Home hero (L5.9).

The Home manifold is a qualitative map of the nine exam areas, and it is honest
by construction. The nine areas always sit on the map, because the syllabus
exists, but the terrain is the learner's real state, not decoration:

- an area the learner has studied rises and lights up, tinted by how far it has
  come: amber once memorized, blue once its problem performance is measured, and
  lilac once that performance clears the ready bar. Its height grows with the mean
  FSRS retrievability of its cards (or measured performance when unreviewed);
- an area the diagnostic marked rusty, or whose Memory has dropped below a floor,
  opens a hole (a known gap);
- a fresh collection shows the unlit syllabus, gentle and even, with no peaks,
  glows, or holes, so nothing about the learner is fabricated.

It is pure math over Memory (the same primitive :func:`anki.pgrep.memory.memory_score`
serves, so the map and the Memory card never disagree) plus the stored diagnostic
placement. No AI, and no scheduling state is read or written. The returned shape
matches the ``Surface`` the renderer consumes (``ts/lib/pgrep/manifold.ts``):
``boundary``, ``spread``, ``bumps``, ``dips``, ``holes``, ``glows``, ``labels``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anki.pgrep.memory import memory_score
from anki.pgrep.performance import performance_score

if TYPE_CHECKING:
    from anki.collection import Collection

# Where each area sits on the map and how its label is offset. This mirrors the
# label placement in ``ts/lib/pgrep/manifold.ts`` (the design's fixed layout);
# only the terrain below is driven by live data.
_LAYOUT: tuple[dict[str, Any], ...] = (
    {
        "topic": "mechanics",
        "name": "Classical Mechanics",
        "x": -0.6,
        "y": -0.5,
        "dx": -60,
        "dy": -44,
        "tf": "translate(-100%, -100%)",
    },  # noqa: E501
    {
        "topic": "electromagnetism",
        "name": "Electromagnetism",
        "x": 0.56,
        "y": -0.48,
        "dx": 30,
        "dy": -60,
        "tf": "translate(0, -100%)",
    },  # noqa: E501
    {
        "topic": "optics_waves",
        "name": "Optics & Waves",
        "x": 1.0,
        "y": -0.14,
        "dx": 54,
        "dy": -22,
        "tf": "translate(0, -100%)",
    },  # noqa: E501
    {
        "topic": "thermodynamics",
        "name": "Thermo & Stat Mech",
        "x": -1.05,
        "y": 0.14,
        "dx": -54,
        "dy": 26,
        "tf": "translate(-100%, 0)",
    },  # noqa: E501
    {
        "topic": "quantum",
        "name": "Quantum Mechanics",
        "x": 0.16,
        "y": 0.6,
        "dx": -60,
        "dy": 190,
        "tf": "translate(-100%, 0)",
    },  # noqa: E501
    {
        "topic": "atomic",
        "name": "Atomic Physics",
        "x": 0.72,
        "y": 0.4,
        "dx": 64,
        "dy": 46,
        "tf": "translate(0, 0)",
    },  # noqa: E501
    {
        "topic": "special_relativity",
        "name": "Special Relativity",
        "x": -0.56,
        "y": 0.62,
        "dx": -50,
        "dy": 62,
        "tf": "translate(-100%, 0)",
    },  # noqa: E501
    {
        "topic": "lab",
        "name": "Laboratory Methods",
        "x": -0.05,
        "y": -0.62,
        "dx": 10,
        "dy": -60,
        "tf": "translate(-50%, -100%)",
    },  # noqa: E501
    {
        "topic": "specialized",
        "name": "Specialized Topics",
        "x": 0.16,
        "y": 0.04,
        "dx": 30,
        "dy": 195,
        "tf": "translate(0, 0)",
    },  # noqa: E501
)

# Design constants for the map frame (copied from the renderer's FULL_SURFACE so
# the live map keeps the same silhouette). These are presentation, not data.
_BOUNDARY: tuple[float, ...] = (1.12, 0.09, 2.6, 0.2, 0.55)
_SPREAD = 0.42

# The reserved score hues (match SCORE_COLORS in manifold.ts). An area is tinted
# by the furthest stage it has reached, so the map travels muted -> amber (memorized)
# -> blue (practiced) -> lilac (ready) as the learner progresses.
_MEMORY_HUE = "235,203,139"  # amber
_PERFORMANCE_HUE = "129,161,193"  # blue
_READINESS_HUE = "196,167,214"  # lilac
# Performance at or above this reads as exam-ready (lilac); below it but measured,
# practiced (blue). Mirrors READY_PERF in the manifold lab.
_READY_PERF = 0.7

# Terrain tuning. Every area shows a modest base so the syllabus reads even when
# unlit; mastery adds up to ``_MASTERY_GAIN`` more height. A scored area below the
# weak floor (or a rusty diagnostic) opens a hole.
_BASE_HEIGHT = 0.16
_MASTERY_GAIN = 0.5
_BASE_SPREAD = 0.28
_STRONG_WITHOUT_REVIEWS = 0.5  # diagnostic-strong but unreviewed: a half-lit rise
_WEAK_MEMORY = 0.45


def _diagnostic_placement(col: Collection) -> dict[str, str]:
    """The stored strong/rusty placement snapshot, or an empty map if never run."""
    from anki.pgrep import diagnostic

    stored = col.get_config(diagnostic.DIAGNOSTIC_CONFIG_KEY, {})
    return dict(stored) if isinstance(stored, dict) else {}


def _region_hue(mem_point: float | None, perf_point: float | None) -> str:
    """The glow hue for a lit area: the furthest progression stage it has reached.

    Blue once problem performance is measured, lilac once that performance clears
    the ready bar, amber for a memorized-only (or diagnostic-strong) area.
    """
    if perf_point is not None:
        return _READINESS_HUE if float(perf_point) >= _READY_PERF else _PERFORMANCE_HUE
    return _MEMORY_HUE


def manifold_surface(col: Collection, deck_id: int | None = None) -> dict[str, Any]:
    """Build the Home manifold surface from live Memory and the diagnostic.

    ``deck_id`` scopes only the Memory (FSRS card) component, matching the score
    read models. The result is JSON-serializable and honest: an untouched area is
    a gentle unlit base, a studied area rises and glows, a known-weak area opens a
    hole. Nothing here invents a number; the terrain is the Memory primitive.
    """
    by_category = {
        e["category"]: e for e in memory_score(col, deck_id=deck_id)["by_topic"]
    }
    # Problem performance per area, so a practiced area travels from amber to blue,
    # and a well-practiced one to lilac (the progression coloring; the L5.9 lab).
    perf_by_category = {
        e["category"]: e for e in performance_score(col, deck_id=deck_id)["by_topic"]
    }
    placement = _diagnostic_placement(col)

    bumps: list[dict[str, Any]] = []
    dips: list[dict[str, Any]] = []
    holes: list[dict[str, Any]] = []
    glows: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []

    for area in _LAYOUT:
        category = area["topic"]
        x, y = area["x"], area["y"]
        entry = by_category.get(category, {})
        point = entry.get("point")
        perf_point = perf_by_category.get(category, {}).get("point")
        place = placement.get(category)

        # Height follows Memory first (the honest retrievability), then measured
        # performance, then a diagnostic-strong half-lit rise. The hue then tints
        # the lit area by the furthest stage it has reached.
        height = _BASE_HEIGHT
        lit = False
        if point is not None:
            height = _BASE_HEIGHT + _MASTERY_GAIN * float(point)
            lit = True
        elif perf_point is not None:
            height = _BASE_HEIGHT + _MASTERY_GAIN * float(perf_point)
            lit = True
        elif place == "strong":
            height = _BASE_HEIGHT + _MASTERY_GAIN * _STRONG_WITHOUT_REVIEWS
            lit = True

        bumps.append({"x": x, "y": y, "h": round(height, 3), "s": _BASE_SPREAD})
        if lit:
            glows.append({"x": x, "y": y, "c": _region_hue(point, perf_point)})

        known_weak = place == "rusty" or (
            point is not None and float(point) < _WEAK_MEMORY
        )
        if known_weak:
            holes.append({"x": x, "y": y, "rx": 0.16, "ry": 0.1, "rot": 0.0})
            dips.append({"x": x, "y": y, "h": 0.12, "s": 0.26})

        labels.append(
            {
                "name": area["name"],
                "x": x,
                "y": y,
                "dx": area["dx"],
                "dy": area["dy"],
                "tf": area["tf"],
                "topic": category,
            }
        )

    return {
        "boundary": list(_BOUNDARY),
        "spread": _SPREAD,
        "bumps": bumps,
        "dips": dips,
        "holes": holes,
        "glows": glows,
        "labels": labels,
    }
