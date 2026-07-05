# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Coverage ledger (how much of the blueprint has been touched) for pgrep.

Coverage answers "how much of the exam have you started on." In L2 a blueprint
category is **covered** once it has at least one reviewed card, and
``overall_pct`` is the summed blueprint weight of the covered categories (the
table sums to 1.0, so it reads directly as a fraction of the whole exam).

It is a thin, honest ledger built entirely on top of :mod:`anki.pgrep.memory`:
the per-category reviewed-card counts and the Memory point come straight from
:func:`anki.pgrep.memory.memory_score`, so Coverage and Memory can never
disagree and no retrievability is recomputed here. No AI, no attempt log, no
schedule mutation (``L2-api-contract.md`` §0).

The ``gate`` (0.70) is the Readiness coverage gate from
``three-scores.md`` §3/§5: Readiness abstains until coverage reaches
it. L2 shows the gate but does not compute Readiness (that lands in L5), so the
gate is informational here — ``abstain_note`` says as much.

The scaffolding bridge handler ``pgrep_coverage`` in ``qt/aqt/pgrep.py`` calls
:func:`coverage`; the signature is fixed by the L2 API contract (§3, L2.4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anki.pgrep.memory import memory_score

if TYPE_CHECKING:
    from anki.collection import Collection

# The Readiness coverage gate (``three-scores.md`` §3/§5): Readiness
# abstains until this fraction of blueprint weight is covered. Shown but not
# enforced in L2 (Readiness itself is not computed until L5).
COVERAGE_GATE = 0.70

# Why the gate is shown here without an actual Readiness number.
_ABSTAIN_NOTE = "Readiness abstains until coverage reaches the gate."


def coverage(col: Collection) -> dict:
    """Return the coverage ledger for the collection.

    The result matches the ``pgrepCoverage`` response in the L2 API contract
    (§3, L2.4): an overall covered fraction, the Readiness ``gate``, and a
    per-category ``by_topic`` ledger (in blueprint order) of covered/uncovered
    categories with their reviewed-card count and Memory point.

    ``covered`` is the L2 definition: the category has at least one reviewed
    card. ``memory_point`` is that category's Memory point from
    :func:`anki.pgrep.memory.memory_score` (``None`` while the topic still
    abstains, i.e. it has fewer than ``k_mem`` reviewed cards). ``overall_pct``
    is the summed blueprint weight of the covered categories over the whole
    blueprint (the table sums to 1.0). The result is JSON-serializable.
    """
    mem = memory_score(col)

    by_topic: list[dict[str, Any]] = []
    covered_weight = 0.0
    total_weight = 0.0
    for entry in mem["by_topic"]:
        blueprint = entry["blueprint"]
        n_cards = entry["n_cards"]
        covered = n_cards >= 1
        total_weight += blueprint
        if covered:
            covered_weight += blueprint
        by_topic.append(
            {
                "category": entry["category"],
                "blueprint": blueprint,
                "covered": covered,
                "n_cards": n_cards,
                "memory_point": entry["point"],
            }
        )

    overall_pct = covered_weight / total_weight if total_weight else 0.0

    return {
        "overall_pct": overall_pct,
        "gate": COVERAGE_GATE,
        "by_topic": by_topic,
        "abstain_note": _ABSTAIN_NOTE,
    }
