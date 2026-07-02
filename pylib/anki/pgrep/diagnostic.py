# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Diagnostic v0 (topic placement) for pgrep.

The Diagnostic seeds the per-topic strength map that the rest of pgrep reads
from. It places every blueprint category into one of two buckets, ``strong`` or
``rusty``. The persona is post-undergraduate, so there is **no cold-start
bucket**: a category the learner has never touched is not "unknown", it is
``rusty`` (needs work) until proven otherwise.

Two signals feed the placement, and they are combined deterministically:

- **FSRS-R (Memory) prior.** Each category's ``memory_point`` from
  :func:`anki.pgrep.memory.memory_score` is the honest ``P(recall now)`` over
  that category's reviewed cards. A point ``>= 0.7`` (:data:`STRONG_MEMORY_POINT`)
  leans the category strong. A category with too little card data has no point
  (``None``) and so does not lean strong on its own.
- **Quick-check outcome.** An objective one-question self-check per category
  yields ``correct`` or ``wrong`` (never a confidence / self-rating). ``correct``
  leans strong, ``wrong`` leans rusty.

**The exact placement rule** (see :func:`_placement_for`):

1. If the category has a quick-check outcome, that fresh objective signal is
   decisive: ``correct`` -> ``strong``, ``wrong`` -> ``rusty``. It overrides the
   Memory prior (a wrong answer now means the material needs work even if FSRS
   still rates the old cards highly, and a correct answer now clears it even if
   the cards are stale).
2. Otherwise fall back to the Memory prior: ``memory_point >= 0.7`` -> ``strong``.
3. With neither a quick-check nor a qualifying Memory point, default to
   ``rusty`` (needs work). No cold bucket.

The resulting snapshot (``{category: "strong"|"rusty"}`` for every blueprint
category) is persisted as small rolled-up state in the collection config under
:data:`DIAGNOSTIC_CONFIG_KEY`, so the Diagnostic is re-runnable (a later pass
overwrites) and survives reopen. It is pure, deterministic, and fast: one Memory
SQL pass plus a dict fold, no AI, no confidence capture, no schedule mutation
(``l2-api-contract.md`` §0).

The scaffolding bridge handlers ``pgrep_diagnostic_topics`` and
``pgrep_diagnostic_place`` in ``qt/aqt/pgrep.py`` call :func:`topics` and
:func:`place`; the signatures are fixed by the L2 API contract (§3, L2.3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anki.pgrep.blueprint import BLUEPRINT_PERCENT, CATEGORY_SLUGS
from anki.pgrep.memory import memory_score

if TYPE_CHECKING:
    from anki.collection import Collection

# Collection-config key holding the rolled-up placement snapshot
# (``{category: "strong"|"rusty"}``). Kept tiny so it is cheap to sync.
DIAGNOSTIC_CONFIG_KEY = "pgrep_diagnostic"

# The two placement buckets. No cold bucket (post-undergraduate persona).
STRONG = "strong"
RUSTY = "rusty"
_PLACEMENTS = (STRONG, RUSTY)

# Objective quick-check outcomes (never a confidence / self-rating).
OUTCOME_CORRECT = "correct"
OUTCOME_WRONG = "wrong"

# A Memory point at or above this leans a category strong on the FSRS-R prior
# alone (matches Memory's own "in your head" reading; tunable).
STRONG_MEMORY_POINT = 0.7


def _memory_by_category(col: Collection) -> dict[str, dict[str, Any]]:
    """Per-category Memory entry (``point``, ``n_cards``, ...) keyed by slug."""
    return {t["category"]: t for t in memory_score(col)["by_topic"]}


def _stored_snapshot(col: Collection) -> dict[str, str]:
    """The persisted placement snapshot, or an empty map if never run."""
    stored = col.get_config(DIAGNOSTIC_CONFIG_KEY, {})
    if not isinstance(stored, dict):
        return {}
    return stored


def _placement_for(memory_point: float | None, outcome: str | None) -> str:
    """Combine the FSRS-R prior and the quick-check outcome into one bucket.

    The quick-check outcome is the fresh, decisive signal when present; the
    Memory prior is the fallback; the default is ``rusty``. See the module
    docstring for the full rule.
    """
    if outcome == OUTCOME_CORRECT:
        return STRONG
    if outcome == OUTCOME_WRONG:
        return RUSTY
    if memory_point is not None and memory_point >= STRONG_MEMORY_POINT:
        return STRONG
    return RUSTY


def topics(col: Collection) -> dict:
    """Return the topics to place, with any existing placement.

    Matches the ``pgrepDiagnosticTopics`` response (``l2-api-contract.md`` §3,
    L2.3): every blueprint category, in blueprint order, with its blueprint
    weight, the placement stored by a previous :func:`place` run
    (``strong``/``rusty``) or ``None`` if never placed, and the reviewed-card
    count derived from Memory.
    """
    stored = _stored_snapshot(col)
    memory = _memory_by_category(col)

    out: list[dict[str, Any]] = []
    for category in CATEGORY_SLUGS:
        placement = stored.get(category)
        out.append(
            {
                "category": category,
                "blueprint": BLUEPRINT_PERCENT[category],
                "placement": placement if placement in _PLACEMENTS else None,
                "n_cards": int(memory.get(category, {}).get("n_cards", 0)),
            }
        )
    return {"topics": out}


def place(col: Collection, results: list) -> dict:
    """Record a placement pass and return the resulting strong/rusty map.

    ``results`` is a list of ``{"category", "outcome"}`` items from the objective
    quick check (``outcome`` is ``"correct"`` or ``"wrong"``, never a
    confidence). Each blueprint category is placed by :func:`_placement_for`
    (quick-check decisive, else the Memory prior, else ``rusty``); off-blueprint
    categories in ``results`` are ignored. The full snapshot is persisted to the
    collection config (re-runnable; a later pass overwrites).

    Matches the ``pgrepDiagnosticPlace`` response (``l2-api-contract.md`` §3,
    L2.3): every blueprint category, in blueprint order, labelled ``strong`` or
    ``rusty``.
    """
    outcome_by_category: dict[str, str] = {}
    for item in results or []:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        if isinstance(category, str) and category in BLUEPRINT_PERCENT:
            outcome_by_category[category] = item.get("outcome")

    memory = _memory_by_category(col)

    snapshot: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for category in CATEGORY_SLUGS:
        placement = _placement_for(
            memory.get(category, {}).get("point"),
            outcome_by_category.get(category),
        )
        snapshot[category] = placement
        out.append({"category": category, "placement": placement})

    col.set_config(DIAGNOSTIC_CONFIG_KEY, snapshot)
    return {"topics": out}
