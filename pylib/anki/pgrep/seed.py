# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Bundled default cards for pgrep (scaffolding-owned).

:func:`seed_sample_content` idempotently ensures a ``PGRE::Sample`` deck of
topic-tagged ``Basic`` cards spread across the PGRE categories, loaded from the
committed, corpus-grounded content bundle (:data:`BUNDLE_CARDS`, built from the
P4 triage-approved set). Every card carries its finest blueprint topic tag, real
``source_ref`` provenance (appended to the answer), and its authored
conceptual/computational kind (as a tag).

Cards land **cold**: they are ordinary new notes with no FSRS review state, so a
freshly seeded collection is honest. Memory abstains until the learner actually
studies, and no scheduling state is ever fabricated or mutated. The dev-only P5
demo injector is what lights up scores for demos; this seeder never does.

The sample deck is given its own deck-config group whose ``reviewOrder`` is set
to the L1 points-at-stake selector variant, so ``get_queued_cards`` returns
worth-ordered cards for free (once cards have review state) without touching the
user's default review order. Cards are inserted round-robin across categories so
the cold new queue is topic-varied from the first card.

Idempotency: a marker tag (:data:`SEEDED_TAG`) on every seeded note means a
second call creates nothing (no duplicate cards). The note adds are one batch
under a single named undo entry. See
``docs_pgrep/contracts/L2-api-contract.md`` §2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from anki import deck_config_pb2
from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.tags import category_of

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.decks import DeckId
    from anki.models import NotetypeDict
    from anki.notes import Note

# The sample deck and its dedicated deck-config group share this name.
DECK_NAME = "PGRE::Sample"
DECK_CONFIG_NAME = "PGRE::Sample"

# Marker tag on every seeded note; drives idempotency (never duplicate cards).
SEEDED_TAG = "pgrep::seeded"

TOPIC_PREFIX = "topic::"
# Each seeded card also carries its authored conceptual/computational kind as a
# tag (not a topic:: tag, so it never affects topic parsing).
KIND_TAG_PREFIX = "pgrep::kind::"

POINTS_AT_STAKE = (
    deck_config_pb2.DeckConfig.Config.ReviewCardOrder.REVIEW_CARD_ORDER_POINTS_AT_STAKE
)

# The committed content bundle lives next to this module.
_BUNDLE_PATH = Path(__file__).with_name("content_bundle.json")


def _load_bundle_cards() -> list[dict[str, Any]]:
    with _BUNDLE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)["cards"]


# The curated default cards (P4 triage-approved, corpus-grounded). Each record is
# ``{"id", "topic", "kind", "front", "back", "source_ref"}``.
BUNDLE_CARDS: tuple[dict[str, Any], ...] = tuple(_load_bundle_cards())

# The categories this seed touches (for the summary dict).
SEEDED_CATEGORIES: tuple[str, ...] = tuple(
    sorted({category_of(card["topic"]) for card in BUNDLE_CARDS})
)


def seed_sample_content(col: Collection) -> dict[str, Any]:
    """Idempotently seed the ``PGRE::Sample`` deck; return a summary dict.

    The summary has ``deck_id`` (int), ``cards_created`` (int; 0 on repeat
    calls), ``categories`` (the category slugs touched), and ``already_seeded``
    (bool). Safe to call repeatedly: a marker tag prevents duplicate cards. Cards
    land cold (no FSRS review state); the scheduler is never touched.
    """
    from anki.collection import AddNoteRequest

    deck_id = col.decks.id(DECK_NAME)
    assert deck_id is not None
    _ensure_points_at_stake_config(col, deck_id)

    # Idempotency guard: if any seeded note exists, do nothing further.
    if col.find_notes(f"tag:{SEEDED_TAG}"):
        return {
            "deck_id": int(deck_id),
            "cards_created": 0,
            "categories": list(SEEDED_CATEGORIES),
            "already_seeded": True,
        }

    basic = col.models.by_name("Basic")
    if basic is None:
        raise RuntimeError("default 'Basic' notetype not found in collection")

    # One clean, undoable action: the whole seed is a single batch of note adds
    # (well within the undo history limit), named for a tidy undo entry.
    undo_id = col.add_custom_undo_entry("Seed pgrep sample content")

    requests: list[AddNoteRequest] = []
    for card in _interleaved_by_category(BUNDLE_CARDS):
        note = _new_note(col, basic, card)
        requests.append(AddNoteRequest(note=note, deck_id=deck_id))
    col.add_notes(requests)

    col.merge_undo_entries(undo_id)

    return {
        "deck_id": int(deck_id),
        "cards_created": len(requests),
        "categories": list(SEEDED_CATEGORIES),
        "already_seeded": False,
    }


def _interleaved_by_category(
    cards: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    """Round-robin the cards across categories (blueprint order first).

    Consecutive inserts differ in category until one category remains, so the
    cold new queue is topic-varied from the start, even before any card has
    review state to drive the points-at-stake order.
    """
    by_category: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        by_category.setdefault(category_of(card["topic"]), []).append(card)
    ordered = [c for c in CATEGORY_SLUGS if c in by_category]
    ordered += sorted(c for c in by_category if c not in CATEGORY_SLUGS)

    queues = {c: list(by_category[c]) for c in ordered}
    out: list[dict[str, Any]] = []
    while any(queues[c] for c in ordered):
        for category in ordered:
            if queues[category]:
                out.append(queues[category].pop(0))
    return out


def _new_note(col: Collection, notetype: NotetypeDict, card: dict[str, Any]) -> Note:
    note = col.new_note(notetype)
    note["Front"] = card["front"]
    back = card["back"]
    source_ref = card.get("source_ref")
    # Provenance rides on the answer, mirroring the generation path.
    note["Back"] = f"{back}\n\nSource: {source_ref}" if source_ref else back
    # SEEDED_TAG first (idempotency marker); the topic tag is the only topic::
    # tag, so finest-topic parsing is unambiguous regardless of tag ordering.
    note.tags = [SEEDED_TAG, card["topic"], f"{KIND_TAG_PREFIX}{card['kind']}"]
    return note


def _ensure_points_at_stake_config(col: Collection, deck_id: DeckId) -> None:
    """Point the sample deck at a dedicated points-at-stake config group.

    A dedicated config group means the user's default review order is never
    clobbered. Idempotent: on repeat calls the existing group is reused and the
    review order is left untouched.
    """
    deck = col.decks.get(deck_id)
    assert deck is not None
    conf = col.decks.config_dict_for_deck_id(deck_id)
    if conf.get("name") != DECK_CONFIG_NAME:
        conf = col.decks.add_config(DECK_CONFIG_NAME, clone_from=conf)
        col.decks.set_config_id_for_deck_dict(deck, conf["id"])
    if conf.get("reviewOrder") != POINTS_AT_STAKE:
        conf["reviewOrder"] = POINTS_AT_STAKE
        col.decks.update_config(conf)
