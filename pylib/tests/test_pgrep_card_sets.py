# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the Card Sets read model (Library "wheel" browser, L4).

``list_card_sets`` groups the learner's ``Basic`` topic-tagged cards into one set
per blueprint category, in blueprint order, with real counts and a real face
preview. Empty collections yield no sets; authored / generated cards join their
category's set (and land after the seeds, so the preview stays put).
"""

from anki.pgrep import generation
from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.card_sets import CATEGORY_NAMES, add_card, list_card_sets
from anki.pgrep.generation import GENERATED_DECK_NAME
from anki.pgrep.seed import SEEDED_TAG, seed_sample_content
from anki.pgrep.tags import category_for
from tests.shared import getEmptyCol


def test_empty_collection_has_no_card_sets():
    col = getEmptyCol()

    assert list_card_sets(col) == []


def test_seeded_collection_groups_into_blueprint_ordered_sets():
    col = getEmptyCol()
    seed_sample_content(col)

    sets = list_card_sets(col)

    # The seed covers all nine categories, so all nine sets come back in
    # blueprint order (never alphabetical, never raw insertion order), each with
    # its canonical display name.
    assert [s["category"] for s in sets] == list(CATEGORY_SLUGS)
    assert [s["name"] for s in sets] == [CATEGORY_NAMES[c] for c in CATEGORY_SLUGS]

    # Every count is real: a set's size equals the seeded notes whose first topic
    # tag lands in that category, and the totals reconcile with the whole deck.
    expected_counts: dict[str, int] = {}
    for nid in col.find_notes(f"tag:{SEEDED_TAG}"):
        cat = category_for(col.get_note(nid).tags)
        expected_counts[cat] = expected_counts.get(cat, 0) + 1
    for s in sets:
        assert len(s["cards"]) == expected_counts[s["category"]]
        assert len(s["cards"]) > 0
    assert sum(len(s["cards"]) for s in sets) == len(
        col.find_notes(f"tag:{SEEDED_TAG}")
    )


def test_face_preview_is_the_real_first_front_in_note_id_order():
    col = getEmptyCol()
    seed_sample_content(col)

    sets = list_card_sets(col)
    mechanics = next(s for s in sets if s["category"] == "mechanics")

    # Cards keep ascending note-id (insertion) order, so the preview is stable.
    ids = [c["note_id"] for c in mechanics["cards"]]
    assert ids == sorted(ids)

    # The face preview is the real stored front (never invented), and the back is
    # carried through with its seeded provenance line.
    first = mechanics["cards"][0]
    note = col.get_note(first["note_id"])
    assert first["front"] == note["Front"]
    assert first["front"].strip() != ""
    assert "Source:" in first["back"]


def test_authored_card_forms_a_set_without_any_seeding():
    col = getEmptyCol()

    res = generation.author_seed(col, "Lone lab card", "The answer.", "lab")

    sets = list_card_sets(col)
    # A single authored card in the generated deck is a real one-card set: no seed
    # required for the wheel to show it.
    assert len(sets) == 1
    assert sets[0]["category"] == "lab"
    assert sets[0]["name"] == CATEGORY_NAMES["lab"]
    assert [c["note_id"] for c in sets[0]["cards"]] == [res["note_id"]]
    assert sets[0]["cards"][0]["front"] == "Lone lab card"


def test_authored_card_joins_its_category_after_the_seeds():
    col = getEmptyCol()
    seed_sample_content(col)
    before = {s["category"]: len(s["cards"]) for s in list_card_sets(col)}

    res = generation.author_seed(
        col, "My own relativity card", "Because clocks disagree.", "special_relativity"
    )

    sets = list_card_sets(col)
    relativity = next(s for s in sets if s["category"] == "special_relativity")
    # The authored card is counted, lands last (highest note id), and so leaves
    # the face preview (the first seeded front) untouched.
    assert len(relativity["cards"]) == before["special_relativity"] + 1
    assert relativity["cards"][-1]["note_id"] == res["note_id"]
    assert relativity["cards"][-1]["front"] == "My own relativity card"
    assert relativity["cards"][0]["note_id"] != res["note_id"]


def test_add_card_authors_into_the_category_deck_without_ai():
    col = getEmptyCol()

    # A fresh collection has AI off by default, so a successful add here proves
    # the path needs no AI (author-as-is).
    res = add_card(col, "quantum", "  My quantum card  ", "  Because operators.  ")

    assert res["category"] == "quantum"
    note = col.get_note(res["note_id"])
    # Front/back are stored trimmed, exactly as authored (no source line, no
    # rephrase), and the note carries the category's topic tag.
    assert note["Front"] == "My quantum card"
    assert note["Back"] == "Because operators."
    assert category_for(note.tags) == "quantum"

    # It lands in the generated deck (never the seeded sample deck).
    card = col.get_card(next(iter(col.find_cards(f"nid:{res['note_id']}"))))
    assert col.decks.name(card.did) == GENERATED_DECK_NAME

    # And it shows up in the quantum set for the wheel.
    sets = list_card_sets(col)
    quantum = next(s for s in sets if s["category"] == "quantum")
    assert any(c["note_id"] == res["note_id"] for c in quantum["cards"])


def test_card_sets_never_expose_stock_anki_defaults():
    col = getEmptyCol()
    seed_sample_content(col)

    sets = list_card_sets(col)
    names = {s["name"] for s in sets}
    cats = {s["category"] for s in sets}

    # The product's Library only surfaces blueprint categories. The collection
    # still carries Anki's stock Default deck and Basic/Cloze note types (Basic is
    # load-bearing), but no pgrep card set is ever named for them, so a fresh
    # account never reads as "polluted" by Anki defaults.
    assert "Default" not in names and "Default" not in cats
    assert "Cloze" not in names and "Cloze" not in cats
