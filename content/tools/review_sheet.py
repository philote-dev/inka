"""Shared plumbing for the disposable make/apply review sheets.

The pool, figure, and technique-giveaway passes all speak one Markdown
contract: a sheet is a header followed by one block per flagged item, each block
starting with ``### <id>`` and ending in a machine-parseable
``-> your call: <verdict>`` line. The ``make_*`` scripts render those sheets from
flagged items; the ``apply_*`` scripts read the filled verdicts back.

This module is the single home for the three pieces every stage used to carry
its own copy of: the verdict parser (:func:`parse`), the sheet assembler
(:func:`build`), and the default-recommendation manifest (:func:`manifest`).
Each stage supplies only what actually differs: its id pattern, its ``recommend``
default, and its ``block`` renderer.

Pure standard library, import-safe and runnable under plain ``python3``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")

# The id shape every current stage flags. Stages pass this to `parse`; keeping it
# a named default rather than a hardcode leaves `parse` generic over the id form.
PROBLEM_ID_RE = r"(p4-prob-\d+)"


def parse(md: str, id_re: str, default: str = "KEEP") -> dict[str, str]:
    """Read the filled ``-> your call:`` verdicts out of a reviewed sheet.

    Split on the ``\\n### `` block boundary, keep blocks whose start matches
    ``id_re`` (which must capture the id in group 1), and record the trimmed
    text after ``-> your call:``. A block with no such value falls back to
    ``default``, the stage's default verdict. This is the exact ``parse_verdicts``
    the ``apply_*`` scripts each carried.
    """
    out: dict[str, str] = {}
    for b in re.split(r"\n### ", "\n" + md):
        m = re.match(id_re, b)
        if not m:
            continue
        cm = re.search(r"-> your call:\s*(.+)", b)
        out[m.group(1)] = cm.group(1).strip() if cm else default
    return out


def build(
    items: Iterable[T],
    *,
    header: Iterable[str],
    recommend: Callable[[T], str],
    block: Callable[[T], str],
    id_of: Callable[[T], str],
) -> str:
    """Assemble a review sheet: the header lines, then one block per item.

    Reproduces byte for byte the ``"\\n".join(head) + "\\n" + "\\n".join(blocks)``
    each ``make_*`` script used. ``block(item)`` renders a full stage block, from
    ``### <id>`` through its trailing ``---``, and closes over the stage's own
    ``recommend`` to fill the recommendation and pre-filled verdict lines.
    ``recommend`` and ``id_of`` are the same per-stage hooks handed to
    :func:`manifest`; they are named here so a stage declares its whole contract
    in one call, while the emitted bytes come from ``header`` and ``block``.
    """
    return "\n".join(header) + "\n" + "\n".join(block(item) for item in items)


def manifest(
    items: Iterable[T],
    *,
    recommend: Callable[[T], str],
    id_of: Callable[[T], str],
) -> dict[str, str]:
    """Map each item's id to its default recommendation.

    This is the ``{id: recommend(item)}`` mapping the three ``make_*`` scripts
    write into their ``*.manifest.json`` (pool and figure nest it under a
    ``review`` key, giveaway writes it flat). Insertion order follows ``items``,
    matching the original comprehensions, so the serialized bytes do not change.
    """
    return {id_of(item): recommend(item) for item in items}
