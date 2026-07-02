# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Diagnostic v0 (topic placement) for pgrep.

**Stub — implemented by the L2.3 Diagnostic surface.**

The scaffolding bridge handlers ``pgrep_diagnostic_topics`` and
``pgrep_diagnostic_place`` in ``qt/aqt/pgrep.py`` already call :func:`topics`
and :func:`place`; L2.3 fills in the bodies. Do not change the signatures — the
four surfaces coordinate through the fixed handler contract.

See ``docs/pgrep/planning/l2-api-contract.md`` §3 (L2.3) for the response
shapes. The persona is post-undergraduate, so there is no cold bucket: every
covered topic is labelled ``strong`` or ``rusty`` (seeded from FSRS R plus the
quick check). The placement snapshot is stored in the collection config and is
re-runnable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anki.collection import Collection


def topics(col: Collection) -> dict:
    """Return the topics to place, with any existing placement.

    The result matches the ``pgrepDiagnosticTopics`` response in the L2 API
    contract (§3, L2.3): a list of categories with blueprint weight, current
    placement (``strong``/``rusty``/``null``), and reviewed-card count.

    Raises:
        NotImplementedError: until the L2.3 Diagnostic surface implements it.
    """
    raise NotImplementedError("implemented by L2.3 Diagnostic")


def place(col: Collection, results: list) -> dict:
    """Record placement outcomes and return the resolved placements.

    ``results`` is the list of ``{"category", "outcome"}`` items from the quick
    check. The result matches the ``pgrepDiagnosticPlace`` response in the L2
    API contract (§3, L2.3): each covered category labelled ``strong`` or
    ``rusty``. The snapshot is persisted to the collection config.

    Raises:
        NotImplementedError: until the L2.3 Diagnostic surface implements it.
    """
    raise NotImplementedError("implemented by L2.3 Diagnostic")
