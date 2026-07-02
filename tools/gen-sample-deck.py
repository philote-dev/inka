#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Generate a small, text-only sample Physics-GRE deck as a collection.anki2.

This produces a reproducible, self-contained Anki collection that the pgrep
iOS app can bundle and open via the shared Rust engine to run a review.

Regenerate (from the repo root, after a desktop build has populated out/):

    PYTHONPATH="$(pwd)/out/pylib" out/pyenv/bin/python tools/gen-sample-deck.py

The output path defaults to mobile/sample-deck/collection.anki2 and can be
overridden with the first argument. Any existing file at the destination is
removed first so the result is deterministic. The committed .anki2 is a small
closed SQLite database; regenerating it and committing the result is expected
whenever the sample cards change.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from anki.collection import Collection

# Path is relative to the repo root so the default works from any CWD.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "mobile" / "sample-deck" / "collection.anki2"

DECK_NAME = "PGRE::Sample"

# Real, simple Physics-GRE-style front/back pairs (text only).
CARDS: list[tuple[str, str]] = [
    ("SI unit of force", "newton (N) = kg·m/s²"),
    ("Time-independent Schrödinger equation", "Ĥψ = Eψ"),
    ("Work-energy theorem", "W_net = ΔKE"),
    ("Lorentz force", "F = q(E + v×B)"),
    ("Ideal gas law", "PV = nRT"),
    ("Heisenberg uncertainty (position-momentum)", "Δx·Δp ≥ ħ/2"),
    ("Relativistic energy-momentum relation", "E² = (pc)² + (mc²)²"),
    ("Coulomb's law", "F = k q₁q₂ / r²"),
]


def generate(output_path: Path) -> int:
    """Create a fresh collection at output_path and return the card count."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Collection() creates a new DB when the file is absent; remove any existing
    # file first so the generated deck is deterministic.
    if output_path.exists():
        output_path.unlink()

    col = Collection(str(output_path))
    try:
        basic = col.models.by_name("Basic")
        if basic is None:
            raise RuntimeError("default 'Basic' notetype not found in new collection")
        deck_id = col.decks.id(DECK_NAME)
        assert deck_id is not None

        for front, back in CARDS:
            note = col.new_note(basic)
            note["Front"] = front
            note["Back"] = back
            col.add_note(note, deck_id)

        card_count = col.card_count()
    finally:
        col.close()
    return card_count


def main() -> None:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    card_count = generate(output_path)
    print(f"Wrote {os.path.relpath(output_path)}")
    print(f"Added {card_count} cards to deck {DECK_NAME!r}")


if __name__ == "__main__":
    main()
