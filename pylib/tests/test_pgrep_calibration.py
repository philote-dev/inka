# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the calibration gate (card-sets plan §4).

A collection is calibrated once the learner has authored one card in every
blueprint category. Bundled sample cards calibrate nothing; the flag is sticky
once earned. Also covers the app's first-run AI-on default, which makes
calibration the paramount onboarding step while leaving the pure default off.
"""

from anki.pgrep import ai_config, calibration, generation
from anki.pgrep.blueprint import CATEGORY_SLUGS
from anki.pgrep.calibration import CALIBRATION_CONFIG_KEY, calibration_status
from anki.pgrep.seed import seed_sample_content
from tests.shared import getEmptyCol


def test_fresh_collection_is_uncalibrated():
    col = getEmptyCol()

    status = calibration_status(col)

    assert status["calibrated"] is False
    assert status["authored"] == 0
    assert status["required"] == len(CATEGORY_SLUGS)


def test_bundled_samples_do_not_calibrate():
    col = getEmptyCol()

    # Seeding fills every category with sample cards, but those are not learner
    # authored, so the collection stays honestly uncalibrated.
    seed_sample_content(col)

    status = calibration_status(col)
    assert status["authored"] == 0
    assert status["calibrated"] is False


def test_authoring_every_category_calibrates_and_sticks():
    col = getEmptyCol()

    for i, category in enumerate(CATEGORY_SLUGS):
        generation.author_seed(col, f"Front {i}", f"Back {i}", category)
        status = calibration_status(col)
        if i < len(CATEGORY_SLUGS) - 1:
            # Partial coverage never calibrates.
            assert status["calibrated"] is False
            assert status["authored"] == i + 1

    # The final category completes coverage and calibrates the collection, and
    # the sticky flag is recorded.
    final = calibration_status(col)
    assert final["authored"] == len(CATEGORY_SLUGS)
    assert final["calibrated"] is True
    assert col.get_config(CALIBRATION_CONFIG_KEY, False) is True


def test_calibration_is_sticky_once_earned():
    col = getEmptyCol()

    # Record the sticky flag directly (as completion would): calibration holds
    # even with no authored coverage, so a later card deletion never re-locks.
    col.set_config(CALIBRATION_CONFIG_KEY, True)

    status = calibration_status(col)
    assert status["calibrated"] is True
    assert status["authored"] == 0


def test_first_run_defaults_turn_ai_on_once_without_overriding_choice():
    col = getEmptyCol()

    # The pure default is off, so a bare collection needs no AI.
    assert ai_config.ai_enabled(col) is False

    # The app's first-run default turns AI on.
    ai_config.ensure_first_run_defaults(col)
    assert ai_config.ai_enabled(col) is True

    # A learner who then turns AI off is never overridden by a later run.
    ai_config.set_ai_enabled(col, False)
    ai_config.ensure_first_run_defaults(col)
    assert ai_config.ai_enabled(col) is False


def test_first_run_defaults_respect_an_explicit_pre_set_off():
    col = getEmptyCol()

    # Explicit off before the first run must survive (the escape hatch).
    ai_config.set_ai_enabled(col, False)
    ai_config.ensure_first_run_defaults(col)

    assert ai_config.ai_enabled(col) is False
