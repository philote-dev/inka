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
        # Appended after the original contract fields (their ordinals never move).
        "decomposition_tutor",
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


def test_bundle_problems_are_misconception_first():
    # The value and the risk of a problem both sit in its distractors, so every
    # shipped problem must carry four misconception-first distractors: the four
    # non-key letters, each with a misconception tag and a rationale. This is a
    # shipped invariant, checked on the raw bundle (no Collection needed).
    for item in problem.BUNDLE_PROBLEMS:
        key = item["correct"]
        assert key in problem.CHOICE_LETTERS, item["id"]
        distractors = item["distractors"]
        assert len(distractors) == 4, item["id"]
        labels = sorted(d["label"] for d in distractors)
        assert labels == sorted(set(problem.CHOICE_LETTERS) - {key}), item["id"]
        for d in distractors:
            assert d["label"] != key, item["id"]
            assert d.get("misconception", "").strip(), (item["id"], d["label"])
            assert d.get("rationale", "").strip(), (item["id"], d["label"])


def test_tutor_field_normalizes_to_the_stored_shape():
    # A bundle item with no tutor data stores a well-formed empty blob, not junk.
    empty = json.loads(problem.tutor_field({"id": "x"}))
    assert empty == {"subproblems": []}
    # A full record round-trips, keeping subproblems and optional parent_variants.
    record = {
        "decomposition_tutor": {
            "subproblems": [{"prompt": "p", "variants": [{"stem": "s"}]}],
            "parent_variants": [{"stem": "pv", "choices": [1, 2, 3, 4, 5], "key": "A"}],
        }
    }
    stored = json.loads(problem.tutor_field(record))
    assert len(stored["subproblems"]) == 1
    assert len(stored["parent_variants"]) == 1
    # An absent parent_variants list is simply omitted, never stored empty.
    no_parents = json.loads(
        problem.tutor_field({"decomposition_tutor": {"subproblems": []}})
    )
    assert "parent_variants" not in no_parents


def test_seed_stores_decomposition_tutor_field():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    for note_id in col.find_notes(f"tag:{problem.PROBLEM_SEED_TAG}"):
        note = col.get_note(note_id)
        # Every seeded Problem carries a parseable tutor blob with a subproblems
        # list (empty for items no decomposition has been generated for yet).
        blob = json.loads(note[problem.FIELD_DECOMPOSITION_TUTOR])
        assert isinstance(blob, dict)
        assert isinstance(blob["subproblems"], list)


def test_difficulty_field_maps_fraction_to_authored_scale():
    # 0..1 authored fraction -> the 1..5 Performance scale (1 + 4*f).
    assert float(problem.difficulty_field(0.0)) == 1.0
    assert float(problem.difficulty_field(0.5)) == 3.0
    assert float(problem.difficulty_field(1.0)) == 5.0
    # Out-of-range generated values clamp into the scale, never beyond it.
    assert float(problem.difficulty_field(1.5)) == 5.0
    assert float(problem.difficulty_field(-0.2)) == 1.0
    # Missing, non-numeric, or bool falls back to the neutral middle of the scale.
    assert float(problem.difficulty_field(None)) == 3.0
    assert float(problem.difficulty_field("medium")) == 3.0
    assert float(problem.difficulty_field(True)) == 3.0


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
        # Every seeded Problem now carries a real corpus citation. The L5.9 P4b
        # provenance pass re-grounded the last uncited triage-KEEP items against
        # the corpus index (cite-or-refuse) and dropped any it could not ground,
        # so no Problem ships without a named source.
        assert ref, f"note {note_id} shipped with an empty source_ref"
        with_ref += 1

    # Provenance reaches every note, and no bundled Problem is uncited.
    assert with_ref == len(problem.BUNDLE_PROBLEMS)
    assert all(p.get("source_ref") for p in problem.BUNDLE_PROBLEMS)


def test_seeded_problem_cards_live_in_problems_deck():
    col = getEmptyCol()
    problem.seed_sample_problems(col)

    deck_id = col.decks.id_for_name(problem.PROBLEM_DECK_NAME)
    assert deck_id is not None

    for note_id in col.find_notes(f"tag:{problem.PROBLEM_SEED_TAG}"):
        for card_id in col.card_ids_of_note(note_id):
            assert col.get_card(card_id).did == deck_id
