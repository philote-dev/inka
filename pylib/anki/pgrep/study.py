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
  ``start_session`` builds a topic-interleaved (round-robin, anti-blocking)
  ordering of the seeded Problems, ``next_item`` hands one over with the correct
  answer and rationales **omitted**, and ``commit_problem`` (called only after
  the learner has committed) appends exactly one immutable Attempt, then returns
  correctness plus the static wrong-answer ladder built from the stored
  ``solution_decomposition``. The final answer appears **only** in the reveal
  rung. No AI, no confidence capture anywhere.

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
from anki.pgrep import attempt_log, problem, seed
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

# In-memory session state, keyed by session_id. Single-user desktop MVP.
_SESSIONS: dict[str, dict[str, Any]] = {}

# The wrong-answer ladder prompts are static (AI off). No em-dashes, light on
# colons, per the copy rule.
_NUDGE_PROMPT = (
    "Step back before you compute. What kind of problem is this, and which "
    "principle applies? Name it in your own words first."
)
_DECOMPOSE_PROMPT = (
    "Break it into ordered sub-goals. Write each sub-goal and one line on why, "
    "then show the stored steps and compare yours."
)
_SIBLING_PROMPT = (
    "Try the same principle on a nearby case. Change one given, redo the "
    "reasoning, and see whether your method still holds."
)
_REVEAL_PROMPT = (
    "Compare your work with the full solution, then say in one line where the trap was."
)


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
        order = _problem_order(col, topic)
        _SESSIONS[session_id] = {
            "door": "problems",
            "topic": topic,
            "order": order,
            "pos": 0,
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

    order: list[int] = session["order"]
    pos: int = session["pos"]
    if pos >= len(order):
        return {"kind": "empty"}
    note_id = order[pos]
    session["pos"] = pos + 1
    note = col.get_note(NoteId(note_id))
    return {
        "kind": "problem",
        "note_id": int(note_id),
        "stem_html": note[problem.FIELD_STEM],
        "choices": _parse_choices(note[problem.FIELD_CHOICES]),
        "topic": finest_topic(note.tags),
        # includes the item being handed over, mirroring the scheduler counts.
        "remaining": len(order) - pos,
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

    Compares ``selected`` to the stored correct letter, appends exactly one
    immutable Attempt (``ladder_depth`` 0, the commit-before-help event), and
    returns correctness plus the static wrong-answer ladder built from the
    stored ``solution_decomposition``. The final answer appears only in the
    reveal rung.

    ``response_ms`` is the client-measured time from the item being shown to the
    commit. It rides into the attempt payload as the M5 data-quality signal so the
    Performance model can drop rapid guesses (``performance._is_clean``). It is the
    deferred M5 half of the L5.2 seam; an absent or invalid value is simply left
    off, matching the pre-M5 behavior.
    """
    from anki.notes import NoteId

    note_id = int(note_id)
    note = col.get_note(NoteId(note_id))

    correct_letter = (note[problem.FIELD_CORRECT] or "").strip().upper()
    selected_letter = (selected or "").strip().upper()
    is_correct = bool(selected_letter) and selected_letter == correct_letter

    choices = _parse_choices(note[problem.FIELD_CHOICES])
    rationales = _parse_json_map(note[problem.FIELD_DISTRACTOR_RATIONALES])
    decomposition = _parse_decomposition(note[problem.FIELD_SOLUTION_DECOMPOSITION])
    topic = finest_topic(note.tags)
    category = category_for(note.tags)

    # Commit gate: exactly one immutable Attempt per commit (no confidence).
    event: dict[str, Any] = {
        "item_note_id": note_id,
        "topic": topic,
        "category": category,
        "correct": is_correct,
        "selected_option": selected_letter,
        "session_id": session_id,
        "answered_at": int(time.time()),
        "ladder_depth": 0,
    }
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

    return {
        "correct": is_correct,
        "correct_choice": correct_letter,
        "rationale_html": _rationale_html(is_correct, selected_letter, rationales),
        "ladder": _build_ladder(decomposition, correct_letter, choices),
    }


# Ladder + feedback construction (static, AI off)
##########################################################################


def _build_ladder(
    decomposition: list[dict[str, str]],
    correct_letter: str,
    choices: list[str],
) -> list[dict[str, str]]:
    """Build the four-rung ladder from the stored decomposition.

    Nudge orients without naming the answer; decompose reveals the stored
    sub-goals (method only, no final answer); sibling points at a near-transfer
    case; reveal shows the full worked solution, the one place the final answer
    appears.
    """
    steps_html = _decomposition_html(decomposition)
    correct_text = _choice_text(correct_letter, choices)
    return [
        {"rung": "nudge", "prompt_html": _NUDGE_PROMPT},
        {
            "rung": "decompose",
            "prompt_html": _DECOMPOSE_PROMPT,
            "reveal_html": steps_html,
        },
        {"rung": "sibling", "prompt_html": _SIBLING_PROMPT},
        {
            "rung": "reveal",
            "prompt_html": _REVEAL_PROMPT,
            "reveal_html": _reveal_html(steps_html, correct_letter, correct_text),
        },
    ]


def _decomposition_html(decomposition: list[dict[str, str]]) -> str:
    if not decomposition:
        return "<p>No stored steps for this item.</p>"
    items = "".join(
        f"<li><strong>{step['subgoal']}.</strong> {step['rubric']}</li>"
        for step in decomposition
    )
    return f"<ol>{items}</ol>"


def _reveal_html(steps_html: str, correct_letter: str, correct_text: str) -> str:
    if correct_text:
        answer_line = f'<p class="answer">Answer {correct_letter}, {correct_text}.</p>'
    else:
        answer_line = f'<p class="answer">Answer {correct_letter}.</p>'
    return f"{steps_html}\n{answer_line}"


def _rationale_html(
    is_correct: bool, selected_letter: str, rationales: dict[str, str]
) -> str:
    if is_correct:
        return "<p>Correct. Hold onto the reasoning you used.</p>"
    text = rationales.get(selected_letter)
    if text:
        return f"<p>{text}</p>"
    return "<p>Not quite. Work through the steps below.</p>"


def _choice_text(letter: str, choices: list[str]) -> str:
    if not letter:
        return ""
    index = ord(letter.upper()) - ord("A")
    if 0 <= index < len(choices):
        return choices[index]
    return ""


# Ordering + counts
##########################################################################


def _problem_order(col: Collection, topic: str | None) -> list[int]:
    """Round-robin the seeded Problems across categories (anti-blocking).

    Categories are visited in blueprint order; within a category, notes are
    ordered by id. Round-robin means consecutive items differ in category until
    a single category remains, so no more than a couple in a row share a topic.
    A ``topic`` restricts to that one category (focus drill, interleaving off).
    """
    notetype = problem.get_problem_notetype(col)
    if notetype is None:
        return []
    wanted = _requested_category(topic)

    by_category: dict[str, list[int]] = {}
    for note_id in col.models.nids(notetype["id"]):
        category = category_for(col.get_note(note_id).tags)
        if wanted is not None and category != wanted:
            continue
        by_category.setdefault(category, []).append(int(note_id))
    for ids in by_category.values():
        ids.sort()

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


def _parse_json_map(raw: str | None) -> dict[str, str]:
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key).upper(): str(value) for key, value in data.items()}


def _parse_decomposition(raw: str | None) -> list[dict[str, str]]:
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    steps: list[dict[str, str]] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                steps.append(
                    {
                        "subgoal": str(item.get("subgoal", "")),
                        "rubric": str(item.get("rubric", "")),
                    }
                )
    return steps
