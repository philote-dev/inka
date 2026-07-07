# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The two-door study loop (Cards and Problems) for pgrep (L2.1 Study).

Two doors, never one shuffled queue (``feature-interleaving.md``): topics are
interleaved **within** a door, never card<->problem whiplash.

- **Cards door** reuses the real engine. ``start_session`` selects the seeded
  ``PGRE::Sample`` deck (whose review order is the L1 points-at-stake selector),
  ``next_item`` reads the top of ``col.sched.get_queued_cards`` (answer withheld
  until the learner reveals it), and ``answer_card`` grades through the genuine
  FSRS loop (``build_answer`` + ``col.sched.answer_card``). The schedule state is
  only ever changed by that sanctioned scheduler call.

- **Problems door** enforces the commit gate (``feature-productive-failure.md``).
  ``start_session`` builds a bounded, rotating sitting of the seeded Problems
  (topic-interleaved round-robin, anti-blocking, capped at
  ``PROBLEMS_PER_SESSION`` and ordered so unseen items lead and the bank rotates
  across sessions), ``next_item`` hands one over with the correct answer and
  rationales **omitted**, and ``commit_problem`` (called only after the learner
  has committed) appends exactly one immutable Attempt. On a **hit** it confirms
  the answer the learner themselves picked. On a **miss** it never reveals the
  parent answer; it opens the gated decomposition tutor (``decomposition.py``)
  and re-queues the note so it recurs later in the same session with a different
  numeric variant. Only the first-try commit (round 0) counts as a clean
  attempt; tutor retries carry a non-zero ``ladder_depth`` so Performance
  excludes them (``performance._is_clean``). No confidence capture anywhere.

Session state lives in a module-level dict keyed by ``session_id`` (acceptable
for this single-user desktop MVP). The bridge handlers in ``qt/aqt/pgrep.py``
call the four functions below; their signatures are fixed by the contract
(``docs_pgrep/contracts/L2-api-contract.md`` §3).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any, cast

from anki import scheduler_pb2
from anki.pgrep import attempt_log, decomposition, problem, seed
from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.tags import category_for, category_of, finest_topic

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.scheduler.v3 import Scheduler as V3Scheduler

CardAnswer = scheduler_pb2.CardAnswer

# rating 1..4 -> the scheduler's Again/Hard/Good/Easy.
_RATING_MAP: dict[int, "CardAnswer.Rating.V"] = {
    1: CardAnswer.AGAIN,
    2: CardAnswer.HARD,
    3: CardAnswer.GOOD,
    4: CardAnswer.EASY,
}

# How many queued cards to gather when we need to look past the top of the queue
# (a topic focus drill, or locating a specific card to grade). Bounded so a call
# stays well under 100 ms even on a large collection.
_CARD_BATCH = 64

# A Problems-door session hands over a bounded batch, not the whole bank. The
# Cards door is already capped by the deck's FSRS daily new/review limits, but
# Problems have no such limiter, so without this a session would queue every
# seeded problem at once (137 in the shipped bundle). Twenty is a sensible
# sitting and still spans the blueprint, since the round-robin order front-loads
# about two problems per area before it repeats a category.
PROBLEMS_PER_SESSION = 20

# In-memory session state, keyed by session_id. Single-user desktop MVP.
_SESSIONS: dict[str, dict[str, Any]] = {}


def _sched(col: Collection) -> "V3Scheduler":
    """The active V3 scheduler. pgrep runs on the 2021 scheduler; casting keeps
    the type checker happy without importing v3 at module load (which would risk
    the cards <-> hooks_gen circular import)."""
    return cast("V3Scheduler", col.sched)


# start_session
##########################################################################


def start_session(col: Collection, door: str, topic: str | None = None) -> dict:
    """Begin or scope a study session for one door.

    ``door`` is ``"cards"`` or ``"problems"``; ``topic`` scopes a focus drill
    (cross-topic interleaving off) when given. Returns
    ``{"session_id", "door", "remaining"}``.
    """
    door = (door or "cards").strip().lower()
    session_id = str(uuid.uuid4())

    if door == "problems":
        # Take the first N of the rotation order (unseen lead, then due-back): a
        # bounded sitting that stays spread across areas and works through the
        # bank across sessions rather than repeating the same items. The sitting
        # is a FIFO queue of {note_id, round}; a missed item is appended with the
        # next round so it recurs later in this same session (see commit_problem).
        order = _problem_order(col, topic)[:PROBLEMS_PER_SESSION]
        _SESSIONS[session_id] = {
            "door": "problems",
            "topic": topic,
            "queue": [{"note_id": note_id, "round": 0} for note_id in order],
            "pos": 0,
            # note_id -> the variant last served for it {"round", "key"}, so the
            # commit grades against the numbers the learner actually saw.
            "served": {},
        }
        return {"session_id": session_id, "door": "problems", "remaining": len(order)}

    # Cards door: select the seeded, points-at-stake-ordered sample deck so the
    # engine returns worth-ordered, topic-interleaved cards for free.
    door = "cards"
    deck_id = col.decks.id_for_name(seed.DECK_NAME)
    if deck_id is not None:
        col.decks.set_current(deck_id)
    _SESSIONS[session_id] = {
        "door": "cards",
        "topic": topic,
        "deck_id": int(deck_id) if deck_id is not None else None,
    }
    return {
        "session_id": session_id,
        "door": "cards",
        "remaining": (
            _card_remaining(col, _requested_category(topic))
            if deck_id is not None
            else 0
        ),
    }


# next_item
##########################################################################


def next_item(col: Collection, session_id: str | None = None) -> dict:
    """Return the next item for the session, revealing no help or answer.

    A ``card`` (its answer carried for the reveal step but no grading yet), a
    ``problem`` (correct answer and rationales withheld behind the commit gate),
    or ``{"kind": "empty"}`` when the door is exhausted.
    """
    session = _SESSIONS.get(session_id) if session_id else None
    # Unknown/expired session: fall back to a Cards read (the stateless door).
    if session is None or session.get("door") == "cards":
        return _next_card(col, session)
    return _next_problem(col, session)


def _next_card(col: Collection, session: dict[str, Any] | None) -> dict:
    from anki.decks import DeckId

    deck_id = session.get("deck_id") if session else None
    if deck_id is None:
        # Best effort for an unknown session: scope to the sample deck if present.
        deck_id = col.decks.id_for_name(seed.DECK_NAME)
    if deck_id is not None and col.decks.get_current_id() != deck_id:
        col.decks.set_current(DeckId(deck_id))

    topic = session.get("topic") if session else None
    if topic:
        queued = _sched(col).get_queued_cards(fetch_limit=_CARD_BATCH)
        chosen = _first_card_in_category(col, queued.cards, _requested_category(topic))
    else:
        queued = _sched(col).get_queued_cards(fetch_limit=1)
        chosen = queued.cards[0] if queued.cards else None

    if chosen is None:
        return {"kind": "empty"}

    # Lazy import: importing anki.cards at module load risks a circular import
    # (cards <-> hooks_gen) when this module is imported before anki.collection.
    from anki.cards import Card

    card = Card(col)
    card._load_from_backend_card(chosen.card)
    note = card.note()
    return {
        "kind": "card",
        "card_id": int(card.id),
        "question_html": card.question(),
        "answer_html": card.answer(),
        "topic": finest_topic(note.tags),
        "remaining": _remaining_count(queued),
    }


def _next_problem(col: Collection, session: dict[str, Any]) -> dict:
    from anki.notes import NoteId

    queue: list[dict[str, Any]] = session["queue"]
    pos: int = session["pos"]
    if pos >= len(queue):
        return {"kind": "empty"}
    entry = queue[pos]
    session["pos"] = pos + 1
    note_id = int(entry["note_id"])
    round_index = int(entry.get("round", 0))
    note = col.get_note(NoteId(note_id))

    # A recurring (missed) item shows a renumbered parent stem when the problem
    # has parent variants, so the numbers differ and a result cannot be carried
    # over. Otherwise it reuses the base stem, still honest since the answer was
    # never revealed.
    variant = decomposition.parent_variant(col, note_id, round_index)
    if variant is not None:
        stem_html = variant["stem"]
        choices = variant["choices"]
        served_key = variant["key"]
    else:
        stem_html = note[problem.FIELD_STEM]
        choices = _parse_choices(note[problem.FIELD_CHOICES])
        served_key = (note[problem.FIELD_CORRECT] or "").strip().upper()

    session["served"][note_id] = {"round": round_index, "key": served_key}
    return {
        "kind": "problem",
        "note_id": note_id,
        "stem_html": stem_html,
        "choices": choices,
        "topic": finest_topic(note.tags),
        # includes the item being handed over, mirroring the scheduler counts.
        "remaining": len(queue) - pos,
        "retry": round_index > 0,
    }


# answer_card (Cards door)
##########################################################################


def answer_card(col: Collection, card_id: int, rating: int) -> dict:
    """Grade a Cards-door card through the real FSRS scheduler.

    Re-fetches the queue, confirms ``card_id`` is the card to grade (the top of
    the queue in the common case; a wider fetch backs the focus-drill case),
    then applies ``build_answer`` + ``col.sched.answer_card``. This is a genuine
    review: the revlog gains a row and the card leaves the due queue. Returns
    ``{"ok": true}`` (``{"ok": false}`` if the card is no longer queued).
    """
    card_id = int(card_id)
    rating_enum = _RATING_MAP.get(int(rating))
    if rating_enum is None:
        raise ValueError(f"rating must be 1..4, got {rating!r}")

    top = _sched(col).get_queued_cards(fetch_limit=1)
    chosen = top.cards[0] if top.cards and top.cards[0].card.id == card_id else None
    if chosen is None:
        # Focus drill handed over a non-top card; locate it in a wider fetch.
        batch = _sched(col).get_queued_cards(fetch_limit=_CARD_BATCH)
        chosen = next((qc for qc in batch.cards if qc.card.id == card_id), None)
    if chosen is None:
        return {"ok": False}

    from anki.cards import Card

    card = Card(col)
    card._load_from_backend_card(chosen.card)
    card.start_timer()
    answer = _sched(col).build_answer(
        card=card, states=chosen.states, rating=rating_enum
    )
    _sched(col).answer_card(answer)
    return {"ok": True}


# commit_problem (Problems door)
##########################################################################


def commit_problem(
    col: Collection,
    note_id: int,
    session_id: str,
    selected: str,
    response_ms: float | None = None,
) -> dict:
    """Record a committed Problems answer (before any help) and return feedback.

    Compares ``selected`` to the correct letter of the variant the learner was
    served, and appends exactly one immutable Attempt (no confidence). The
    first-try commit (round 0) is a clean attempt; a tutor retry (a re-served
    miss, round >= 1) carries a matching non-zero ``ladder_depth`` so the
    Performance model excludes it (``performance._is_clean`` counts only
    ``ladder_depth == 0``). Tutor retries never count as clean first-try attempts.

    On a **hit** it returns ``{"correct": true, "correct_choice": ...}`` (the
    answer the learner themselves picked). On a **miss** of a problem that has a
    gated decomposition it never reveals the parent answer; it returns the tutor
    to work (``{"correct": false, "tutor": {...}}``) and re-queues the note so it
    recurs later in this same session with the next numeric variant. On a **miss**
    of a problem with no decomposition (nothing to gate, never re-queued) it
    reveals the worked solution instead of stranding the learner
    (``{"correct": false, "correct_choice": ..., "explanation": {...}}``).

    ``response_ms`` is the client-measured time from the item being shown to the
    commit. It rides into the attempt payload as the M5 data-quality signal so the
    Performance model can drop rapid guesses. An absent or invalid value is left
    off, matching the pre-M5 behavior.
    """
    from anki.notes import NoteId

    note_id = int(note_id)
    note = col.get_note(NoteId(note_id))
    session = _SESSIONS.get(session_id) if session_id else None
    problems_session = bool(session and session.get("door") == "problems")

    # Grade against the variant actually served (a renumbered parent has its own
    # key); fall back to the base note when the session did not serve this item.
    served = session.get("served", {}).get(note_id) if problems_session else None
    round_index = int(served["round"]) if served else 0
    if served and served.get("key"):
        correct_letter = str(served["key"]).strip().upper()
    else:
        correct_letter = (note[problem.FIELD_CORRECT] or "").strip().upper()

    selected_letter = (selected or "").strip().upper()
    is_correct = bool(selected_letter) and selected_letter == correct_letter

    # Commit gate: exactly one immutable Attempt per commit (no confidence).
    event: dict[str, Any] = {
        "item_note_id": note_id,
        "topic": finest_topic(note.tags),
        "category": category_for(note.tags),
        "correct": is_correct,
        "selected_option": selected_letter,
        "session_id": session_id,
        "answered_at": int(time.time()),
        # 0 = clean first-try attempt; >= 1 = tutor retry (excluded from scoring).
        "ladder_depth": round_index,
    }
    if round_index > 0:
        event["tutor_retry"] = True
    # M2: carry the authored item difficulty into the attempt payload so the
    # Performance model can read it live (performance._attempt_difficulty maps a
    # word or a 1..5 number to its scale). Passed through as authored. An empty
    # field is omitted, and Performance falls back to a neutral difficulty.
    difficulty = note[problem.FIELD_DIFFICULTY]
    if difficulty:
        event["difficulty"] = difficulty
    # M5 seam: carry the client-measured response time so Performance can filter
    # rapid guesses. Left off when absent or unparseable (the pre-M5 default).
    ms = _response_ms(response_ms)
    if ms is not None:
        event["response_ms"] = ms
    attempt_log.append_attempt(col, event)

    if is_correct:
        # The answer is confirmed only because the learner picked it themselves.
        return {"correct": True, "correct_choice": correct_letter}

    # Miss. A problem that carries a gated decomposition opens the tutor with the
    # parent answer withheld, and is re-queued to recur later this session with the
    # next numeric variant (numbers differ, no result carries over). A problem with
    # no decomposition has nothing to gate and is never re-queued, so hiding its
    # answer would only strand the learner: reveal the worked solution and move on.
    tutor = decomposition.load_tutor(col, note_id, round_index)
    if tutor["count"] == 0:
        return {
            "correct": False,
            "correct_choice": correct_letter,
            "tutor": tutor,
            "explanation": decomposition.parent_explanation(col, note_id),
        }
    if problems_session:
        session["queue"].append({"note_id": note_id, "round": round_index + 1})
    return {"correct": False, "tutor": tutor}


# Ordering + counts
##########################################################################


def _last_attempts(col: Collection) -> dict[int, tuple[bool, int]]:
    """Map each attempted Problem note to its last ``(correct, answered_at)``.

    Reads the attempt log through the single read-model seam (K4). Events come
    back oldest first, so the last write per ``item_note_id`` wins. A problem that
    was never committed is simply absent, which :func:`_rotation_key` treats as
    the highest priority so unseen items lead the rotation.
    """
    last: dict[int, tuple[bool, int]] = {}
    for event in attempt_log.attempts(col):
        note_id = event.payload.get("item_note_id")
        if note_id is None:
            continue
        last[int(note_id)] = (event.correct, event.answered_at)
    return last


def _rotation_key(
    note_id: int, last: dict[int, tuple[bool, int]]
) -> tuple[int, int, int]:
    """Sort key for one Problem: unseen first, then last-wrong, then last-correct.

    Lower sorts earlier. Tier 0 is never attempted (leads the rotation), tier 1 a
    last-wrong answer (returns before correct ones revisit), tier 2 last-correct.
    Within a tier the oldest ``answered_at`` comes first, so the least-recently
    touched surfaces next and the sitting rotates through the bank. Ties break on
    note id for a stable order.
    """
    info = last.get(note_id)
    if info is None:
        return (0, 0, note_id)
    correct, answered_at = info
    return (2 if correct else 1, answered_at, note_id)


def _problem_order(col: Collection, topic: str | None) -> list[int]:
    """Round-robin the seeded Problems across categories (anti-blocking), in
    rotation order so a session works through the whole bank.

    Categories are visited in blueprint order; within a category, notes are
    ordered by :func:`_rotation_key` (unseen first, then last-wrong, then
    last-correct, least-recently touched first). Round-robin means consecutive
    items differ in category until a single category remains, so no more than a
    couple in a row share a topic. A ``topic`` restricts to that one category
    (focus drill, interleaving off). ``start_session`` takes the first
    ``PROBLEMS_PER_SESSION`` of this order as the sitting, so the rest of the
    bank surfaces as these get answered. All reads go through the attempt-log
    seam; no scheduling state is touched.
    """
    notetype = problem.get_problem_notetype(col)
    if notetype is None:
        return []
    wanted = _requested_category(topic)
    last = _last_attempts(col)

    by_category: dict[str, list[int]] = {}
    for note_id in col.models.nids(notetype["id"]):
        category = category_for(col.get_note(note_id).tags)
        if wanted is not None and category != wanted:
            continue
        by_category.setdefault(category, []).append(int(note_id))
    for ids in by_category.values():
        ids.sort(key=lambda nid: _rotation_key(nid, last))

    ordered_categories = [c for c in CATEGORY_SLUGS if c in by_category]
    ordered_categories += sorted(c for c in by_category if c not in CATEGORY_SLUGS)

    queues = {c: list(by_category[c]) for c in ordered_categories}
    order: list[int] = []
    while any(queues[c] for c in ordered_categories):
        for c in ordered_categories:
            if queues[c]:
                order.append(queues[c].pop(0))
    return order


def _first_card_in_category(col: Collection, cards: Any, category: str | None) -> Any:
    if category is None:
        return cards[0] if cards else None
    from anki.notes import NoteId

    for queued_card in cards:
        note = col.get_note(NoteId(queued_card.card.note_id))
        if category_for(note.tags) == category:
            return queued_card
    return None


def _card_remaining(col: Collection, category: str | None = None) -> int:
    """Count due cards, optionally scoped to one topic category.

    The all-topics case reads the scheduler's own queue counts (exact). A focus
    drill scopes to ``category`` by counting matches in a bounded queue fetch, so
    the drill can show an honest per-topic due count and a correct "nothing due"
    state. The fetch is capped at ``_CARD_BATCH`` (the same bound ``_next_card``
    uses to locate a topic card), so a topic with more than that many due at once
    reads as the cap rather than the full figure. No scheduling state changes.
    """
    if category is None:
        return _remaining_count(_sched(col).get_queued_cards(fetch_limit=1))

    from anki.notes import NoteId

    queued = _sched(col).get_queued_cards(fetch_limit=_CARD_BATCH)
    return sum(
        1
        for queued_card in queued.cards
        if category_for(col.get_note(NoteId(queued_card.card.note_id)).tags) == category
    )


def _remaining_count(queued: Any) -> int:
    return int(queued.new_count) + int(queued.learning_count) + int(queued.review_count)


def _requested_category(topic: str | None) -> str | None:
    if not topic:
        return None
    topic = topic.strip()
    if topic.lower().startswith("topic::"):
        return category_of(topic)
    return topic.lower()


# Parsing helpers (Problem fields hold JSON)
##########################################################################


def _response_ms(value: float | None) -> int | None:
    """Coerce a client-supplied ``response_ms`` to a non-negative int, or ``None``.

    A missing, non-numeric, or negative value returns ``None`` so it is left off
    the attempt payload rather than storing a nonsensical latency.
    """
    if value is None:
        return None
    try:
        ms = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return ms if ms >= 0 else None


def _parse_choices(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []
