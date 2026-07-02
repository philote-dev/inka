# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Coverage ledger (how much of the blueprint has been touched) for pgrep.

**Stub — implemented by the L2.4 Progress / Coverage surface.**

The scaffolding bridge handler ``pgrep_coverage`` in ``qt/aqt/pgrep.py`` already
calls :func:`coverage`; L2.4 fills in the body. Do not change the signature —
the four surfaces coordinate through the fixed handler contract.

See ``docs/pgrep/planning/l2-api-contract.md`` §3 (L2.4) for the response shape.
In L2, ``coverage`` is the fraction of blueprint weight whose category has at
least one reviewed card (the ``k_perf`` readiness gate lands in L5). It reuses
``anki.pgrep.memory`` for each topic's point estimate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anki.collection import Collection


def coverage(col: Collection) -> dict:
    """Return the coverage ledger for the collection.

    The result matches the ``pgrepCoverage`` response in the L2 API contract
    (§3, L2.4): an overall covered fraction, the gate, and a per-topic ledger
    of covered/uncovered categories with their Memory point estimate.

    Raises:
        NotImplementedError: until the L2.4 Progress surface implements it.
    """
    raise NotImplementedError("implemented by L2.4 Progress")
