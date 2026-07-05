# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Timed Exam mode for pgrep (L5.9 P3).

Exam mode is the readiness-measuring instrument (``ux-foundation.md`` 7.2): a
full-length or shorter sectioned timed run of Problems under exam conditions,
zero help, blind review until the end, scored on the raw-to-scaled Readiness map.
It is distinct from untimed practice, where latency is only a data-quality
filter. In the timed exam, latency is the pace signal (``performance-model.md``
M5).

The exam is an assembled problem set plus Attempt notes tagged with a timed
``session_id`` and no help (``technical-architecture.md`` (d)). Each answered
question becomes exactly one clean, committed Attempt (``ladder_depth`` 0, with
``response_ms`` and the timed ``session_id``), appended through the same
``attempt_log.append_attempt`` seam the Problems door uses. So an exam sitting
also feeds Performance and Readiness, which is correct: it is genuine transfer
under exam conditions.

Flow (four bridge handlers in ``qt/aqt/pgrep.py``):

- ``start_exam`` assembles a blueprint-weighted, anti-blocking, no-repeat run of
  the seeded Problems (real PGRE proportions), and starts a timed session.
- ``next_exam_item`` serves one item by index (the navigator) or the next
  unanswered one, with the correct answer and rationales withheld (blind).
- ``answer_exam_item`` records the learner's selection, per-question
  ``response_ms``, and flag into the session. Nothing is graded or revealed yet
  (blind review), and nothing hits the immutable log until finish, so an answer
  can be changed freely and no item is ever double-counted.
- ``finish_exam`` appends one clean Attempt per answered item (idempotent on a
  deterministic ``event_id``), then computes the projected scaled Readiness score
  with an 80% range by reusing ``readiness.py``'s pure functions, plus pace stats
  from ``response_ms``. ``exam_attempts`` is the read model over the attempt log
  for the session.

The scoring reuses ``readiness.correct_to_raw`` / ``raw_to_scaled`` /
``project_scaled_score`` (the formula-scored raw axis, ``correct - incorrect/4``).
Per topic, the exam's observed accuracy becomes a small-sample Jeffreys-Beta
estimate (point plus a standard deviation that never collapses at 0 or 1), so a
short mock projects an honestly wide range rather than a falsely confident one.
Coverage below the Readiness gate abstains from the scaled projection while still
reporting the raw actual result and pace. No AI, no scheduling state is ever
touched (Exam is over the attempt log, not FSRS card grading).

Session state lives in a module-level dict keyed by ``session_id`` (single-user
desktop MVP, matching ``study.py``).
"""

from __future__ import annotations

import json
import math
import time
import uuid
from typing import TYPE_CHECKING, Any

from anki.pgrep import attempt_log, problem
from anki.pgrep.blueprint import BLUEPRINT_PERCENT, CATEGORY_SLUGS
from anki.pgrep.performance import MIN_RESPONSE_MS_DEFAULT
from anki.pgrep.readiness import (
    COVERAGE_GATE,
    GUESS_BASELINE,
    project_scaled_score,
)
from anki.pgrep.readiness_constants import RAW_MAX, RAW_MIN, SCORED_QUESTION_COUNT
from anki.pgrep.tags import category_for, finest_topic

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.pgrep.attempt_log import Event

# The real PGRE is 100 scored questions in 170 minutes. A full-length mock mirrors
# that; a shorter sectioned run trades coverage for time. Both are timed the same
# way (pace per question is constant), so the countdown scales with the run.
FULL_LENGTH_QUESTION_COUNT = SCORED_QUESTION_COUNT
DEFAULT_SECTION_QUESTION_COUNT = 20
_FULL_LENGTH_DURATION_S = 170 * 60
SECONDS_PER_QUESTION = _FULL_LENGTH_DURATION_S / FULL_LENGTH_QUESTION_COUNT

# A topic counts as tested by the exam once it has at least this many answered
# questions. One is enough for the mock to have measured it (unlike Performance's
# k_perf, which governs the untimed model, not a single sitting).
MIN_TOPIC_QUESTIONS = 1

# The short "no hints" line the exam surface shows, and the reason strings. Copy
# rule: no em-dashes, short labels.
NO_HELP_LINE = "No hints. No help. Timed like the exam."
_REASON_NO_ANSWERS = "No answers recorded yet"
_REASON_ABSTAIN = "Not enough of the exam is covered yet"

# Marker carried on every exam attempt payload so a reader can tell an exam
# attempt from an untimed Problems-door commit without inspecting the session id.
EXAM_MODE = "exam"

# In-memory session state, keyed by session_id. Single-user desktop MVP.
_SESSIONS: dict[str, dict[str, Any]] = {}


def _parse_choices(raw: str | None) -> list[str]:
    """Parse the Problem ``choices`` JSON array into a list of strings.

    Mirrors the Problems door parser: a malformed or non-array blob yields an empty
    list rather than raising, so a single bad item never sinks the exam.
    """
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


# Assembly (blueprint-weighted, anti-blocking, no repeats)
##########################################################################


def assemble_exam(col: Collection, question_count: int) -> list[int]:
    """Assemble a timed run of Problem note ids at real PGRE proportions.

    Allocates ``question_count`` across categories by blueprint weight (largest
    remainder, capped by how many distinct Problems each category actually has),
    then round-robins the picks in blueprint order so consecutive items differ in
    topic until only one category has picks left (anti-blocking, like the Problems
    door; the tail of that last category unavoidably runs together). No item
    repeats, and the length is capped by the distinct Problems available, so a thin
    seed simply yields a shorter mock.
    """
    notetype = problem.get_problem_notetype(col)
    if notetype is None or question_count <= 0:
        return []

    by_category: dict[str, list[int]] = {}
    for note_id in col.models.nids(notetype["id"]):
        category = category_for(col.get_note(note_id).tags)
        by_category.setdefault(category, []).append(int(note_id))
    for ids in by_category.values():
        ids.sort()
    if not by_category:
        return []

    ordered_categories = [c for c in CATEGORY_SLUGS if c in by_category]
    ordered_categories += sorted(c for c in by_category if c not in CATEGORY_SLUGS)

    available = {c: len(by_category[c]) for c in ordered_categories}
    allocation = _allocate(question_count, ordered_categories, available)

    queues = {c: list(by_category[c]) for c in ordered_categories}
    remaining = dict(allocation)
    order: list[int] = []
    while sum(remaining.values()) > 0:
        progressed = False
        for category in ordered_categories:
            if remaining[category] > 0 and queues[category]:
                order.append(queues[category].pop(0))
                remaining[category] -= 1
                progressed = True
        if not progressed:
            break
    return order


def _allocate(
    target: int, ordered_categories: list[str], available: dict[str, int]
) -> dict[str, int]:
    """Blueprint-proportional counts per category, capped by availability.

    Largest-remainder apportionment of ``min(target, total available)`` across the
    categories in proportion to their blueprint weight, never exceeding what each
    category can supply. Categories off the blueprint (weight 0) only receive picks
    once the weighted ones are exhausted and the target is not yet met.
    """
    capacity = sum(available.values())
    target = min(target, capacity)
    if target <= 0:
        return {c: 0 for c in ordered_categories}

    total_weight = sum(BLUEPRINT_PERCENT.get(c, 0.0) for c in ordered_categories)
    if total_weight <= 0.0:
        quotas = {c: target / len(ordered_categories) for c in ordered_categories}
    else:
        quotas = {
            c: BLUEPRINT_PERCENT.get(c, 0.0) / total_weight * target
            for c in ordered_categories
        }

    alloc = {c: min(available[c], int(quotas[c])) for c in ordered_categories}
    assigned = sum(alloc.values())

    # Hand out the leftover one at a time, largest fractional remainder first, so
    # the counts stay proportional. Skip a category once it is at capacity.
    by_remainder = sorted(
        ordered_categories, key=lambda c: quotas[c] - int(quotas[c]), reverse=True
    )
    while assigned < target:
        progressed = False
        for category in by_remainder:
            if assigned >= target:
                break
            if alloc[category] < available[category]:
                alloc[category] += 1
                assigned += 1
                progressed = True
        if not progressed:
            break
    return alloc


# start_exam
##########################################################################


def start_exam(
    col: Collection,
    question_count: int | None = None,
    section: bool = False,
) -> dict:
    """Begin a timed exam session and return its shape.

    ``question_count`` sets the run length; when omitted it defaults to a shorter
    sectioned run (``section=True``) or the full-length mock otherwise, both capped
    by the Problems available. Returns ``{session_id, total, duration_s,
    seconds_per_question, no_help_line}``. The countdown is the frontend's to run;
    the backend only records what is submitted, so it never blocks.
    """
    if question_count is None:
        question_count = (
            DEFAULT_SECTION_QUESTION_COUNT if section else FULL_LENGTH_QUESTION_COUNT
        )

    order = assemble_exam(col, int(question_count))
    session_id = str(uuid.uuid4())
    total = len(order)
    duration_s = _round_half_up(SECONDS_PER_QUESTION * total)

    _SESSIONS[session_id] = {
        "order": order,
        "answers": {},  # index -> {"selected", "response_ms", "flagged"}
        # Flips true at finish so a late submit cannot change the scored result.
        "finished": False,
    }
    return {
        "session_id": session_id,
        "total": total,
        "duration_s": duration_s,
        "seconds_per_question": _round_half_up(SECONDS_PER_QUESTION),
        "no_help_line": NO_HELP_LINE,
    }


# next_exam_item (navigator + next-unanswered)
##########################################################################


def next_exam_item(
    col: Collection, session_id: str | None = None, index: int | None = None
) -> dict:
    """Serve one exam item, answer withheld (blind).

    With an ``index`` the navigator fetches that specific question; without one the
    first unanswered question is served (the natural next step). Returns a
    ``{"kind": "item", ...}`` payload carrying the stem, the five choices, the
    topic, the position, and the learner's own prior selection/flag for this
    session, or ``{"kind": "empty"}`` when the session is unknown, the index is out
    of range, or every question has been answered.
    """
    session = _SESSIONS.get(session_id) if session_id else None
    if session is None:
        return {"kind": "empty"}

    order: list[int] = session["order"]
    answers: dict[int, dict[str, Any]] = session["answers"]

    if index is None:
        # The next question with no selection yet (a flag alone does not count as
        # answered, so a flagged-but-blank question is still served here).
        index = next(
            (i for i in range(len(order)) if not answers.get(i, {}).get("selected")),
            None,
        )
        if index is None:
            return {"kind": "empty"}
    if index < 0 or index >= len(order):
        return {"kind": "empty"}

    # ``answered`` reports how many questions carry a selection (not just a flag).
    answered_count = sum(1 for a in answers.values() if a.get("selected"))

    from anki.notes import NoteId

    note_id = order[index]
    note = col.get_note(NoteId(note_id))
    recorded = answers.get(index, {})
    return {
        "kind": "item",
        "index": index,
        "note_id": int(note_id),
        "stem_html": note[problem.FIELD_STEM],
        "choices": _parse_choices(note[problem.FIELD_CHOICES]),
        "topic": finest_topic(note.tags),
        "total": len(order),
        "answered": answered_count,
        "selected": recorded.get("selected", ""),
        "flagged": bool(recorded.get("flagged", False)),
    }


# answer_exam_item (record only; blind until finish)
##########################################################################


def answer_exam_item(
    col: Collection,
    session_id: str,
    index: int,
    selected: str,
    response_ms: float | None = None,
    flagged: bool | None = None,
) -> dict:
    """Record a selection, its ``response_ms``, and the flag for one item.

    Blind by construction: nothing is graded, revealed, or written to the immutable
    attempt log here, so the learner can change an answer or flag any question
    freely. The definitive Attempts are appended once at ``finish_exam``. Returns
    ``{"ok", "answered", "remaining", "flagged"}``. An empty ``selected`` clears the
    answer (the question returns to unanswered) while keeping any flag. Once the
    exam is finished, further answers are rejected (``ok`` false) so a late submit
    cannot change the scored result.
    """
    session = _SESSIONS.get(session_id)
    if session is None:
        return {"ok": False, "answered": 0, "remaining": 0, "flagged": False}

    order: list[int] = session["order"]
    answers: dict[int, dict[str, Any]] = session["answers"]

    if session.get("finished"):
        # The exam is already scored; a late submit must not change the result.
        answered = sum(1 for a in answers.values() if a.get("selected"))
        return {
            "ok": False,
            "answered": answered,
            "remaining": len(order) - answered,
            "flagged": False,
        }

    index = int(index)
    if index < 0 or index >= len(order):
        return {
            "ok": False,
            "answered": len(answers),
            "remaining": len(order) - len(answers),
            "flagged": False,
        }

    selected_letter = (selected or "").strip().upper()
    existing = answers.get(index, {})
    flag = existing.get("flagged", False) if flagged is None else bool(flagged)

    if not selected_letter:
        # Clearing the choice returns the question to unanswered, but a flag set on
        # it survives so the navigator can still mark it for review.
        if flag:
            answers[index] = {"selected": "", "response_ms": None, "flagged": True}
        else:
            answers.pop(index, None)
    else:
        answers[index] = {
            "selected": selected_letter,
            "response_ms": _coerce_ms(response_ms),
            "flagged": flag,
        }

    answered = sum(1 for a in answers.values() if a.get("selected"))
    return {
        "ok": True,
        "answered": answered,
        "remaining": len(order) - answered,
        "flagged": flag,
    }


def _coerce_ms(response_ms: float | None) -> int | None:
    if response_ms is None:
        return None
    try:
        value = int(round(float(response_ms)))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


# finish_exam (append clean Attempts, then score)
##########################################################################


def finish_exam(col: Collection, session_id: str) -> dict:
    """Append one clean Attempt per answered item, then return the exam result.

    Each answered question becomes exactly one committed Attempt (``ladder_depth``
    0, timed ``session_id``, ``response_ms``, authored difficulty). The append is
    idempotent on a deterministic ``event_id`` (``<session_id>:<note_id>``), so
    finishing again (or a repeated result call) never double-writes. The result is
    then computed purely from the attempt log through :func:`exam_result`.
    """
    session = _SESSIONS.get(session_id)
    if session is None:
        # The session is gone (restart), but the log may still hold the attempts,
        # so fall back to the pure read model rather than failing.
        return exam_result(col, session_id)

    from anki.notes import NoteId

    order: list[int] = session["order"]
    answers: dict[int, dict[str, Any]] = session["answers"]

    for index, recorded in answers.items():
        selected_letter = (recorded.get("selected") or "").strip().upper()
        if not selected_letter:
            continue
        note_id = order[index]
        note = col.get_note(NoteId(note_id))
        correct_letter = (note[problem.FIELD_CORRECT] or "").strip().upper()
        is_correct = selected_letter == correct_letter

        event: dict[str, Any] = {
            # Deterministic id: one immutable Attempt per (session, item), so a
            # re-finish is a no-op and an item never double-counts.
            "event_id": f"{session_id}:{int(note_id)}",
            "item_note_id": int(note_id),
            "topic": finest_topic(note.tags),
            "category": category_for(note.tags),
            "correct": is_correct,
            "selected_option": selected_letter,
            "session_id": session_id,
            "answered_at": int(time.time()),
            "ladder_depth": 0,
            "mode": EXAM_MODE,
        }
        response_ms = recorded.get("response_ms")
        if response_ms is not None:
            event["response_ms"] = int(response_ms)
        difficulty = note[problem.FIELD_DIFFICULTY]
        if difficulty:
            event["difficulty"] = difficulty
        attempt_log.append_attempt(col, event)

    session["finished"] = True
    result = exam_result(col, session_id, n_served=len(order))
    # Blind review is unlocked only now, at the end. Attach the per-question review
    # (the learner's answer against the correct one) built from the full served
    # order, so skipped questions appear too.
    result["review"] = _build_review(col, session)
    return result


# Read model over the attempt log for the session
##########################################################################


def exam_attempts(col: Collection, session_id: str) -> list[Event]:
    """Every attempt logged for one exam ``session_id``, oldest first.

    The exam's slice of the single attempt-log read-model seam (K4): it filters
    :func:`attempt_log.attempts` by the session on the payload, so nothing here
    touches attempt storage directly.
    """
    return [
        event
        for event in attempt_log.attempts(col)
        if event.payload.get("session_id") == session_id
    ]


def exam_result(
    col: Collection,
    session_id: str,
    n_served: int | None = None,
    coverage_gate: float = COVERAGE_GATE,
    min_topic_questions: int = MIN_TOPIC_QUESTIONS,
    guess_baseline: float = GUESS_BASELINE,
) -> dict:
    """Score a finished exam from its logged attempts (projected scaled + range).

    Reads the session's attempts (deduped to the final answer per item), then:

    - reports the raw actual result (correct, incorrect, skipped, accuracy, and the
      formula-scored ``raw_actual = correct - incorrect/4`` over the answered
      questions);
    - projects the full PGRE scaled score with an 80% range by reusing
      :func:`readiness.project_scaled_score`. Per topic the exam's observed accuracy
      becomes a Jeffreys-Beta estimate (point plus a standard deviation that stays
      honest at 0 and 1), spread across that topic's blueprint share of the 100
      scored questions; untested topics fall back to the guessing baseline;
    - reports pace stats from ``response_ms`` (M5 in the timed exam).

    Below the coverage gate, or with no answers, the scaled projection abstains
    (naming the untested topics) while the raw actual result and pace still report.
    Everything is arithmetic over the attempt log plus the embedded raw-to-scaled
    constants. No AI, no scheduling state, and no score is ever hardcoded.
    """
    events = exam_attempts(col, session_id)

    # Dedupe to the final answer per item (events arrive oldest first).
    latest_by_item: dict[Any, Event] = {}
    for event in events:
        item = event.payload.get("item_note_id")
        latest_by_item[item] = event
    answered = list(latest_by_item.values())

    n_answered = len(answered)
    correct = sum(1 for event in answered if event.correct)
    incorrect = n_answered - correct
    served = n_served if n_served is not None else n_answered
    skipped = max(0, served - n_answered)
    accuracy = correct / n_answered if n_answered else 0.0

    # Per-category correct/total from the answered exam questions.
    by_category_counts: dict[str, list[int]] = {}
    for event in answered:
        bucket = by_category_counts.setdefault(event.category, [0, 0])
        bucket[0] += 1 if event.correct else 0
        bucket[1] += 1

    contributions, by_topic, tested_topics, untested_topics, coverage_pct = (
        _topic_contributions(by_category_counts, min_topic_questions, guess_baseline)
    )

    result: dict[str, Any] = {
        "session_id": session_id,
        "total": served,
        "n_served": served,
        "n_answered": n_answered,
        "correct": correct,
        "incorrect": incorrect,
        "skipped": skipped,
        "accuracy": accuracy,
        "raw_actual": _raw_actual(correct, incorrect),
        "coverage_pct": coverage_pct,
        "coverage_gate": coverage_gate,
        "tested_topics": tested_topics,
        "untested_topics": untested_topics,
        "by_topic": by_topic,
        "pace": _pace_stats(answered),
        # Always present so the ``review`` type stays honest; the session-gone
        # path never builds one, and ``finish_exam`` overwrites it with the real
        # per-question review.
        "review": [],
    }

    if n_answered == 0:
        result.update(_abstain_fields(_REASON_NO_ANSWERS))
        return result
    if coverage_pct < coverage_gate:
        result.update(_abstain_fields(_REASON_ABSTAIN))
        return result

    projection = project_scaled_score(
        contributions, n_total=float(SCORED_QUESTION_COUNT)
    )
    result.update(
        {
            "scaled": projection["scaled"],
            "low": projection["low"],
            "high": projection["high"],
            "raw": projection["raw"],
            "raw_low": projection["raw_low"],
            "raw_high": projection["raw_high"],
            "expected_correct": projection["expected_correct"],
            "abstain": False,
            "reason": None,
        }
    )
    return result


def _raw_actual(correct: int, incorrect: int) -> int:
    """The exam's own formula-scored raw over the questions it actually sat.

    ``correct - incorrect/4`` (skips carry no penalty), rounded and clamped to the
    table's raw domain. This is the honest raw on the answered questions, reported
    beside the full-length projection rather than mapped to a scaled score (the
    table's scale assumes all 100 questions).
    """
    return _round_half_up(_clamp(correct - incorrect / 4.0, RAW_MIN, RAW_MAX))


def _topic_contributions(
    by_category_counts: dict[str, list[int]],
    min_topic_questions: int,
    guess_baseline: float,
) -> tuple[
    list[tuple[float, float, float]], list[dict[str, Any]], list[str], list[str], float
]:
    """Per-topic projection inputs from the exam's per-category correct/total.

    For each blueprint category, a tested topic's observed accuracy becomes a
    Jeffreys-Beta estimate (point plus a spread that stays honest at 0 and 1),
    spread over that topic's share of the 100 scored questions; an untested topic
    falls back to the guessing baseline. Returns the ``(n, p, p_sd)`` contributions
    for :func:`readiness.project_scaled_score`, the ``by_topic`` breakdown, the
    tested and untested topic slugs, and the blueprint-weighted coverage fraction.
    """
    contributions: list[tuple[float, float, float]] = []
    by_topic: list[dict[str, Any]] = []
    tested_topics: list[str] = []
    untested_topics: list[str] = []
    covered_weight = 0.0
    total_weight = 0.0

    for category in CATEGORY_SLUGS:
        blueprint = BLUEPRINT_PERCENT[category]
        total_weight += blueprint
        n_questions = blueprint * SCORED_QUESTION_COUNT
        c_t, n_t = by_category_counts.get(category, [0, 0])

        tested = n_t >= min_topic_questions
        if tested:
            covered_weight += blueprint
            tested_topics.append(category)
            p_t, p_sd = _beta_posterior(c_t, n_t)
            source = "exam"
        else:
            untested_topics.append(category)
            p_t, p_sd = guess_baseline, 0.0
            source = "guess"

        contributions.append((n_questions, p_t, p_sd))
        by_topic.append(
            {
                "category": category,
                "blueprint": blueprint,
                "n_questions": n_questions,
                "n_exam": n_t,
                "correct": c_t,
                "p": p_t,
                "p_sd": p_sd,
                "tested": tested,
                "source": source,
            }
        )

    coverage_pct = covered_weight / total_weight if total_weight else 0.0
    return contributions, by_topic, tested_topics, untested_topics, coverage_pct


def _build_review(col: Collection, session: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-question blind review over the full served order (answered and skipped).

    Reveals the correct choice beside the learner's own answer, so this is only
    ever built at finish. Skipped questions carry an empty selection and
    ``answered`` false, so the review is honest about what was left blank.
    """
    from anki.notes import NoteId

    order: list[int] = session["order"]
    answers: dict[int, dict[str, Any]] = session["answers"]
    review: list[dict[str, Any]] = []
    for index, note_id in enumerate(order):
        note = col.get_note(NoteId(note_id))
        correct_letter = (note[problem.FIELD_CORRECT] or "").strip().upper()
        recorded = answers.get(index, {})
        selected = (recorded.get("selected") or "").strip().upper()
        review.append(
            {
                "index": index,
                "note_id": int(note_id),
                "topic": finest_topic(note.tags),
                "stem_html": note[problem.FIELD_STEM],
                "choices": _parse_choices(note[problem.FIELD_CHOICES]),
                "selected": selected,
                "correct_choice": correct_letter,
                "correct": bool(selected) and selected == correct_letter,
                "answered": bool(selected),
                "flagged": bool(recorded.get("flagged", False)),
            }
        )
    return review


def _abstain_fields(reason: str) -> dict[str, Any]:
    """The null projection fields for an honest abstain (raw actual still reports)."""
    return {
        "scaled": None,
        "low": None,
        "high": None,
        "raw": None,
        "raw_low": None,
        "raw_high": None,
        "expected_correct": None,
        "abstain": True,
        "reason": reason,
    }


def _beta_posterior(correct: int, total: int) -> tuple[float, float]:
    """Jeffreys-Beta point and standard deviation for a topic's exam accuracy.

    A ``Beta(0.5, 0.5)`` prior updated by ``correct`` of ``total`` gives a posterior
    mean (the point) and standard deviation (the model spread on ``p_t``) that stay
    honest at the extremes. One-for-one on a single question reads as ``0.75`` with
    a wide spread, not a falsely confident ``1.0``, so a short mock projects a wide
    range rather than pretending to certainty.
    """
    a = correct + 0.5
    b = (total - correct) + 0.5
    total_ab = a + b
    mean = a / total_ab
    variance = (a * b) / (total_ab * total_ab * (total_ab + 1.0))
    return mean, math.sqrt(variance)


def _pace_stats(answered: list[Event]) -> dict[str, Any] | None:
    """Pace stats from the answered items' ``response_ms`` (M5 in the timed exam).

    Returns median, mean, fastest, and slowest milliseconds, the count with a
    timing, and how many were faster than the rapid-guess floor. ``None`` when no
    answered item carried a ``response_ms``. Latency here is pace only, so it never
    filters what the exam scores.
    """
    times = [
        int(event.payload["response_ms"])
        for event in answered
        if event.payload.get("response_ms") is not None
    ]
    if not times:
        return None
    times.sort()
    n = len(times)
    mid = n // 2
    median = times[mid] if n % 2 else (times[mid - 1] + times[mid]) / 2.0
    rapid = sum(1 for ms in times if ms < MIN_RESPONSE_MS_DEFAULT)
    return {
        "count": n,
        "median_ms": median,
        "mean_ms": sum(times) / n,
        "fastest_ms": times[0],
        "slowest_ms": times[-1],
        "rapid_guesses": rapid,
        "rapid_guess_floor_ms": int(MIN_RESPONSE_MS_DEFAULT),
    }
