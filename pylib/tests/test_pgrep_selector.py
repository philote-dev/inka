# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""End-to-end test for the pgrep "points at stake" review selector (L1.1).

Builds a collection of due review cards tagged with ``topic::…`` across PGRE
categories, sets the deck's review order to ``POINTS_AT_STAKE`` via deck config,
then drives the v3 scheduler's ``get_queued_cards`` and asserts the returned
order reflects worth (blueprint% x FSRS-native topic weakness). An untagged card
(category ``unknown``, blueprint 0) must sort last but is never dropped.
"""

import time

from anki import cards_pb2, deck_config_pb2
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from tests.shared import getEmptyCol

POINTS_AT_STAKE = (
    deck_config_pb2.DeckConfig.Config.ReviewCardOrder.REVIEW_CARD_ORDER_POINTS_AT_STAKE
)


def test_points_at_stake_orders_by_worth():
    col = getEmptyCol()

    # Distinct blueprint weights make the expected order unambiguous. Every card
    # shares the same FSRS memory state and last-review time, so each single-card
    # topic has an identical weakness and band factor; worth (and therefore the
    # queue order) is driven purely by the category's blueprint%. The final
    # entry is untagged and must sort last while still being gathered.
    setup = [
        ("mechanics", "topic::mechanics::kinematics"),
        ("electromagnetism", "topic::electromagnetism::gauss"),
        ("quantum", "topic::quantum::spin"),
        ("specialized", "topic::specialized::misc"),
        ("optics_waves", "topic::optics_waves::lenses"),
        ("special_relativity", "topic::special_relativity::lorentz"),
        ("unknown", None),
    ]

    last_review = int(time.time()) - 30 * 86400
    id_to_category: dict[int, str] = {}

    # Insert in reverse of the expected order so a pass can only come from real
    # scoring, never from insertion/gather order.
    for category, topic in reversed(setup):
        note = col.newNote()
        note["Front"] = category
        if topic:
            note.tags = [topic]
        col.addNote(note)

        card = note.cards()[0]
        card.type = CARD_TYPE_REV
        card.queue = QUEUE_TYPE_REV
        card.due = 0
        card.ivl = 40
        card.memory_state = cards_pb2.FsrsMemoryState(stability=50.0, difficulty=5.0)
        card.last_review_time = last_review
        col.update_card(card)
        id_to_category[card.id] = category

    # Point the default deck's review order at points-at-stake via deck config.
    conf = col.decks.config_dict_for_deck_id(1)
    conf["reviewOrder"] = POINTS_AT_STAKE
    col.decks.save(conf)

    queued = col.sched.get_queued_cards(fetch_limit=100).cards
    order = [id_to_category[queued_card.card.id] for queued_card in queued]

    assert order == [
        "mechanics",
        "electromagnetism",
        "quantum",
        "specialized",
        "optics_waves",
        "special_relativity",
        "unknown",
    ]
