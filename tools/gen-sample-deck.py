#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Generate the sample Physics-GRE deck as a collection.anki2 for the iOS app.

This produces a reproducible, self-contained Anki collection that the pgrep iOS
app bundles and opens via the shared Rust engine to run a review.

To guarantee the phone and desktop review *the same deck* (the Wednesday MVP
requirement), it delegates to ``anki.pgrep.seed.seed_sample_content`` -- the
exact function the desktop uses to seed its ``PGRE::Sample`` deck. So the phone
gets the identical topic-tagged cards, the same FSRS review state, and the same
points-at-stake review order, which means the L1 selector runs on the phone
build too. The iOS app studies the parent ``PGRE`` deck, which includes the
``PGRE::Sample`` subdeck these cards live in.

Regenerate (from the repo root, after a desktop build has populated out/):

    PYTHONPATH="$(pwd)/out/pylib" out/pyenv/bin/python tools/gen-sample-deck.py

The output path defaults to mobile/sample-deck/collection.anki2 and can be
overridden with the first argument. Any existing file at the destination is
removed first so the result is deterministic. Regenerate and commit the .anki2
whenever the shared seed changes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from anki.collection import Collection
from anki.pgrep import seed

# Path is relative to the repo root so the default works from any CWD.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "mobile" / "sample-deck" / "collection.anki2"


def generate(output_path: Path) -> dict[str, Any]:
    """Create a fresh collection at output_path via the shared desktop seed.

    Returns the seed summary dict, augmented with ``card_count``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Collection() creates a new DB when the file is absent; remove any existing
    # file first so the generated deck is deterministic.
    if output_path.exists():
        output_path.unlink()

    col = Collection(str(output_path))
    try:
        summary = seed.seed_sample_content(col)
        summary["card_count"] = col.card_count()
    finally:
        col.close()
    return summary


def main() -> None:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    summary = generate(output_path)
    print(f"Wrote {os.path.relpath(output_path)}")
    print(
        f"Seeded {summary['card_count']} cards into deck {seed.DECK_NAME!r} "
        f"across {len(summary['categories'])} categories "
        f"(topic-tagged, points-at-stake review order)."
    )


if __name__ == "__main__":
    main()
