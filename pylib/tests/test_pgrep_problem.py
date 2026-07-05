# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the ``pgrep::Problem`` notetype and bundled problems (L2.1)."""

import json

from anki.pgrep import problem
from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.tags import category_for
from tests.shared import getEmptyCol


def test_problem_notetype_has_contract_fields_in_order():
    col = getEmptyCol()
    notetype = problem.ensure_problem_notetype(col)

    assert notetype["name"] == problem.PROBLEM_NOTETYPE_NAME
    field_names = [field["name"] for field in notetype["flds"]]
    assert field_names == [
        "stem",
        "choices",
        "correct",
        "distractor_rationales",
        "solution_decomposition",
        "difficulty",
        "source_ref",
    ]
    assert field_names == list(problem.PROBLEM_FIELDS)
    # exactly one card template, and no confidence field anywhere.
    assert len(notetype["tmpls"]) == 1
    assert "confidence" not in field_names


def test_ensure_problem_notetype_is_idempotent():
    col = getEmptyCol()
    first = problem.ensure_problem_notetype(col)
    second = problem.ensure_problem_notetype(col)
    assert first["id"] == second["id"]


def test_seed_sample_problems_seeds_the_bundle_and_is_idempotent():
    col = getEmptyCol()

    created = problem.seed_sample_problems(col)
    # Seeds the whole bundled problem set.
    assert created == len(problem.BUNDLE_PROBLEMS)
    assert created > 100

    # A second call creates nothing (marker-tag guarded).
    assert problem.seed_sample_problems(col) == 0

    note_ids = col.find_notes(f"tag:{problem.PROBLEM_SEED_TAG}")
    assert len(note_ids) == created


def test_seeded_problems_are_parseable_and_cover_all_categories():
    col = getEmptyCol()
    problem.seed_sample_problems(col)

    categories = set()
    for note_id in col.find_notes(f"tag:{problem.PROBLEM_SEED_TAG}"):
        note = col.get_note(note_id)

        choices = json.loads(note[problem.FIELD_CHOICES])
        assert isinstance(choices, list)
        assert len(choices) == 5

        correct = note[problem.FIELD_CORRECT].strip().upper()
        assert correct in problem.CHOICE_LETTERS

        rationales = json.loads(note[problem.FIELD_DISTRACTOR_RATIONALES])
        assert isinstance(rationales, dict)
        # rationales explain distractors, never the correct letter.
        assert correct not in {key.upper() for key in rationales}

        decomposition = json.loads(note[problem.FIELD_SOLUTION_DECOMPOSITION])
        assert isinstance(decomposition, list)
        # ordered sub-goals, ladder-ready.
        assert len(decomposition) >= 2
        for step in decomposition:
            assert set(step) == {"subgoal", "rubric"}
            assert step["subgoal"] and step["rubric"]

        # authored difficulty is stored on the Performance model's 1..5 scale.
        difficulty = float(note[problem.FIELD_DIFFICULTY])
        assert 1.0 <= difficulty <= 5.0

        categories.add(category_for(note.tags))

    # Coverage: all nine blueprint categories are represented.
    assert categories == set(CATEGORY_SLUGS)


def test_seeded_problems_carry_real_source_ref():
    col = getEmptyCol()
    problem.seed_sample_problems(col)

    with_ref = 0
    for note_id in col.find_notes(f"tag:{problem.PROBLEM_SEED_TAG}"):
        note = col.get_note(note_id)
        ref = note[problem.FIELD_SOURCE_REF]
        # The "pgrep-sample" placeholder is retired.
        assert ref != "pgrep-sample"
        if ref:
            with_ref += 1

    # Every bundle item that has provenance carries it onto the note, and the
    # overwhelming majority of problems are cited (a small handful of triage-KEEP
    # items were left uncited by the generator; their physics was re-derived).
    expected = sum(1 for p in problem.BUNDLE_PROBLEMS if p.get("source_ref"))
    assert with_ref == expected
    assert with_ref >= 0.8 * len(problem.BUNDLE_PROBLEMS)


def test_seeded_problem_cards_live_in_problems_deck():
    col = getEmptyCol()
    problem.seed_sample_problems(col)

    deck_id = col.decks.id_for_name(problem.PROBLEM_DECK_NAME)
    assert deck_id is not None

    for note_id in col.find_notes(f"tag:{problem.PROBLEM_SEED_TAG}"):
        for card_id in col.card_ids_of_note(note_id):
            assert col.get_card(card_id).did == deck_id
