# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Sample content for pgrep (scaffolding-owned).

:func:`seed_sample_content` idempotently ensures a ``PGRE::Sample`` deck of
topic-tagged ``Basic`` cards spread across the PGRE categories, so the L1
selector, Memory, and Coverage all have real data to work with. Most cards are
given real FSRS review state (so they are due and carry a retrievability R),
with stability and last-review offsets varied across cards so per-topic R and
Memory ranges differ. A couple of categories are left deliberately sparse (one
new/unreviewed card, one with none) so the Memory/Coverage abstain state is
demonstrable.

The sample deck is given its own deck-config group whose ``reviewOrder`` is set
to the L1 points-at-stake selector variant, so ``get_queued_cards`` returns
worth-ordered cards for free without touching the user's default review order.

Idempotency: a marker tag (:data:`SEEDED_TAG`) on every seeded note means a
second call creates nothing (no duplicate cards). Note adds and card-state
updates are each done in a single batch, merged into one undoable action. See
``docs_pgrep/plan/l2-api-contract.md`` §2.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from anki import cards_pb2, deck_config_pb2
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV

if TYPE_CHECKING:
    from anki.cards import Card
    from anki.collection import Collection
    from anki.decks import DeckId
    from anki.models import NotetypeDict
    from anki.notes import Note

# The sample deck and its dedicated deck-config group share this name.
DECK_NAME = "PGRE::Sample"
DECK_CONFIG_NAME = "PGRE::Sample"

# Marker tag on every seeded note; drives idempotency (never duplicate cards).
SEEDED_TAG = "pgrep::seeded"

TOPIC_PREFIX = "topic::"

POINTS_AT_STAKE = (
    deck_config_pb2.DeckConfig.Config.ReviewCardOrder.REVIEW_CARD_ORDER_POINTS_AT_STAKE
)

# (category, subtopic-or-None, front, back). These get real FSRS review state so
# they are due with a retrievability R. Subtopics are only used under the big-3
# (mechanics, electromagnetism, quantum), per the L1 topic-tag contract. Counts
# are deliberately uneven: the big-3 carry more cards (non-abstain Memory) while
# smaller categories stay light. Text only, no media.
REVIEWED_CARDS: tuple[tuple[str, str | None, str, str], ...] = (
    # mechanics (6)
    (
        "mechanics",
        "kinematics",
        "Constant-acceleration displacement",
        "x = x0 + v0 t + ½ a t²",
    ),
    (
        "mechanics",
        "kinematics",
        "Projectile range on level ground",
        "R = v0² sin(2θ) / g",
    ),
    ("mechanics", "dynamics", "Newton's second law", "F = m a"),
    ("mechanics", "energy", "Work-energy theorem", "W_net = ΔKE"),
    ("mechanics", "rotation", "Rotational form of Newton's second law", "τ = I α"),
    (
        "mechanics",
        "oscillations",
        "Angular frequency of a mass on a spring",
        "ω = √(k/m)",
    ),
    # electromagnetism (5)
    ("electromagnetism", "electrostatics", "Coulomb's law", "F = k q₁ q₂ / r²"),
    ("electromagnetism", "electrostatics", "Gauss's law", "∮ E·dA = Q_enc / ε₀"),
    ("electromagnetism", "magnetostatics", "Lorentz force", "F = q(E + v×B)"),
    ("electromagnetism", "induction", "Faraday's law of induction", "emf = −dΦ_B/dt"),
    ("electromagnetism", "circuits", "Ohm's law", "V = I R"),
    # quantum (5)
    ("quantum", "wavefunction", "Time-independent Schrödinger equation", "Ĥψ = Eψ"),
    ("quantum", "wavefunction", "de Broglie wavelength", "λ = h / p"),
    (
        "quantum",
        "operators",
        "Heisenberg uncertainty (position, momentum)",
        "Δx·Δp ≥ ħ/2",
    ),
    ("quantum", "spin", "Spin quantum number of an electron", "s = ½"),
    ("quantum", "hydrogen", "Hydrogen energy levels", "E_n = −13.6 eV / n²"),
    # thermodynamics (4)
    ("thermodynamics", None, "Ideal gas law", "PV = nRT"),
    ("thermodynamics", None, "First law of thermodynamics", "ΔU = Q − W"),
    ("thermodynamics", None, "Carnot efficiency", "η = 1 − T_c/T_h"),
    (
        "thermodynamics",
        None,
        "Average kinetic energy per molecule (monatomic)",
        "⟨E⟩ = (3/2) k_B T",
    ),
    # atomic (4)
    ("atomic", None, "Photon energy", "E = h f"),
    ("atomic", None, "Photoelectric effect", "K_max = h f − φ"),
    ("atomic", None, "Rydberg formula", "1/λ = R (1/n₁² − 1/n₂²)"),
    ("atomic", None, "Bohr radius", "a₀ ≈ 0.529 Å"),
    # optics_waves (3)
    ("optics_waves", None, "Thin lens equation", "1/f = 1/dₒ + 1/dᵢ"),
    ("optics_waves", None, "Double-slit maxima", "d sin θ = m λ"),
    ("optics_waves", None, "Wave speed", "v = f λ"),
    # special_relativity (3)
    ("special_relativity", None, "Time dilation", "Δt = γ Δt₀"),
    ("special_relativity", None, "Energy-momentum relation", "E² = (pc)² + (mc²)²"),
    ("special_relativity", None, "Lorentz factor", "γ = 1/√(1 − v²/c²)"),
)

# Deliberately sparse: left as new (unreviewed) cards so their category is
# "covered" by too few reviewed cards to score, driving the abstain state.
# ``specialized`` is intentionally absent entirely (zero cards) so an uncovered
# category is demonstrable too.
NEW_CARDS: tuple[tuple[str, str | None, str, str], ...] = (
    ("lab", None, "Standard error of the mean", "SE = σ / √N"),
)

# The categories this seed touches (for the summary dict).
SEEDED_CATEGORIES: tuple[str, ...] = tuple(
    sorted({card[0] for card in REVIEWED_CARDS} | {card[0] for card in NEW_CARDS})
)

# Stability (days), difficulty, and days-since-last-review are cycled across the
# reviewed cards so per-topic retrievability and Memory ranges differ. Stability
# spans ~5..120 days; longer time-since-review against shorter stability lowers R.
_STABILITY_DAYS: tuple[float, ...] = (
    8.0,
    20.0,
    45.0,
    90.0,
    120.0,
    15.0,
    30.0,
    60.0,
    5.0,
)
_DIFFICULTY: tuple[float, ...] = (3.0, 5.0, 7.0, 4.0, 6.0)
_LAST_REVIEW_DAYS_AGO: tuple[int, ...] = (5, 15, 40, 75, 90, 25, 55)


def seed_sample_content(col: Collection) -> dict[str, Any]:
    """Idempotently seed the ``PGRE::Sample`` deck; return a summary dict.

    The summary has ``deck_id`` (int), ``cards_created`` (int; 0 on repeat
    calls), ``categories`` (the category slugs touched), and ``already_seeded``
    (bool). Safe to call repeatedly: a marker tag prevents duplicate cards.
    """
    from anki.collection import AddNoteRequest

    deck_id = col.decks.id(DECK_NAME)
    assert deck_id is not None
    _ensure_points_at_stake_config(col, deck_id)

    # Idempotency guard: if any seeded note exists, do nothing further.
    if col.find_notes(f"tag:{SEEDED_TAG}"):
        return {
            "deck_id": int(deck_id),
            "cards_created": 0,
            "categories": list(SEEDED_CATEGORIES),
            "already_seeded": True,
        }

    basic = col.models.by_name("Basic")
    if basic is None:
        raise RuntimeError("default 'Basic' notetype not found in collection")

    now = int(time.time())

    # One clean, undoable action. Batch the note adds and the card-state updates
    # so the whole seed is only two undoable ops (well within the undo history
    # limit), then merge them under a single named entry.
    undo_id = col.add_custom_undo_entry("Seed pgrep sample content")

    reviewed_notes: list[Note] = []
    requests: list[AddNoteRequest] = []
    for category, subtopic, front, back in REVIEWED_CARDS:
        note = _new_note(col, basic, category, subtopic, front, back)
        requests.append(AddNoteRequest(note=note, deck_id=deck_id))
        reviewed_notes.append(note)
    for category, subtopic, front, back in NEW_CARDS:
        note = _new_note(col, basic, category, subtopic, front, back)
        requests.append(AddNoteRequest(note=note, deck_id=deck_id))
    col.add_notes(requests)

    cards: list[Card] = []
    for index, note in enumerate(reviewed_notes):
        card = col.get_card(next(iter(col.card_ids_of_note(note.id))))
        _apply_review_state(card, index, now)
        cards.append(card)
    col.update_cards(cards)

    col.merge_undo_entries(undo_id)

    return {
        "deck_id": int(deck_id),
        "cards_created": len(requests),
        "categories": list(SEEDED_CATEGORIES),
        "already_seeded": False,
    }


def _topic_tag(category: str, subtopic: str | None) -> str:
    if subtopic:
        return f"{TOPIC_PREFIX}{category}::{subtopic}"
    return f"{TOPIC_PREFIX}{category}"


def _new_note(
    col: Collection,
    notetype: NotetypeDict,
    category: str,
    subtopic: str | None,
    front: str,
    back: str,
) -> Note:
    note = col.new_note(notetype)
    note["Front"] = front
    note["Back"] = back
    # SEEDED_TAG first (idempotency marker); the topic tag is the only topic::
    # tag, so finest-topic parsing is unambiguous regardless of tag ordering.
    note.tags = [SEEDED_TAG, _topic_tag(category, subtopic)]
    return note


def _apply_review_state(card: Card, index: int, now: int) -> None:
    """Give ``card`` real FSRS review state so it is due with a varied R.

    Mirrors the technique in ``pylib/tests/test_pgrep_selector.py``: promote the
    card to the review type/queue, make it due today, and attach an FSRS memory
    state plus a past last-review time. The caller persists the batch via
    ``col.update_cards``. Never touches the scheduler.
    """
    stability = _STABILITY_DAYS[index % len(_STABILITY_DAYS)]
    difficulty = _DIFFICULTY[index % len(_DIFFICULTY)]
    days_ago = _LAST_REVIEW_DAYS_AGO[index % len(_LAST_REVIEW_DAYS_AGO)]

    card.type = CARD_TYPE_REV
    card.queue = QUEUE_TYPE_REV
    card.due = 0
    card.ivl = max(1, int(stability))
    card.memory_state = cards_pb2.FsrsMemoryState(
        stability=stability, difficulty=difficulty
    )
    card.last_review_time = now - days_ago * 86400


def _ensure_points_at_stake_config(col: Collection, deck_id: DeckId) -> None:
    """Point the sample deck at a dedicated points-at-stake config group.

    A dedicated config group means the user's default review order is never
    clobbered. Idempotent: on repeat calls the existing group is reused and the
    review order is left untouched.
    """
    deck = col.decks.get(deck_id)
    assert deck is not None
    conf = col.decks.config_dict_for_deck_id(deck_id)
    if conf.get("name") != DECK_CONFIG_NAME:
        conf = col.decks.add_config(DECK_CONFIG_NAME, clone_from=conf)
        col.decks.set_config_id_for_deck_dict(deck, conf["id"])
    if conf.get("reviewOrder") != POINTS_AT_STAKE:
        conf["reviewOrder"] = POINTS_AT_STAKE
        col.decks.update_config(conf)
