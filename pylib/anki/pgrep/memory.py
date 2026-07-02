# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Memory (the honest per-topic readiness signal) for pgrep.

**Stub — implemented by the L2.2 Home / Readiness surface.**

The scaffolding bridge handler ``pgrep_memory_score`` in ``qt/aqt/pgrep.py``
already calls :func:`memory_score`; L2.2 fills in the body. Do not change the
signature — the four surfaces coordinate through the fixed handler contract.

See ``docs/pgrep/planning/l2-api-contract.md`` §3 (L2.2) for the response shape
and ``scoring-and-readiness.md`` §1 for the math (per-topic ``mean(R)`` over the
topic's reviewed cards, blueprint-weighted overall, Poisson-binomial range, and
the ``k_mem`` abstain gate). Memory is pure math over FSRS state and tags: no AI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anki.collection import Collection


def memory_score(col: Collection, deck_id: int | None = None) -> dict:
    """Return the Memory score for the collection (or one deck).

    ``deck_id`` scopes the score to a single deck when given; otherwise the
    whole collection is scored. The result matches the ``pgrepMemoryScore``
    response in the L2 API contract (§3, L2.2): ``overall`` plus a per-topic
    breakdown, each with a point estimate, an 80% range, and an abstain flag.

    Raises:
        NotImplementedError: until the L2.2 Home surface implements it.
    """
    raise NotImplementedError("implemented by L2.2 Home")
