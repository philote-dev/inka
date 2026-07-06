# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Shared helpers for the pgrep dev tools (benchmark + crash test).

This module is dev-only tooling, not a shipped surface. It does two things:

1. Makes the built ``anki`` package importable from ``out/pylib`` (the generated
   protobuf modules) alongside the editable ``pylib`` source, so the tools run
   under ``out/pyenv/bin/python`` without a manual ``PYTHONPATH``.
2. Builds a large, deterministic synthetic pgrep collection: review cards spread
   across the nine blueprint categories with real FSRS memory state, plus the
   dev-only demo study history (:func:`anki.pgrep.demo_profile.inject_demo_profile`)
   so Memory, Performance, Readiness and Coverage all score instead of abstaining.

The FSRS-state technique mirrors the sanctioned one in ``pylib/anki/pgrep/seed.py``
and ``demo_profile.py`` (``col.update_cards`` with ``memory_state``); the scheduler
is never driven during the build, so no scheduling state is fabricated.
"""

from __future__ import annotations

import os
import random
import sys
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anki.collection import Collection


def ensure_anki_importable() -> str:
    """Put the built ``anki`` (out/pylib) on ``sys.path`` and return the repo root.

    ``out/pylib/anki`` holds the generated ``*_pb2`` modules; the hand-written
    source lives in ``pylib/anki`` (already on the path via the editable install).
    Both merge into the ``anki`` namespace package once ``out/pylib`` is present.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    built = os.path.join(repo_root, "out", "pylib")
    if built not in sys.path:
        sys.path.insert(0, built)
    return repo_root


# Make anki importable as a side effect of importing this module, so callers can
# simply ``import pgrep_synth`` before importing anything from ``anki``.
REPO_ROOT = ensure_anki_importable()

# The daily new/review limit. Anki clamps ``perDay`` to a maximum of 9999 (values
# >= 10000 are rejected and silently revert to the default), so 9999 is the
# largest value that persists. It is far above the default 200/day, letting the
# tools stress the real review loop instead of the daily limiter.
_MAX_PER_DAY = 9999

# FSRS state is drawn from these ranges so retrievability has a realistic spread
# (rather than every card reading as a perfect 1.0). Deterministic per seed.
_STABILITY_RANGE = (5.0, 250.0)
_DIFFICULTY_RANGE = (3.0, 8.0)
_LAST_REVIEW_MAX_DAYS_AGO = 40
_OVERDUE_MAX_DAYS = 20


def build_collection(
    path: str,
    n_cards: int,
    seed: int = 1234,
    with_demo: bool = True,
    deck_name: str = "PGRE::Bench",
    high_limits: bool = True,
) -> tuple[Collection, dict[str, Any]]:
    """Create a synthetic pgrep collection at ``path`` and return ``(col, info)``.

    ``n_cards`` review cards are spread round-robin across the nine blueprint
    categories, each tagged ``topic::<category>`` and given deterministic FSRS
    memory state so Memory scores every category. All cards are made due (today
    or mildly overdue) so the scheduler hands them out. When ``with_demo`` is set,
    the dev demo study history is injected so Performance and Readiness score too.

    ``info`` reports the build timings and counts (for honest reporting).
    """
    from anki import cards_pb2
    from anki.collection import AddNoteRequest, Collection
    from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
    from anki.pgrep import demo_profile
    from anki.pgrep.blueprint import CATEGORY_SLUGS

    rng = random.Random(seed)
    col = Collection(path)

    basic = col.models.by_name("Basic")
    if basic is None:
        raise RuntimeError("default 'Basic' notetype not found in collection")

    deck_id = col.decks.id(deck_name)
    assert deck_id is not None
    if high_limits:
        conf = col.decks.config_dict_for_deck_id(deck_id)
        conf["new"]["perDay"] = _MAX_PER_DAY
        conf["rev"]["perDay"] = _MAX_PER_DAY
        col.decks.update_config(conf)
    col.decks.set_current(deck_id)

    today = col.sched.today
    now = int(time.time())

    t0 = time.perf_counter()
    requests: list[AddNoteRequest] = []
    for i in range(n_cards):
        category = CATEGORY_SLUGS[i % len(CATEGORY_SLUGS)]
        note = col.new_note(basic)
        note["Front"] = f"PGRE bench card {i} ({category})"
        note["Back"] = "Synthetic benchmark content (dev only)."
        note.tags = [f"topic::{category}"]
        requests.append(AddNoteRequest(note=note, deck_id=deck_id))
    col.add_notes(requests)
    t_add = time.perf_counter() - t0

    t0 = time.perf_counter()
    cards = []
    for req in requests:
        card = col.get_card(next(iter(col.card_ids_of_note(req.note.id))))
        stability = rng.uniform(*_STABILITY_RANGE)
        difficulty = rng.uniform(*_DIFFICULTY_RANGE)
        card.type = CARD_TYPE_REV
        card.queue = QUEUE_TYPE_REV
        card.due = max(0, today - rng.randint(0, _OVERDUE_MAX_DAYS))
        card.ivl = max(1, int(stability))
        card.memory_state = cards_pb2.FsrsMemoryState(
            stability=stability, difficulty=difficulty
        )
        card.last_review_time = now - rng.randint(0, _LAST_REVIEW_MAX_DAYS_AGO) * 86400
        cards.append(card)
    col.update_cards(cards)
    t_state = time.perf_counter() - t0

    demo_summary = None
    t_demo = 0.0
    if with_demo:
        t0 = time.perf_counter()
        demo_summary = demo_profile.inject_demo_profile(col)
        t_demo = time.perf_counter() - t0

    info: dict[str, Any] = {
        "n_cards": n_cards,
        "deck": deck_name,
        "seed": seed,
        "card_count": col.card_count(),
        "note_count": col.note_count(),
        "demo": demo_summary,
        "build_seconds": {
            "add_notes": t_add,
            "fsrs_state": t_state,
            "inject_demo": t_demo,
        },
    }
    return col, info
