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


def test_problems_session_is_capped_to_a_sitting():
    col = getEmptyCol()
    problem.seed_sample_problems(col)  # seeds the full bundle, well over one sitting

    # Sanity: the bank really is larger than a single session, so the cap bites.
    assert len(problem.BUNDLE_PROBLEMS) > study.PROBLEMS_PER_SESSION

    started = study.start_session(col, "problems")
    # The session hands over a bounded batch, not every seeded problem.
    assert started["remaining"] == study.PROBLEMS_PER_SESSION

    # And it exhausts exactly at the cap (no extra items hiding past the count).
    seen = 0
    while study.next_item(col, started["session_id"])["kind"] != "empty":
        seen += 1
    assert seen == study.PROBLEMS_PER_SESSION


def test_problems_rotate_through_the_bank_across_sessions():
    col = getEmptyCol()
    problem.seed_sample_problems(col)

    # Session 1: work the whole sitting and commit every item, so each gains a
    # recent attempt and drops below the still-unseen problems.
    first = study.start_session(col, "problems")
    seen_first: list[int] = []
    while True:
        item = study.next_item(col, first["session_id"])
        if item["kind"] == "empty":
            break
        seen_first.append(item["note_id"])
        note = col.get_note(NoteId(item["note_id"]))
        study.commit_problem(
            col, item["note_id"], first["session_id"], note[problem.FIELD_CORRECT]
        )

    # Session 2: unseen problems lead, so the next sitting is a fresh batch, not
    # the same twenty again.
    second = study.start_session(col, "problems")
    seen_second: list[int] = []
    while True:
        item = study.next_item(col, second["session_id"])
        if item["kind"] == "empty":
            break
        seen_second.append(item["note_id"])

    assert len(seen_second) == study.PROBLEMS_PER_SESSION
    assert set(seen_first).isdisjoint(seen_second)


def test_wrong_problems_return_before_correct_within_a_topic():
    col = getEmptyCol()
    problem.seed_sample_problems(col)

    # A single-category drill makes the round-robin trivial, so the order is just
    # the rotation key: unseen first, then last-wrong, then last-correct.
    drill = study._problem_order(col, "topic::mechanics")
    assert len(drill) >= 3
    correct_one, wrong_one = drill[0], drill[1]

    for note_id, was_correct in ((correct_one, True), (wrong_one, False)):
        attempt_log.append_attempt(
            col,
            {"item_note_id": int(note_id), "correct": was_correct, "answered_at": 1000},
        )

    reordered = study._problem_order(col, "topic::mechanics")
    unseen = [n for n in reordered if n not in (correct_one, wrong_one)]
    # The still-unseen problems lead the rotation.
    assert reordered.index(unseen[0]) < reordered.index(wrong_one)
    # A last-wrong item returns before a last-correct one revisits.
    assert reordered.index(wrong_one) < reordered.index(correct_one)


def test_commit_miss_logs_one_attempt_and_withholds_the_answer():
    from anki.pgrep import decomposition

    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = study.start_session(col, "problems")

    # Use a served problem that carries a gated decomposition: a miss on it opens
    # the tutor with the parent answer withheld. A miss on a problem with no
    # decomposition reveals its worked solution instead (its own test below).
    note_id = None
    while True:
        item = study.next_item(col, started["session_id"])
        if item["kind"] == "empty":
            break
        if decomposition.has_tutor(col, item["note_id"]):
            note_id = item["note_id"]
            break
    assert note_id is not None

    note = col.get_note(NoteId(note_id))
    correct = note[problem.FIELD_CORRECT].strip().upper()
    wrong = next(letter for letter in "ABCDE" if letter != correct)

    attempts_before = len(attempt_log.attempts(col))
    result = study.commit_problem(col, note_id, started["session_id"], wrong)
    attempts_after = len(attempt_log.attempts(col))

    # Exactly one immutable Attempt appended by the commit, a clean first try.
    assert attempts_after == attempts_before + 1
    assert attempt_log.attempts(col)[-1].payload["ladder_depth"] == 0
    fold = attempt_log.performance_fold(col)
    assert fold.total == 1
    assert fold.correct == 0

    # A miss on a problem with a decomposition never reveals the parent answer:
    # no correct choice, no reveal ladder. It opens the decomposition tutor
    # instead, and that payload withholds every answer (no keys, no rationales)
    # until the learner works each subproblem.
    assert result["correct"] is False
    assert set(result.keys()) == {"correct", "tutor"}
    for sub in result["tutor"]["subproblems"]:
        assert "key" not in sub
        assert "correct_choice" not in sub
        assert "distractor_rationales" not in sub


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

    # every problem in the session shown exactly once (the session is a capped
    # batch, not the whole bank).
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


# Committed attempts carry the authored item difficulty (M2 seam)
##########################################################################


def _add_problem(
    col,
    *,
    difficulty: str,
    correct: str = "A",
    topic: str = "topic::mechanics",
) -> int:
    """Add one pgrep::Problem note with a chosen difficulty; return its note id.

    A focused fixture for the commit seam: the shared sample problems all fix
    difficulty to "medium", so we build a single note when a specific authored
    difficulty (or an empty one) is what is under test.
    """
    notetype = problem.ensure_problem_notetype(col)
    note = col.new_note(notetype)
    note[problem.FIELD_STEM] = "A falling-body problem."
    note[problem.FIELD_CHOICES] = json.dumps(["A", "B", "C", "D", "E"])
    note[problem.FIELD_CORRECT] = correct
    note[problem.FIELD_DISTRACTOR_RATIONALES] = json.dumps({})
    note[problem.FIELD_SOLUTION_DECOMPOSITION] = json.dumps([])
    note[problem.FIELD_DIFFICULTY] = difficulty
    note[problem.FIELD_SOURCE_REF] = "test"
    note.tags = [topic]
    col.add_note(note, col.decks.id(problem.PROBLEM_DECK_NAME))
    return int(note.id)


def test_commit_persists_item_difficulty_onto_attempt():
    col = getEmptyCol()
    note_id = _add_problem(col, difficulty="hard", correct="A")

    study.commit_problem(col, note_id, "sess-diff", "A")

    events = attempt_log.attempts(col)
    assert len(events) == 1
    # The authored item difficulty rides into the attempt payload (M2) so the
    # Performance model reads it live (performance._attempt_difficulty maps the
    # word to the 1..5 scale). It is passed through as authored, not normalized
    # in the study path.
    assert events[0].payload["difficulty"] == "hard"


def test_commit_omits_difficulty_when_field_is_empty():
    col = getEmptyCol()
    note_id = _add_problem(col, difficulty="", correct="A")

    study.commit_problem(col, note_id, "sess-diff", "A")

    events = attempt_log.attempts(col)
    assert len(events) == 1
    # An empty authored difficulty is left off the payload. Performance already
    # falls back to a neutral difficulty when the key is absent.
    assert "difficulty" not in events[0].payload


# Same-session re-queue and honest first-try semantics
##########################################################################


def _add_tutor_problem(col, *, correct="C") -> int:
    """A single Problem carrying a tutor blob with a renumbered parent variant."""
    tutor = {
        "subproblems": [
            {
                "prompt": "Step one.",
                "variants": [
                    {
                        "stem": "sub 1",
                        "choices": ["a", "b", "c", "d", "e"],
                        "key": "A",
                        "distractor_rationales": {
                            "B": "x",
                            "C": "x",
                            "D": "x",
                            "E": "x",
                        },
                        "explain_why": "because",
                        "source_ref": "S",
                    }
                ],
            },
            {
                "prompt": "Step two.",
                "variants": [
                    {
                        "stem": "sub 2",
                        "choices": ["a", "b", "c", "d", "e"],
                        "key": "B",
                        "distractor_rationales": {
                            "A": "x",
                            "C": "x",
                            "D": "x",
                            "E": "x",
                        },
                        "explain_why": "because",
                        "source_ref": "S",
                    }
                ],
            },
        ],
        "parent_variants": [
            {
                "stem": "renumbered parent",
                "choices": ["a", "b", "c", "d", "e"],
                "key": "E",
            }
        ],
    }
    notetype = problem.ensure_problem_notetype(col)
    note = col.new_note(notetype)
    note[problem.FIELD_STEM] = "Original parent stem."
    note[problem.FIELD_CHOICES] = json.dumps(["a", "b", "c", "d", "e"])
    note[problem.FIELD_CORRECT] = correct
    note[problem.FIELD_DISTRACTOR_RATIONALES] = json.dumps({})
    note[problem.FIELD_SOLUTION_DECOMPOSITION] = json.dumps([])
    note[problem.FIELD_DIFFICULTY] = "3.0"
    note[problem.FIELD_SOURCE_REF] = "src"
    note[problem.FIELD_DECOMPOSITION_TUTOR] = json.dumps(tutor)
    note.tags = ["topic::mechanics"]
    col.add_note(note, col.decks.id(problem.PROBLEM_DECK_NAME))
    return int(note.id)


def test_miss_requeues_with_next_variant_and_excludes_the_retry():
    from anki.pgrep import performance

    col = getEmptyCol()
    nid = _add_tutor_problem(col, correct="C")

    started = study.start_session(col, "problems")
    assert started["remaining"] == 1

    first = study.next_item(col, started["session_id"])
    assert first["note_id"] == nid
    assert first["retry"] is False
    assert first["stem_html"] == "Original parent stem."

    # Miss the first try: the tutor opens and the note is re-queued for later.
    miss = study.commit_problem(col, nid, started["session_id"], "A")
    assert miss["correct"] is False
    assert "correct_choice" not in miss
    assert miss["tutor"]["count"] == 2

    # It recurs in the SAME session, renumbered so the numbers differ.
    again = study.next_item(col, started["session_id"])
    assert again["note_id"] == nid
    assert again["retry"] is True
    assert again["stem_html"] == "renumbered parent"

    # Answer the renumbered variant with its own key.
    hit = study.commit_problem(col, nid, started["session_id"], "E")
    assert hit["correct"] is True

    # Two attempts: the first-try miss is a clean attempt (ladder_depth 0); the
    # tutor retry is flagged (ladder_depth >= 1, tutor_retry) so it is excluded
    # from clean first-try scoring.
    events = attempt_log.attempts(col)
    assert len(events) == 2
    first_event, retry_event = events[0], events[1]
    assert first_event.payload["ladder_depth"] == 0
    assert first_event.correct is False
    assert retry_event.payload["ladder_depth"] == 1
    assert retry_event.payload.get("tutor_retry") is True
    assert performance._is_clean(first_event, 0) is True
    assert performance._is_clean(retry_event, 0) is False


def test_correct_first_try_does_not_requeue():
    col = getEmptyCol()
    nid = _add_tutor_problem(col, correct="C")
    started = study.start_session(col, "problems")
    study.next_item(col, started["session_id"])

    result = study.commit_problem(col, nid, started["session_id"], "C")
    assert result["correct"] is True
    assert result["correct_choice"] == "C"
    # Nothing more is queued after a clean hit.
    assert study.next_item(col, started["session_id"]) == {"kind": "empty"}


def _add_plain_problem(col, *, correct="C") -> int:
    """A single Problem with a worked solution but no gated decomposition."""
    notetype = problem.ensure_problem_notetype(col)
    note = col.new_note(notetype)
    note[problem.FIELD_STEM] = "A plain problem with no decomposition."
    note[problem.FIELD_CHOICES] = json.dumps(["a", "b", "c", "d", "e"])
    note[problem.FIELD_CORRECT] = correct
    note[problem.FIELD_DISTRACTOR_RATIONALES] = json.dumps({})
    note[problem.FIELD_SOLUTION_DECOMPOSITION] = json.dumps(
        [
            {"subgoal": "Name the principle", "rubric": "Energy is conserved here."},
            {"subgoal": "Solve for the target", "rubric": "Isolate the unknown."},
        ]
    )
    note[problem.FIELD_DIFFICULTY] = "3.0"
    note[problem.FIELD_SOURCE_REF] = "src"
    # An empty tutor blob: nothing to gate on a miss.
    note[problem.FIELD_DECOMPOSITION_TUTOR] = json.dumps({"subproblems": []})
    note.tags = ["topic::mechanics"]
    col.add_note(note, col.decks.id(problem.PROBLEM_DECK_NAME))
    return int(note.id)


def test_miss_without_decomposition_reveals_solution_and_does_not_requeue():
    col = getEmptyCol()
    nid = _add_plain_problem(col, correct="C")
    started = study.start_session(col, "problems")
    assert started["remaining"] == 1

    served = study.next_item(col, started["session_id"])
    assert served["note_id"] == nid

    # Miss a problem with no gated decomposition: there is nothing to gate, so the
    # worked solution is revealed (correct choice + steps) rather than withheld.
    miss = study.commit_problem(col, nid, started["session_id"], "A")
    assert miss["correct"] is False
    assert miss["tutor"]["count"] == 0
    assert miss["correct_choice"] == "C"
    explanation = miss["explanation"]
    assert explanation["correct_choice"] == "C"
    assert [step["subgoal"] for step in explanation["steps"]] == [
        "Name the principle",
        "Solve for the target",
    ]
    assert explanation["steps"][0]["rubric"] == "Energy is conserved here."

    # A no-decomp miss is never re-queued, so the sitting is now empty (it does not
    # come back around like a decomposable miss does).
    assert study.next_item(col, started["session_id"]) == {"kind": "empty"}

    # Still exactly one clean immutable Attempt for the miss (scoring unchanged).
    events = attempt_log.attempts(col)
    assert len(events) == 1
    assert events[0].correct is False
    assert events[0].payload["ladder_depth"] == 0
