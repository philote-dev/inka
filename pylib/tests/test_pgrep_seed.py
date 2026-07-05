# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep bundled-content seed (L2 scaffolding).

Seeding loads the committed content bundle and creates topic-tagged ``Basic``
cards that land **cold** (ordinary new cards, no fabricated FSRS state), points
the sample deck at the points-at-stake review order on its own config group, and
is idempotent (a second call adds no cards).
"""

from anki import deck_config_pb2
from anki.consts import QUEUE_TYPE_NEW
from anki.pgrep import seed
from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.seed import DECK_NAME, SEEDED_TAG, seed_sample_content
from anki.pgrep.tags import category_for, topic_tags
from tests.shared import getEmptyCol

POINTS_AT_STAKE = (
    deck_config_pb2.DeckConfig.Config.ReviewCardOrder.REVIEW_CARD_ORDER_POINTS_AT_STAKE
)


def test_seed_creates_cold_topic_cards_sets_order_and_is_idempotent():
    col = getEmptyCol()

    summary = seed_sample_content(col)

    # It created the whole bundle and reported a summary.
    assert summary["already_seeded"] is False
    assert summary["cards_created"] == len(seed.BUNDLE_CARDS)
    assert summary["cards_created"] == col.card_count()
    deck_id = summary["deck_id"]
    assert "mechanics" in summary["categories"]

    seeded = col.find_notes(f"tag:{SEEDED_TAG}")
    assert len(seeded) == summary["cards_created"]
    # Finest-topic tagging: the big-3 carry subtopic tags.
    assert col.find_cards("tag:topic::mechanics::*")

    categories = set()
    for note_id in seeded:
        note = col.get_note(note_id)
        # Exactly one topic tag, plus the authored conceptual/computational kind.
        assert len(topic_tags(note.tags)) == 1
        assert any(tag.startswith(seed.KIND_TAG_PREFIX) for tag in note.tags)
        # Real provenance rides on the answer (no "pgrep-sample" placeholder).
        assert "Source:" in note["Back"]
        assert "pgrep-sample" not in note["Back"]
        categories.add(category_for(note.tags))

    # Coverage: all nine blueprint categories are represented.
    assert categories == set(CATEGORY_SLUGS)

    # Cards land COLD: ordinary new cards, no fabricated FSRS memory state. A
    # freshly seeded collection is honest (Memory abstains until studied).
    all_cards = [col.get_card(cid) for cid in col.find_cards(f'deck:"{DECK_NAME}"')]
    assert all_cards
    assert all(card.queue == QUEUE_TYPE_NEW for card in all_cards)
    assert all(card.memory_state is None for card in all_cards)
    assert not col.find_cards(f'deck:"{DECK_NAME}" is:review')

    # The sample deck uses the points-at-stake review order, on its own config
    # group (the default config is left untouched).
    conf = col.decks.config_dict_for_deck_id(deck_id)
    assert conf["reviewOrder"] == POINTS_AT_STAKE
    default_conf = col.decks.config_dict_for_deck_id(1)
    assert default_conf["reviewOrder"] != POINTS_AT_STAKE

    # Idempotent: a second call adds nothing and does not duplicate cards.
    before = col.card_count()
    summary2 = seed_sample_content(col)
    assert summary2["already_seeded"] is True
    assert summary2["cards_created"] == 0
    assert col.card_count() == before
    assert len(col.find_notes(f"tag:{SEEDED_TAG}")) == len(seeded)
