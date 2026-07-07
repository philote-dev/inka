# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Card Sets read model for the Library "wheel" browser (L4).

Groups the learner's flash cards into one **set per blueprint category**, in
blueprint order, for the Card Sets browser (``design/claude-design/
design_handoff_card_sets``). A "set" is a category (Classical Mechanics, E&M,
...); its cards are the ``Basic`` notes tagged ``topic::<category>[::<sub>]``
across the seeded ``PGRE::Sample`` deck and the authored / AI ``PGRE::Generated``
deck.

Honesty rule (``api-contract.md`` §0): every count and preview is real. A
set's card count is the true number of notes, and the deck-face preview
(``cards[0].front``) is the first card's actual front. Categories with no cards
are omitted, so the wheel never shows an invented set. No AI, and no scheduling
state is read or written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.tags import TOPIC_PREFIX, category_for

if TYPE_CHECKING:
    from anki.collection import Collection

# The decks a card set draws from: the seeded sample deck and the authored /
# AI-generated deck. Both hold ``Basic`` topic-tagged notes.
SET_DECKS: tuple[str, ...] = ("PGRE::Sample", "PGRE::Generated")

# Category slug -> display name. Mirrors the Home manifold labels
# (``anki.pgrep.manifold``) so a category reads the same on every surface. This
# is duplicated rather than imported: the manifold's layout table is presentation
# coupled to the 3D map, not a shared naming source (see ``blueprint.py`` on
# intentional per-boundary duplication).
CATEGORY_NAMES: dict[str, str] = {
    "mechanics": "Classical Mechanics",
    "electromagnetism": "Electromagnetism",
    "quantum": "Quantum Mechanics",
    "thermodynamics": "Thermo & Stat Mech",
    "atomic": "Atomic Physics",
    "optics_waves": "Optics & Waves",
    "special_relativity": "Special Relativity",
    "lab": "Laboratory Methods",
    "specialized": "Specialized Topics",
}


def _display_name(category: str) -> str:
    """Human name for a category slug (Title-Cased fallback for the unexpected)."""
    return CATEGORY_NAMES.get(category, category.replace("_", " ").title())


def list_card_sets(col: Collection) -> list[dict[str, Any]]:
    """Return the learner's card sets, one per blueprint category with cards.

    Each entry is ``{"category", "name", "cards": [{"note_id", "front",
    "back"}, ...]}``. Categories come back in blueprint order
    (:data:`anki.pgrep.blueprint.CATEGORY_SLUGS`); a category with no cards is
    omitted. Cards keep note-id (insertion) order, so the deck-face preview
    (``cards[0].front``) is stable. JSON-serializable; no AI, no scheduler.
    """
    decks = " OR ".join(f'deck:"{deck}"' for deck in SET_DECKS)
    query = f"note:Basic ({decks}) tag:{TOPIC_PREFIX}*"

    by_category: dict[str, list[dict[str, Any]]] = {}
    for nid in sorted(col.find_notes(query)):
        note = col.get_note(nid)
        # Guard the field read: a stray non-Basic match would lack Front/Back.
        if "Front" not in note or "Back" not in note:
            continue
        category = category_for(note.tags)
        by_category.setdefault(category, []).append(
            {"note_id": int(nid), "front": note["Front"], "back": note["Back"]}
        )

    # Blueprint order first; any unrecognized category (should not occur for
    # topic-tagged content) is appended alphabetically so nothing is dropped.
    ordered = [c for c in CATEGORY_SLUGS if c in by_category]
    ordered += sorted(c for c in by_category if c not in CATEGORY_SLUGS)

    return [
        {
            "category": category,
            "name": _display_name(category),
            "cards": by_category[category],
        }
        for category in ordered
    ]


def add_card(col: Collection, category: str, front: str, back: str) -> dict[str, Any]:
    """Author one card into a category's set, as-is (no AI). Returns the new id.

    This is the wheel's "Add a card": the learner's own front/back go straight
    into the ``PGRE::Generated`` deck tagged for ``category``, via
    :func:`anki.pgrep.generation.author_seed` (the generation-effect authoring
    path, which works with AI off and imports no AI modules). Distinct from
    calibration, which is the guided walkthrough. Returns ``{"note_id",
    "category"}``.
    """
    from anki.pgrep import generation

    result = generation.author_seed(col, front.strip(), back.strip(), category)
    return {"note_id": int(result["note_id"]), "category": category}
