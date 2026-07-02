# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the two-door study loop (L2.1 Study).

Cards go through the genuine FSRS scheduler; Problems enforce the commit gate,
append exactly one Attempt per commit, and expose the final answer only in the
reveal rung of the static ladder.
"""

import json

from anki.notes import NoteId
from anki.pgrep import attempt_log, problem, seed, study
from tests.shared import getEmptyCol

# Cards door
##########################################################################


def test_cards_session_starts_on_sample_deck_and_serves_a_card():
    col = getEmptyCol()
    seed.seed_sample_content(col)

    started = study.start_session(col, "cards")
    assert started["door"] == "cards"
    assert isinstance(started["session_id"], str) and started["session_id"]
    assert started["remaining"] > 0
    # the session selected the seeded sample deck.
    assert col.decks.get_current_id() == col.decks.id_for_name(seed.DECK_NAME)

    item = study.next_item(col, started["session_id"])
    assert item["kind"] == "card"
    assert item["card_id"]
    assert item["question_html"]
    assert item["answer_html"]
    assert item["topic"].startswith("topic::")


def test_answer_card_is_a_real_fsrs_review():
    col = getEmptyCol()
    seed.seed_sample_content(col)
    started = study.start_session(col, "cards")
    item = study.next_item(col, started["session_id"])
    card_id = item["card_id"]

    card_before = col.get_card(card_id)
    reps_before = card_before.reps
    last_review_before = card_before.last_review_time
    revlog_before = col.db.scalar("select count() from revlog where cid = ?", card_id)
    total_cards_before = col.card_count()

    result = study.answer_card(col, card_id, 3)  # Good
    assert result == {"ok": True}

    # A genuine scheduler review (not faked): a revlog row was written, reps
    # advanced, and the last-review time moved forward.
    card_after = col.get_card(card_id)
    revlog_after = col.db.scalar("select count() from revlog where cid = ?", card_id)
    assert revlog_after == revlog_before + 1
    assert card_after.reps == reps_before + 1
    assert card_after.last_review_time != last_review_before
    # Not corrupted: no cards were added or dropped by the review.
    assert col.card_count() == total_cards_before


def test_answer_card_rejects_bad_rating():
    col = getEmptyCol()
    seed.seed_sample_content(col)
    started = study.start_session(col, "cards")
    item = study.next_item(col, started["session_id"])
    try:
        study.answer_card(col, item["card_id"], 9)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an out-of-range rating")


def test_cards_focus_drill_scopes_to_topic():
    col = getEmptyCol()
    seed.seed_sample_content(col)

    started = study.start_session(col, "cards", "topic::mechanics")
    item = study.next_item(col, started["session_id"])
    assert item["kind"] == "card"
    assert item["topic"].startswith("topic::mechanics")


# Problems door
##########################################################################


def test_problems_session_withholds_the_answer():
    col = getEmptyCol()
    problem.seed_sample_problems(col)

    started = study.start_session(col, "problems")
    assert started["door"] == "problems"
    assert started["remaining"] >= 6

    item = study.next_item(col, started["session_id"])
    assert item["kind"] == "problem"
    assert item["note_id"]
    assert len(item["choices"]) == 5
    assert item["topic"].startswith("topic::")
    # commit gate: no correct answer or rationales leak before commit.
    assert "correct" not in item
    assert "correct_choice" not in item
    assert "distractor_rationales" not in item
    assert "solution_decomposition" not in item


def test_commit_logs_exactly_one_attempt_and_builds_the_ladder():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = study.start_session(col, "problems")
    item = study.next_item(col, started["session_id"])
    note_id = item["note_id"]

    note = col.get_note(NoteId(note_id))
    correct = note[problem.FIELD_CORRECT].strip().upper()
    wrong = next(letter for letter in "ABCDE" if letter != correct)
    correct_text = json.loads(note[problem.FIELD_CHOICES])[ord(correct) - ord("A")]

    attempts_before = len(attempt_log.attempts(col))
    result = study.commit_problem(col, note_id, started["session_id"], wrong)
    attempts_after = len(attempt_log.attempts(col))

    # Exactly one immutable Attempt appended by the commit.
    assert attempts_after == attempts_before + 1
    fold = attempt_log.performance_fold(col)
    assert fold.total == 1
    assert fold.correct == 0

    assert result["correct"] is False
    assert result["correct_choice"] == correct

    rungs = [rung["rung"] for rung in result["ladder"]]
    assert rungs == ["nudge", "decompose", "sibling", "reveal"]

    # The final answer appears ONLY in the reveal rung (not in the earlier
    # rungs, and not in the pre-reveal rationale).
    reveal = next(r for r in result["ladder"] if r["rung"] == "reveal")
    assert correct_text in reveal["reveal_html"]
    for rung in result["ladder"]:
        if rung["rung"] == "reveal":
            continue
        for key in ("prompt_html", "reveal_html"):
            assert correct_text not in rung.get(key, "")
    assert correct_text not in result["rationale_html"]


def test_commit_correct_answer_reports_correct():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = study.start_session(col, "problems")
    item = study.next_item(col, started["session_id"])
    note = col.get_note(NoteId(item["note_id"]))
    correct = note[problem.FIELD_CORRECT].strip().upper()

    result = study.commit_problem(col, item["note_id"], started["session_id"], correct)
    assert result["correct"] is True
    assert result["correct_choice"] == correct
    fold = attempt_log.performance_fold(col)
    assert fold.correct == 1
    assert fold.total == 1


def test_problems_interleave_by_topic_and_exhaust():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = study.start_session(col, "problems")

    seen_categories: list[str] = []
    seen_notes: list[int] = []
    while True:
        item = study.next_item(col, started["session_id"])
        if item["kind"] == "empty":
            break
        seen_notes.append(item["note_id"])
        seen_categories.append(item["topic"])

    # every seeded problem shown exactly once.
    assert len(seen_notes) == len(set(seen_notes))
    assert len(seen_notes) == started["remaining"]
    # anti-blocking: no three of the same category in a row.
    for i in range(len(seen_categories) - 2):
        trio = seen_categories[i : i + 3]
        assert not (trio[0] == trio[1] == trio[2])


def test_problems_focus_drill_scopes_to_one_category():
    col = getEmptyCol()
    problem.seed_sample_problems(col)

    started = study.start_session(col, "problems", "topic::mechanics")
    assert started["remaining"] >= 1

    item = study.next_item(col, started["session_id"])
    assert item["kind"] == "problem"
    assert item["topic"].startswith("topic::mechanics")


def test_next_item_on_empty_problem_session_is_empty():
    col = getEmptyCol()
    # no problems seeded -> the door is empty from the start.
    started = study.start_session(col, "problems")
    assert started["remaining"] == 0
    assert study.next_item(col, started["session_id"]) == {"kind": "empty"}
