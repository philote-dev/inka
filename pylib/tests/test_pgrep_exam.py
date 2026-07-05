# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for timed Exam mode (L5.9 P3).

Exam mode assembles a blueprint-weighted run of Problems, serves them with the
answer withheld (blind), records each answer as one clean committed Attempt
(``ladder_depth`` 0, timed ``session_id``, ``response_ms``, difficulty), and at
finish projects the scaled Readiness score with an 80% range by reusing the
``readiness.py`` pure functions, plus pace stats from ``response_ms``.

The projection math is fixed by ``three-scores.md`` section 3 and the embedded
raw-to-scaled table; the flow mirrors the Problems door (``test_pgrep_study.py``)
and the attempt-log plumbing (``test_pgrep_performance.py``).
"""

from __future__ import annotations

import inspect
import json

from anki.notes import NoteId
from anki.pgrep import attempt_log, exam, problem, study
from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.readiness import GUESS_BASELINE, project_scaled_score, raw_to_scaled
from anki.pgrep.readiness_constants import SCORED_QUESTION_COUNT
from tests.shared import getEmptyCol

# Fixtures
##########################################################################


def _add_problem(
    col,
    *,
    category: str,
    correct: str = "A",
    difficulty: str = "medium",
    stem: str | None = None,
) -> int:
    """Add one pgrep::Problem note in a category; return its note id."""
    notetype = problem.ensure_problem_notetype(col)
    note = col.new_note(notetype)
    note[problem.FIELD_STEM] = stem or f"A {category} problem."
    note[problem.FIELD_CHOICES] = json.dumps(["A", "B", "C", "D", "E"])
    note[problem.FIELD_CORRECT] = correct
    note[problem.FIELD_DISTRACTOR_RATIONALES] = json.dumps({})
    note[problem.FIELD_SOLUTION_DECOMPOSITION] = json.dumps([])
    note[problem.FIELD_DIFFICULTY] = difficulty
    note[problem.FIELD_SOURCE_REF] = "test"
    note.tags = [f"topic::{category}"]
    col.add_note(note, col.decks.id(problem.PROBLEM_DECK_NAME))
    return int(note.id)


def _correct_letter(col, note_id: int) -> str:
    return col.get_note(NoteId(note_id))[problem.FIELD_CORRECT].strip().upper()


def _wrong_letter(col, note_id: int) -> str:
    correct = _correct_letter(col, note_id)
    return next(letter for letter in "ABCDE" if letter != correct)


def _sit_exam(col, session_id, order, *, correct: bool, response_ms: int = 5000):
    """Answer every served item (all correct or all wrong) and finish the exam."""
    for index, note_id in enumerate(order):
        letter = (
            _correct_letter(col, note_id) if correct else _wrong_letter(col, note_id)
        )
        exam.answer_exam_item(col, session_id, index, letter, response_ms=response_ms)
    return exam.finish_exam(col, session_id)


# The six categories the small-N exam-logic tests exercise (one Problem each),
# reconstructing the pre-bundle placeholder seed. The committed content bundle
# (P4) now seeds the full mock (137 Problems across all nine categories), which
# would swamp these deterministic assertions about assembly, projection range,
# untested-topic fallback, skip counting, and difficulty carry-through, so these
# tests seed this fixed sample explicitly instead of calling seed_sample_problems.
_SAMPLE_CATEGORIES = (
    "mechanics",
    "electromagnetism",
    "quantum",
    "thermodynamics",
    "atomic",
    "optics_waves",
)


def _seed_six_category_sample(col) -> list[int]:
    """Add one Problem per sample category (six total, difficulty "medium")."""
    return [_add_problem(col, category=category) for category in _SAMPLE_CATEGORIES]


# Assembly
##########################################################################


def test_assembly_is_capped_by_available_problems():
    col = getEmptyCol()
    _seed_six_category_sample(col)  # six Problems, one per sample category

    order = exam.assemble_exam(col, exam.FULL_LENGTH_QUESTION_COUNT)

    # A full-length request cannot exceed the distinct Problems that exist.
    assert len(order) == 6
    assert len(order) == len(set(order))  # no repeats


def test_assembly_is_blueprint_weighted_and_anti_blocking():
    col = getEmptyCol()
    # A rich seed: plenty per category so allocation, not availability, decides.
    for _ in range(12):
        for category in ("mechanics", "electromagnetism", "quantum", "thermodynamics"):
            _add_problem(col, category=category)

    order = exam.assemble_exam(col, 20)
    assert len(order) == 20
    assert len(order) == len(set(order))

    categories = [_category(col, nid) for nid in order]
    # Heavier blueprint weight earns more questions (mechanics .20 > quantum .13).
    assert categories.count("mechanics") >= categories.count("quantum")
    # Anti-blocking: never three of the same category in a row.
    for i in range(len(categories) - 2):
        assert not (categories[i] == categories[i + 1] == categories[i + 2])


def _category(col, note_id):
    from anki.pgrep.tags import category_for

    return category_for(col.get_note(NoteId(note_id)).tags)


def test_assembly_empty_without_problems():
    col = getEmptyCol()
    assert exam.assemble_exam(col, 20) == []


# Start + serve (blind)
##########################################################################


def test_start_reports_shape_and_scaled_duration():
    col = getEmptyCol()
    _seed_six_category_sample(col)

    started = exam.start_exam(col)
    assert isinstance(started["session_id"], str) and started["session_id"]
    assert started["total"] == 6
    # The countdown scales with the run at the PGRE's per-question pace.
    assert started["duration_s"] == round(exam.SECONDS_PER_QUESTION * 6)
    assert started["no_help_line"] == exam.NO_HELP_LINE


def test_next_item_withholds_the_answer():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)

    item = exam.next_exam_item(col, started["session_id"], index=0)
    assert item["kind"] == "item"
    assert item["index"] == 0
    assert len(item["choices"]) == 5
    assert item["topic"].startswith("topic::")
    # Blind: no correct answer or rationales leak before the review at the end.
    assert "correct" not in item
    assert "correct_choice" not in item
    assert "distractor_rationales" not in item


def test_next_item_serves_first_unanswered():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]

    first = exam.next_exam_item(col, sid)  # no index -> first unanswered
    exam.answer_exam_item(col, sid, first["index"], "A", response_ms=4000)
    nxt = exam.next_exam_item(col, sid)
    assert nxt["kind"] == "item"
    assert nxt["index"] != first["index"]


def test_answer_does_not_touch_the_log_until_finish():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]

    exam.answer_exam_item(col, sid, 0, "A", response_ms=5000)
    # Blind review: recording an answer writes nothing to the immutable log yet.
    assert exam.exam_attempts(col, sid) == []
    assert len(attempt_log.attempts(col)) == 0


def test_answer_can_be_changed_before_finish():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid, order = started["session_id"], exam._SESSIONS[started["session_id"]]["order"]
    note_id = order[0]
    correct = _correct_letter(col, note_id)
    wrong = _wrong_letter(col, note_id)

    exam.answer_exam_item(col, sid, 0, wrong, response_ms=5000)
    exam.answer_exam_item(col, sid, 0, correct, response_ms=6000)  # change of mind
    exam.finish_exam(col, sid)

    events = exam.exam_attempts(col, sid)
    # Exactly one Attempt for the item, and it is the final (correct) answer.
    assert len(events) == 1
    assert events[0].correct is True
    assert events[0].payload["selected_option"] == correct


# Attempts are clean, committed, timed, and carry response_ms + difficulty
##########################################################################


def test_finish_logs_clean_committed_timed_attempts():
    col = getEmptyCol()
    _seed_six_category_sample(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    _sit_exam(col, sid, order, correct=True, response_ms=5000)

    events = exam.exam_attempts(col, sid)
    assert len(events) == len(order)
    for event in events:
        payload = event.payload
        # Clean + committed: first-try, no ladder help.
        assert payload["ladder_depth"] == 0
        # Timed session tag.
        assert payload["session_id"] == sid
        # response_ms present (the M5 seam, live in the exam).
        assert payload["response_ms"] == 5000
        # Marked as an exam attempt and carries the authored difficulty.
        assert payload["mode"] == exam.EXAM_MODE
        assert payload["difficulty"] == "medium"


def test_finish_is_idempotent():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    _sit_exam(col, sid, order, correct=True)
    first = len(attempt_log.attempts(col))
    exam.finish_exam(col, sid)  # finishing again must not double-write
    assert len(attempt_log.attempts(col)) == first == len(order)


def test_answers_are_rejected_after_finish():
    # Once scored, the session no longer accepts answers, so a late submit cannot
    # change the recorded result or append a new attempt.
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    _sit_exam(col, sid, order, correct=True)
    before = len(attempt_log.attempts(col))

    # An unanswered index (there is none here since all were answered, but the
    # guard fires regardless of index).
    result = exam.answer_exam_item(col, sid, 0, "A", response_ms=5000)
    assert result["ok"] is False
    # No new attempt was written by the rejected late answer.
    assert len(attempt_log.attempts(col)) == before


def test_result_always_carries_a_review_list():
    # The review type is non-optional; the session-gone path (pure read model)
    # still returns an empty review rather than omitting the key.
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]
    _sit_exam(col, sid, order, correct=True)

    # exam_result is the pure read model (no session): review defaults to [].
    read_model = exam.exam_result(col, sid)
    assert read_model["review"] == []


def test_exam_attempts_feed_performance_seam():
    # Exam attempts are clean, committed attempts, so the collection-wide fold
    # sees them (an exam sitting is genuine transfer under exam conditions).
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    _sit_exam(col, sid, order, correct=True)

    fold = attempt_log.performance_fold(col)
    assert fold.total == len(order)
    assert fold.correct == len(order)


# Projection (reuses the readiness pure functions) + range
##########################################################################


def test_result_projects_scaled_with_a_range():
    col = getEmptyCol()
    _seed_six_category_sample(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    result = _sit_exam(col, sid, order, correct=True)

    assert result["abstain"] is False
    # A real scaled point in the PGRE band with a bracketing 80% range.
    assert 200 <= result["low"] <= result["scaled"] <= result["high"] <= 990
    assert result["low"] < result["high"]  # a short mock is honestly uncertain
    # The raw actual result is reported alongside the projection.
    assert result["correct"] == len(order)
    assert result["incorrect"] == 0
    assert result["raw_actual"] == len(order)  # correct - incorrect/4, all correct


def test_result_matches_readiness_pure_functions():
    # The projection is exactly readiness.project_scaled_score over the exam's
    # per-topic Jeffreys-Beta estimates, mapped through the raw-to-scaled table.
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    result = _sit_exam(col, sid, order, correct=True)

    contributions = [(t["n_questions"], t["p"], t["p_sd"]) for t in result["by_topic"]]
    expected = project_scaled_score(contributions, n_total=float(SCORED_QUESTION_COUNT))
    assert result["scaled"] == expected["scaled"] == raw_to_scaled(result["raw"])
    assert result["low"] == expected["low"]
    assert result["high"] == expected["high"]


def test_untested_topics_fall_back_to_the_guess_baseline():
    col = getEmptyCol()
    _seed_six_category_sample(col)  # covers six of the nine categories
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    result = _sit_exam(col, sid, order, correct=True)

    seeded = {
        "mechanics",
        "electromagnetism",
        "quantum",
        "thermodynamics",
        "atomic",
        "optics_waves",
    }
    for entry in result["by_topic"]:
        if entry["category"] in seeded:
            assert entry["tested"] is True
            assert entry["source"] == "exam"
        else:
            assert entry["tested"] is False
            assert entry["source"] == "guess"
            assert entry["p"] == GUESS_BASELINE
    assert set(result["untested_topics"]) == set(CATEGORY_SLUGS) - seeded


def test_higher_score_projects_higher_than_lower_score():
    col_hi = getEmptyCol()
    problem.seed_sample_problems(col_hi)
    hi_started = exam.start_exam(col_hi)
    hi_order = exam._SESSIONS[hi_started["session_id"]]["order"]
    hi = _sit_exam(col_hi, hi_started["session_id"], hi_order, correct=True)

    col_lo = getEmptyCol()
    problem.seed_sample_problems(col_lo)
    lo_started = exam.start_exam(col_lo)
    lo_order = exam._SESSIONS[lo_started["session_id"]]["order"]
    lo = _sit_exam(col_lo, lo_started["session_id"], lo_order, correct=False)

    assert hi["scaled"] > lo["scaled"]


# Abstain + thin cases
##########################################################################


def test_no_answers_abstains():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)

    result = exam.finish_exam(col, started["session_id"])
    assert result["abstain"] is True
    assert result["reason"] == exam._REASON_NO_ANSWERS
    assert result["scaled"] is None
    assert result["n_answered"] == 0


def test_thin_coverage_abstains_but_still_reports_raw():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    # Answer a single question, so only one topic is covered (~20% of blueprint,
    # below the 70% gate). The scaled projection abstains, honestly.
    exam.answer_exam_item(col, sid, 0, _correct_letter(col, order[0]), response_ms=4000)
    result = exam.finish_exam(col, sid)

    assert result["abstain"] is True
    assert result["reason"] == exam._REASON_ABSTAIN
    assert result["scaled"] is None
    # The raw actual result and coverage still report (useful, not fabricated).
    assert result["correct"] == 1
    assert result["raw_actual"] == 1
    assert result["coverage_pct"] < result["coverage_gate"]
    assert len(result["untested_topics"]) >= 1


def test_skipped_questions_are_counted():
    col = getEmptyCol()
    _seed_six_category_sample(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    # Answer four of six; two are skipped.
    for index in range(4):
        exam.answer_exam_item(
            col, sid, index, _correct_letter(col, order[index]), response_ms=5000
        )
    result = exam.finish_exam(col, sid)

    assert result["n_served"] == 6
    assert result["n_answered"] == 4
    assert result["skipped"] == 2


# Pace (M5 in the timed exam)
##########################################################################


def test_pace_stats_report_from_response_ms():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    for index, note_id in enumerate(order):
        exam.answer_exam_item(
            col,
            sid,
            index,
            _correct_letter(col, note_id),
            response_ms=3000 + index * 1000,
        )
    result = exam.finish_exam(col, sid)

    pace = result["pace"]
    assert pace is not None
    assert pace["count"] == len(order)
    assert pace["fastest_ms"] == 3000
    assert pace["slowest_ms"] == 3000 + (len(order) - 1) * 1000
    assert pace["rapid_guesses"] == 0  # none below the rapid-guess floor


def test_pace_flags_rapid_guesses():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]

    # First answer is a rapid guess (below the floor); the rest are deliberate.
    exam.answer_exam_item(col, sid, 0, _correct_letter(col, order[0]), response_ms=500)
    for index in range(1, len(order)):
        exam.answer_exam_item(
            col, sid, index, _correct_letter(col, order[index]), response_ms=5000
        )
    result = exam.finish_exam(col, sid)

    assert result["pace"]["rapid_guesses"] == 1


# The response_ms seam, untimed commit half (M5, owned by P3)
##########################################################################


def test_untimed_commit_logs_response_ms():
    # The deferred M5 half of the L5.2 seam: the untimed Problems-door commit now
    # carries the client-measured response_ms into the attempt payload, so the
    # Performance model can filter rapid guesses.
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = study.start_session(col, "problems")
    item = study.next_item(col, started["session_id"])

    study.commit_problem(
        col, item["note_id"], started["session_id"], "A", response_ms=4200
    )

    events = attempt_log.attempts(col)
    assert len(events) == 1
    assert events[0].payload["response_ms"] == 4200


def test_untimed_commit_omits_absent_or_bad_response_ms():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    started = study.start_session(col, "problems")
    item = study.next_item(col, started["session_id"])

    # Absent response_ms (the pre-M5 default) leaves the key off entirely.
    study.commit_problem(col, item["note_id"], started["session_id"], "A")
    assert "response_ms" not in attempt_log.attempts(col)[0].payload


# Purity + honesty guards
##########################################################################


def test_beta_posterior_stays_honest_at_the_extremes():
    # One-for-one on a single question is 0.75 with a wide spread, never a
    # falsely certain 1.0 (so a short mock projects an honest range).
    mean, sd = exam._beta_posterior(1, 1)
    assert 0.7 < mean < 0.8
    assert sd > 0.2
    # More evidence tightens the spread.
    _, sd_rich = exam._beta_posterior(20, 20)
    assert sd_rich < sd


def test_ai_off_no_ai_imports():
    # The exam path is pure arithmetic over the attempt log and the embedded
    # constants. Guard against any AI / network import (AI-off by construction).
    source = inspect.getsource(exam)
    forbidden = (
        "pgrep.ai",
        "import openai",
        "import anthropic",
        "import httpx",
        "import requests",
        "import torch",
        "urllib",
    )
    for token in forbidden:
        assert token not in source, f"unexpected AI/network import: {token}"


def test_exam_never_touches_scheduling_state():
    col = getEmptyCol()
    problem.seed_sample_problems(col)
    # Snapshot the Problem cards' scheduling state before the exam.
    notetype = problem.get_problem_notetype(col)
    before = {}
    for note_id in col.models.nids(notetype["id"]):
        for card in col.get_note(note_id).cards():
            before[card.id] = (
                card.due,
                card.ivl,
                card.queue,
                card.type,
                card.memory_state,
            )

    started = exam.start_exam(col)
    sid = started["session_id"]
    order = exam._SESSIONS[sid]["order"]
    _sit_exam(col, sid, order, correct=True)

    for note_id in col.models.nids(notetype["id"]):
        for card in col.get_note(note_id).cards():
            after = (
                card.due,
                card.ivl,
                card.queue,
                card.type,
                card.memory_state,
            )
            assert after == before[card.id]
