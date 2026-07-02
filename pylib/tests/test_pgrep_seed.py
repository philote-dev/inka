# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep sample-content seed (L2 scaffolding).

Seeding must create topic-tagged, due review cards, point the sample deck at the
points-at-stake review order, and be idempotent (a second call adds no cards).
"""

from anki import deck_config_pb2
from anki.consts import QUEUE_TYPE_REV
from anki.pgrep.seed import DECK_NAME, SEEDED_TAG, seed_sample_content
from tests.shared import getEmptyCol

POINTS_AT_STAKE = (
    deck_config_pb2.DeckConfig.Config.ReviewCardOrder.REVIEW_CARD_ORDER_POINTS_AT_STAKE
)


def test_seed_creates_due_topic_cards_sets_order_and_is_idempotent():
    col = getEmptyCol()

    summary = seed_sample_content(col)

    # It created cards and reported a summary.
    assert summary["already_seeded"] is False
    assert summary["cards_created"] > 0
    assert summary["cards_created"] == col.card_count()
    deck_id = summary["deck_id"]
    assert "mechanics" in summary["categories"]

    # Every seeded card carries the idempotency marker and a topic tag.
    seeded = col.find_notes(f"tag:{SEEDED_TAG}")
    assert len(seeded) == summary["cards_created"]
    assert col.find_cards("tag:topic::mechanics::*")

    # Most cards are due review cards with FSRS memory state.
    review_cards = [
        col.get_card(cid)
        for cid in col.find_cards(f'deck:"{DECK_NAME}"')
        if col.get_card(cid).queue == QUEUE_TYPE_REV
    ]
    assert len(review_cards) >= 10
    assert all(card.memory_state is not None for card in review_cards)
    assert col.find_cards(f'deck:"{DECK_NAME}" is:due')

    # The sample deck uses the points-at-stake review order, on its own config
    # group (the default config is left untouched).
    conf = col.decks.config_dict_for_deck_id(deck_id)
    assert conf["reviewOrder"] == POINTS_AT_STAKE
    default_conf = col.decks.config_dict_for_deck_id(1)
    assert default_conf["reviewOrder"] != POINTS_AT_STAKE

    # A sparse category (lab) has a card left as new (unreviewed) to drive
    # abstain; the review promotion did not touch it.
    lab_cards = [col.get_card(cid) for cid in col.find_cards("tag:topic::lab")]
    assert lab_cards
    assert all(card.memory_state is None for card in lab_cards)

    # Idempotent: a second call adds nothing and does not duplicate cards.
    before = col.card_count()
    summary2 = seed_sample_content(col)
    assert summary2["already_seeded"] is True
    assert summary2["cards_created"] == 0
    assert col.card_count() == before
    assert len(col.find_notes(f"tag:{SEEDED_TAG}")) == len(seeded)
