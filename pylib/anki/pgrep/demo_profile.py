# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Dev-only demo profile injector for pgrep (L5.9 P5, NOT a shipped surface).

This is a hands-on test and sync-demo tool. It injects a coherent, clearly
marked *hypothetical* study history into a collection so the three scores light
up on demand: Memory (reviewed cards with FSRS state), Performance (clean
Attempt notes per topic), and Readiness (enough blueprint coverage to clear the
70% gate). With the profile injected you can watch the same lit-up account sync
from desktop to the phone through the self-hosted sync server.

Why it is safe for real accounts. Nothing here runs on the shipped user path.
The only trigger is the dev bridge handler ``pgrep_demo_profile`` in
``qt/aqt/pgrep.py``, reachable only from the ``pgrep-lab`` dev surface. Real
accounts never call it, so they still abstain by construction (no attempt log,
too few reviewed cards). The tests prove a fresh collection abstains everywhere.

What it injects, per covered category:

- ``CARDS_PER_CATEGORY`` reviewed cards with real FSRS memory state (so Memory
  scores the category, clearing its ``k_mem`` abstain gate).
- ``ATTEMPTS_PER_CATEGORY`` clean Attempt notes (``ladder_depth`` 0,
  ``response_ms`` well above the rapid-guess floor, distinct item ids, varied
  correctness, ``answered_at`` spread over weeks), so Performance scores the
  category and its blueprint weight counts toward Readiness coverage.

The covered set sums to ``COVERAGE_WEIGHT`` of the blueprint (above the 0.70
Readiness gate), leaving ``lab`` and ``specialized`` uncovered so Readiness still
names an honest hole rather than a fake all-clear.

Marking, idempotency, reversibility. Every reviewed card carries the
:data:`DEMO_TAG` marker, and every Attempt payload carries ``demo: true``.
:func:`inject_demo_profile` is idempotent (it no-ops when the marker is already
present, mirroring ``seed.py``), and :func:`clear_demo_profile` removes exactly
the demo cards and demo attempts, so a real account is never left with injected
data by accident.

Content and technique. All card text is clearly synthetic placeholder content,
so no held-out or gold data can leak in (Memory reads only FSRS retrievability
and the topic tag, never the card text). The FSRS-state technique mirrors the
sanctioned one in ``seed.py`` (``col.update_cards`` with ``memory_state``); the
scheduler is never driven, so no real scheduling state is mutated.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from anki import cards_pb2
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki.pgrep.attempt_log import (
    FIELD_EVENT_JSON,
    append_attempt,
    get_attempt_notetype,
)
from anki.pgrep.blueprint import BLUEPRINT_PERCENT

if TYPE_CHECKING:
    from anki.cards import Card
    from anki.collection import Collection
    from anki.models import NotetypeDict
    from anki.notes import Note, NoteId

# The demo deck, plus the marker tag on every demo reviewed card. The tag drives
# both idempotency (never inject twice) and reversibility (clear finds them).
DEMO_DECK_NAME = "PGRE::Demo"
DEMO_TAG = "pgrep::demo"
TOPIC_PREFIX = "topic::"

# Key stored in the collection config so status can report the active profile.
_ACTIVE_PROFILE_KEY = "pgrep_demo_profile"

# The payload flag that marks a demo Attempt note, so clear can find them without
# mutating the (immutable) notes. Kept inside the payload at creation time.
DEMO_PAYLOAD_KEY = "demo"

# Categories the profile covers: a representative subtopic plus a per-area skill
# in [0, 1] that shapes the profile (a strong learner is not equally strong
# everywhere). Their blueprint weights sum to COVERAGE_WEIGHT, comfortably above
# the 0.70 Readiness gate; lab and specialized are left uncovered so Readiness
# names an honest hole rather than a fake all-clear.
COVERED: tuple[tuple[str, str, float], ...] = (
    ("mechanics", "kinematics", 0.9),
    ("electromagnetism", "circuits", 0.7),
    ("quantum", "wavefunction", 0.4),
    ("thermodynamics", "laws", 0.6),
    ("atomic", "spectra", 0.5),
    ("optics_waves", "interference", 0.3),
    ("special_relativity", "kinematics", 0.8),
)

COVERED_CATEGORIES: tuple[str, ...] = tuple(category for category, _, _ in COVERED)
COVERAGE_WEIGHT: float = sum(
    BLUEPRINT_PERCENT[category] for category in COVERED_CATEGORIES
)

# How far a per-area skill pulls attempt accuracy around the profile base
# (skill 0.0 subtracts half of this, 1.0 adds half), and the range the skill maps
# FSRS stability onto (a stronger area remembers longer). Both keep every covered
# area comfortably past its abstain gate while giving the profile a real shape.
_ACCURACY_SPREAD = 0.4
_STABILITY_SCALE_MIN = 0.6
_STABILITY_SCALE_MAX = 1.4

# Per-area accuracy is capped below a perfect run so every covered area keeps at
# least one miss. With the misses spread into the recency window (see _outcomes),
# that makes even a strong learner feed a non-zero recent-failure term into the
# Performance model rather than a hidden, front-loaded miss. It sits below 0.95 so
# a 10-attempt area rounds to at most 9 correct.
_MAX_ACCURACY = 0.9

# Reviewed cards per category (>= memory.K_MEM_DEFAULT so Memory scores it) and
# clean attempts per category (>= performance.K_PERF_DEFAULT so Performance
# scores it and the weight counts toward Readiness coverage). Chosen with margin.
CARDS_PER_CATEGORY = 6
ATTEMPTS_PER_CATEGORY = 10

# Attempt latencies (ms), all well above the rapid-guess floor (2000ms) so every
# injected attempt counts as clean. Cycled across a category's attempts.
_RESPONSE_MS: tuple[int, ...] = (
    4200,
    8700,
    3100,
    12000,
    5600,
    2600,
    9500,
    3800,
    15000,
    6400,
)

# Authored item difficulty (1..5) cycled across a category's attempts, so the
# Performance model sees a real spread rather than a single value.
_ITEM_DIFFICULTY: tuple[int, ...] = (2, 3, 4, 3, 2, 4, 3, 2, 3, 4)

# The attempt window: answered_at is spread from this many days ago up to now.
_ATTEMPT_WINDOW_DAYS = 45


@dataclass(frozen=True)
class DemoProfile:
    """One hypothetical learner shape. ``accuracy`` sets how many attempts land.

    ``stability_days`` / ``fsrs_difficulty`` / ``last_review_days_ago`` are cycled
    across a category's reviewed cards to give a realistic spread of FSRS
    retrievability (and therefore Memory). A strong learner has long, recent
    stability (high R); a rusty learner has short, older stability (lower R). Both
    still clear every abstain gate; only the numbers differ.
    """

    key: str
    label: str
    accuracy: float
    stability_days: tuple[float, ...]
    fsrs_difficulty: tuple[float, ...]
    last_review_days_ago: tuple[int, ...]


PROFILES: dict[str, DemoProfile] = {
    "strong": DemoProfile(
        key="strong",
        label="Strong learner",
        accuracy=0.8,
        stability_days=(90.0, 140.0, 200.0, 110.0, 160.0, 130.0),
        fsrs_difficulty=(3.0, 4.0, 3.0, 5.0, 4.0, 3.0),
        last_review_days_ago=(2, 5, 8, 3, 6, 4),
    ),
    "rusty": DemoProfile(
        key="rusty",
        label="Rusty learner",
        accuracy=0.5,
        stability_days=(6.0, 12.0, 20.0, 8.0, 15.0, 10.0),
        fsrs_difficulty=(6.0, 7.0, 6.0, 8.0, 7.0, 6.0),
        last_review_days_ago=(18, 30, 40, 22, 34, 26),
    ),
}

DEFAULT_PROFILE = "strong"


def _resolve_profile(profile: str | None) -> DemoProfile:
    """Return a known :class:`DemoProfile`, falling back to the default."""
    return PROFILES.get((profile or DEFAULT_PROFILE), PROFILES[DEFAULT_PROFILE])


def _topic_tag(category: str, subtopic: str | None) -> str:
    if subtopic:
        return f"{TOPIC_PREFIX}{category}::{subtopic}"
    return f"{TOPIC_PREFIX}{category}"


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _category_accuracy(base: float, skill: float) -> float:
    """Attempt accuracy for an area, its skill pulling around the profile base.

    Capped at :data:`_MAX_ACCURACY` so no area is a perfect run and every covered
    area keeps at least one miss for the recency-failure term.
    """
    return _clamp(base + (skill - 0.5) * _ACCURACY_SPREAD, 0.1, _MAX_ACCURACY)


def _stability_scale(skill: float) -> float:
    """Map an area skill to an FSRS stability multiplier (stronger remembers longer)."""
    return _STABILITY_SCALE_MIN + skill * (_STABILITY_SCALE_MAX - _STABILITY_SCALE_MIN)


def is_demo_injected(col: Collection) -> bool:
    """Whether a demo profile is currently present (marker tag on a demo card)."""
    return bool(col.find_notes(f"tag:{DEMO_TAG}"))


def _outcomes(n: int, correct: int) -> list[bool]:
    """``correct`` wins and ``n - correct`` misses, oldest first (deterministic).

    The misses are placed at evenly spaced positions across the run rather than
    bunched at the oldest end, so whenever there is at least one miss, at least
    one lands inside the recent tail that the Performance recency window reads
    (the last ``RECENCY_WINDOW`` attempts). That makes even a strong profile feed
    a non-zero recent-failure term, instead of hiding a single front-loaded miss
    outside the window. The order matches the ``answered_at`` order the attempts
    are given (oldest first).
    """
    outcomes = [True] * n
    misses = n - correct
    if misses <= 0:
        return outcomes
    step = n / misses
    for j in range(misses):
        index = min(n - 1, int((j + 0.5) * step))
        # Guard a rare rounding collision so the miss count stays exact.
        while not outcomes[index]:
            index = (index + 1) % n
        outcomes[index] = False
    return outcomes


def inject_demo_profile(
    col: Collection, profile: str | None = DEFAULT_PROFILE
) -> dict[str, Any]:
    """Inject the hypothetical profile so Memory, Performance and Readiness score.

    Idempotent for the same profile: if that profile is already present this is a
    no-op that reports ``already_injected``. Switching to a different profile
    clears the current one first, so the lab can move between "strong" and "rusty"
    without a manual clear. Returns a summary dict with the profile key, whether it
    was already present, the number of reviewed cards and attempts created, the
    covered categories, and their summed blueprint coverage weight.
    """
    prof = _resolve_profile(profile)

    if is_demo_injected(col):
        active = col.get_config(_ACTIVE_PROFILE_KEY, None)
        if active == prof.key:
            # Same profile already present: keep the idempotent no-op.
            return {
                "profile": prof.key,
                "already_injected": True,
                "cards_created": 0,
                "attempts_created": 0,
                "covered_categories": list(COVERED_CATEGORIES),
                "coverage_weight": COVERAGE_WEIGHT,
            }
        # A different profile is active: clear it first so the lab can switch
        # between profiles (strong to rusty and back) without a manual clear.
        clear_demo_profile(col)

    cards_created = _inject_reviewed_cards(col, prof)
    attempts_created = _inject_attempts(col, prof)
    col.set_config(_ACTIVE_PROFILE_KEY, prof.key)

    return {
        "profile": prof.key,
        "already_injected": False,
        "cards_created": cards_created,
        "attempts_created": attempts_created,
        "covered_categories": list(COVERED_CATEGORIES),
        "coverage_weight": COVERAGE_WEIGHT,
    }


def clear_demo_profile(col: Collection) -> dict[str, Any]:
    """Remove every demo reviewed card and demo Attempt note; report the counts.

    The inverse of :func:`inject_demo_profile`. Only demo-marked data is touched,
    so any genuine user data (or seed sample content) is left untouched.
    """
    card_note_ids = list(col.find_notes(f"tag:{DEMO_TAG}"))
    attempt_note_ids = _demo_attempt_note_ids(col)

    undo_id = col.add_custom_undo_entry("Clear pgrep demo profile")
    if card_note_ids:
        col.remove_notes(card_note_ids)
    if attempt_note_ids:
        col.remove_notes(attempt_note_ids)
    deck_removed = _remove_demo_deck_if_empty(col)
    col.merge_undo_entries(undo_id)
    col.remove_config(_ACTIVE_PROFILE_KEY)

    return {
        "cleared": bool(card_note_ids or attempt_note_ids),
        "cards_removed": len(card_note_ids),
        "attempts_removed": len(attempt_note_ids),
        "deck_removed": deck_removed,
    }


def demo_status(col: Collection) -> dict[str, Any]:
    """Return the current demo state plus a snapshot of the three overall scores.

    The lab surface uses this to show the scores lighting up (or abstaining)
    immediately after an inject or clear, without a second round of calls.
    """
    from anki.pgrep.memory import memory_score
    from anki.pgrep.performance import performance_score
    from anki.pgrep.readiness import readiness_score

    injected = is_demo_injected(col)
    memory = memory_score(col)
    performance = performance_score(col)
    readiness = readiness_score(col)

    return {
        "injected": injected,
        "profile": col.get_config(_ACTIVE_PROFILE_KEY, None) if injected else None,
        "profiles": [{"key": p.key, "label": p.label} for p in PROFILES.values()],
        "demo_cards": len(col.find_notes(f"tag:{DEMO_TAG}")),
        "demo_attempts": len(_demo_attempt_note_ids(col)),
        "covered_categories": list(COVERED_CATEGORIES),
        "coverage_weight": COVERAGE_WEIGHT,
        "coverage_pct": readiness["coverage_pct"],
        "coverage_gate": readiness["coverage_gate"],
        "scores": {
            "memory": _overall_summary(memory["overall"]),
            "performance": _overall_summary(performance["overall"]),
            "readiness": _readiness_summary(readiness),
        },
    }


# --- injection internals -----------------------------------------------------


def _inject_reviewed_cards(col: Collection, prof: DemoProfile) -> int:
    """Create demo reviewed cards with FSRS state so Memory scores each category.

    Mirrors ``seed.py``: add the notes in one batch, then attach FSRS memory
    state and promote them to review cards in a second batch, merged into one
    undoable action. The scheduler is never invoked.
    """
    from anki.collection import AddNoteRequest

    basic = col.models.by_name("Basic")
    if basic is None:
        raise RuntimeError("default 'Basic' notetype not found in collection")

    deck_id = col.decks.id(DEMO_DECK_NAME)
    assert deck_id is not None
    now = int(time.time())

    undo_id = col.add_custom_undo_entry("Inject pgrep demo profile")

    # (note, area skill, per-area card index) so state can vary by area and card.
    prepared: list[tuple[Note, float, int]] = []
    requests: list[AddNoteRequest] = []
    for category, subtopic, skill in COVERED:
        for index in range(CARDS_PER_CATEGORY):
            note = _new_reviewed_note(col, basic, category, subtopic, index)
            requests.append(AddNoteRequest(note=note, deck_id=deck_id))
            prepared.append((note, skill, index))
    col.add_notes(requests)

    cards: list[Card] = []
    for note, skill, index in prepared:
        card = col.get_card(next(iter(col.card_ids_of_note(note.id))))
        _apply_review_state(card, prof, index, skill, now)
        cards.append(card)
    col.update_cards(cards)

    col.merge_undo_entries(undo_id)
    return len(requests)


def _new_reviewed_note(
    col: Collection,
    notetype: NotetypeDict,
    category: str,
    subtopic: str,
    index: int,
) -> Note:
    note = col.new_note(notetype)
    # Clearly synthetic placeholder text. Memory reads only the FSRS state and the
    # topic tag, never this text, so no real (or gold) content is needed here.
    note["Front"] = f"Demo review card, {category} #{index + 1}"
    note["Back"] = "Hypothetical demo content (dev only)."
    note.tags = [DEMO_TAG, _topic_tag(category, subtopic)]
    return note


def _apply_review_state(
    card: Card, prof: DemoProfile, index: int, skill: float, now: int
) -> None:
    """Give ``card`` real FSRS review state (the sanctioned ``seed.py`` technique).

    The profile's cycled stability / difficulty / last-review offsets vary the
    per-card retrievability, and the area ``skill`` scales stability so a stronger
    area reads as higher Memory. The caller persists the batch via
    ``col.update_cards``; the scheduler is untouched.
    """
    stability = prof.stability_days[
        index % len(prof.stability_days)
    ] * _stability_scale(skill)
    difficulty = prof.fsrs_difficulty[index % len(prof.fsrs_difficulty)]
    days_ago = prof.last_review_days_ago[index % len(prof.last_review_days_ago)]

    card.type = CARD_TYPE_REV
    card.queue = QUEUE_TYPE_REV
    card.due = 0
    card.ivl = max(1, int(stability))
    card.memory_state = cards_pb2.FsrsMemoryState(
        stability=stability, difficulty=difficulty
    )
    card.last_review_time = now - days_ago * 86400


def _inject_attempts(col: Collection, prof: DemoProfile) -> int:
    """Append clean Attempt notes per category through the sanctioned write path.

    Each attempt uses ``append_attempt`` with a self-contained payload carrying
    ``ladder_depth`` 0, a real ``response_ms`` above the rapid-guess floor, a
    distinct ``item_note_id`` (so the Performance interval is tight), an
    ``answered_at`` spread over weeks, and the :data:`DEMO_PAYLOAD_KEY` flag so
    the attempt is reversible.
    """
    now = int(time.time())
    created = 0

    for cat_index, (category, subtopic, skill) in enumerate(COVERED):
        topic = _topic_tag(category, subtopic)
        item_base = (cat_index + 1) * 100000
        accuracy = _category_accuracy(prof.accuracy, skill)
        correct_count = int(accuracy * ATTEMPTS_PER_CATEGORY + 0.5)
        outcomes = _outcomes(ATTEMPTS_PER_CATEGORY, correct_count)
        for i, correct in enumerate(outcomes):
            answered_at = _answered_at(now, cat_index, i, ATTEMPTS_PER_CATEGORY)
            append_attempt(
                col,
                {
                    "item_note_id": item_base + i,
                    "topic": topic,
                    "category": category,
                    "correct": bool(correct),
                    "selected_option": 0 if correct else 1,
                    "session_id": f"pgrep-demo-{prof.key}-{category}",
                    "answered_at": answered_at,
                    "ladder_depth": 0,
                    "difficulty": _ITEM_DIFFICULTY[i % len(_ITEM_DIFFICULTY)],
                    "response_ms": _RESPONSE_MS[i % len(_RESPONSE_MS)],
                    DEMO_PAYLOAD_KEY: True,
                },
            )
            created += 1
    return created


def _answered_at(now: int, cat_index: int, i: int, n: int) -> int:
    """An ``answered_at`` spread over the window, oldest first, staggered per topic."""
    frac = i / (n - 1) if n > 1 else 1.0
    days_ago = _ATTEMPT_WINDOW_DAYS * (1.0 - frac)
    # Stagger topics by a few hours so timestamps do not collide across topics.
    return now - int(days_ago * 86400) - cat_index * 3600


def _remove_demo_deck_if_empty(col: Collection) -> bool:
    """Remove the demo deck once it holds no cards, so no empty deck rides to sync."""
    deck_id = col.decks.id_for_name(DEMO_DECK_NAME)
    if deck_id is None:
        return False
    if col.decks.card_count(deck_id, include_subdecks=True):
        return False
    col.decks.remove([deck_id])
    return True


def _demo_attempt_note_ids(col: Collection) -> list[NoteId]:
    """Note ids of every demo Attempt (payload carries the demo flag)."""
    notetype = get_attempt_notetype(col)
    if not notetype:
        return []
    matched: list[NoteId] = []
    for note_id in col.models.nids(notetype["id"]):
        raw = col.get_note(note_id)[FIELD_EVENT_JSON]
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get(DEMO_PAYLOAD_KEY):
            matched.append(note_id)
    return matched


# --- score snapshot helpers (for demo_status only) ---------------------------


def _overall_summary(overall: dict[str, Any]) -> dict[str, Any]:
    """The Memory / Performance overall block, trimmed for display."""
    return {
        "point": overall.get("point"),
        "low": overall.get("low"),
        "high": overall.get("high"),
        "abstain": overall.get("abstain"),
        "reason": overall.get("reason"),
    }


def _readiness_summary(readiness: dict[str, Any]) -> dict[str, Any]:
    """The Readiness scaled score block, trimmed for display."""
    return {
        "scaled": readiness.get("scaled"),
        "low": readiness.get("low"),
        "high": readiness.get("high"),
        "abstain": readiness.get("abstain"),
        "reason": readiness.get("reason"),
    }
