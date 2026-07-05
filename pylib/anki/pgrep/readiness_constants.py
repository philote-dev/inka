# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Embedded PGRE raw-to-scaled score-conversion constants (Tier-3, constants only).

Readiness maps an expected raw score to the PGRE 200-990 scaled band via the
official raw-to-scaled conversion table (``three-scores.md`` §3). That table is a
**private Tier-3 dependency** (a copyrighted practice-test artifact), so we may
**not** ship the source items. What we *can* ship are the **numeric conversion
constants**: raw-score ranges to scaled scores are plain factual mappings, not
copyrightable content.

This module therefore embeds the numeric table as a tracked constant. The values
were generated **from** the private JSON
``content/tier3-private/constants/raw_to_scaled.json`` (mirrored, with
percentiles, in ``gr0177_score_conversion.json``), which itself documents:

    - source: a published GRE Physics prep-book conversion table (p.8);
    - raw score = ``round(correct - incorrect / 4)`` over 100 scored questions;
    - scale 200-990 in 10-point steps;
    - a 64-row table of ``{raw_min, raw_max, scaled}`` covering raw 0..100.

Shipping the numbers here, rather than reading ``content/`` at runtime, is what
"constants only" means: ``content/`` is gitignored and will not exist in the
shipped app, and the AI-path leakage firewall stays green because nothing on the
scoring path references a private root. Regenerate this table (never hand-edit)
if the private source is ever corrected.
"""

from __future__ import annotations

# The PGRE has this many scored questions; the raw axis of the table spans them.
SCORED_QUESTION_COUNT = 100

# The raw axis is formula-scored (a quarter-point penalty per wrong answer),
# rounded to the nearest integer. Documented here so Readiness can state the
# assumption it makes when turning expected-correct into this raw.
RAW_SCORE_FORMULA = "round(correct - incorrect / 4)"

# Inclusive raw domain of the table (a raw outside this is clamped before lookup).
RAW_MIN = 0
RAW_MAX = 100

# The conversion table, ``(raw_min, raw_max, scaled)`` per row, highest raw first.
# Every raw in [RAW_MIN, RAW_MAX] falls in exactly one row (contiguous, no gaps),
# and ``scaled`` is strictly increasing with raw. Generated from
# ``content/tier3-private/constants/raw_to_scaled.json`` (64 rows) — do not edit
# by hand; regenerate from the private source if it changes.
RAW_TO_SCALED_TABLE: tuple[tuple[int, int, int], ...] = (
    (84, 100, 990),
    (83, 83, 980),
    (81, 82, 970),
    (80, 80, 960),
    (79, 79, 950),
    (77, 78, 940),
    (76, 76, 930),
    (75, 75, 920),
    (73, 74, 910),
    (72, 72, 900),
    (71, 71, 890),
    (69, 70, 880),
    (68, 68, 870),
    (67, 67, 860),
    (65, 66, 850),
    (64, 64, 840),
    (63, 63, 830),
    (61, 62, 820),
    (60, 60, 810),
    (59, 59, 800),
    (57, 58, 790),
    (56, 56, 780),
    (55, 55, 770),
    (53, 54, 760),
    (52, 52, 750),
    (51, 51, 740),
    (49, 50, 730),
    (48, 48, 720),
    (47, 47, 710),
    (45, 46, 700),
    (44, 44, 690),
    (43, 43, 680),
    (41, 42, 670),
    (40, 40, 660),
    (39, 39, 650),
    (37, 38, 640),
    (36, 36, 630),
    (35, 35, 620),
    (33, 34, 610),
    (32, 32, 600),
    (30, 31, 590),
    (29, 29, 580),
    (28, 28, 570),
    (26, 27, 560),
    (25, 25, 550),
    (24, 24, 540),
    (22, 23, 530),
    (21, 21, 520),
    (20, 20, 510),
    (18, 19, 500),
    (17, 17, 490),
    (16, 16, 480),
    (14, 15, 470),
    (13, 13, 460),
    (12, 12, 450),
    (10, 11, 440),
    (9, 9, 430),
    (8, 8, 420),
    (6, 7, 410),
    (5, 5, 400),
    (4, 4, 390),
    (2, 3, 380),
    (1, 1, 370),
    (0, 0, 360),
)
