# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The calibration gate for pgrep (card-sets plan §4).

Calibration is the generation-effect act: the learner writes one card in their
own words for each blueprint category. It is the learning-science pillar of
onboarding and, when AI is on, the gate in front of Study.

A collection is **calibrated** once it has at least one learner-authored card
(:data:`anki.pgrep.generation.SEED_TAG`) in every blueprint category, or once
the sticky "complete" flag has been recorded. The flag makes calibration
durable: removing an authored card later never re-locks Study. Only
learner-authored cards count; the bundled sample cards calibrate nothing, so a
fresh collection is honestly uncalibrated.

The gate itself is derived wherever it is read (``aiEnabled && !calibrated``):
Study locks and Library shows the walkthrough while AI is on and calibration is
incomplete; turning AI off relaxes both. No AI is imported here, and no
scheduling state is read or written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.generation import SEED_TAG
from anki.pgrep.tags import category_for

if TYPE_CHECKING:
    from anki.collection import Collection

# Sticky "calibration complete" flag in the collection config (mirrors the
# Diagnostic gate's stored snapshot). Once set, it stays set.
CALIBRATION_CONFIG_KEY = "pgrepCalibrated"

# One learner-authored card per blueprint category calibrates the collection.
REQUIRED_CATEGORIES = len(CATEGORY_SLUGS)


def _covered_categories(col: Collection) -> set[str]:
    """Blueprint categories with at least one learner-authored card."""
    covered: set[str] = set()
    for nid in col.find_notes(f"tag:{SEED_TAG}"):
        category = category_for(col.get_note(nid).tags)
        if category in CATEGORY_SLUGS:
            covered.add(category)
    return covered


def calibration_status(col: Collection) -> dict[str, Any]:
    """Return ``{calibrated, authored, required}`` for the calibration gate.

    ``authored`` is how many blueprint categories the learner has authored a card
    in; ``required`` is all of them. ``calibrated`` is true once every category
    is covered, and is then recorded as a sticky flag so it survives a later card
    deletion. JSON-serializable; no AI, no scheduler.
    """
    authored = len(_covered_categories(col))
    calibrated = bool(col.get_config(CALIBRATION_CONFIG_KEY, False))
    if not calibrated and authored >= REQUIRED_CATEGORIES:
        # Set-on-completion: calibration is durable once reached.
        col.set_config(CALIBRATION_CONFIG_KEY, True)
        calibrated = True
    return {
        "calibrated": calibrated,
        "authored": authored,
        "required": REQUIRED_CATEGORIES,
    }
