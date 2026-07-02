# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""PGRE blueprint weights, keyed by category slug.

The blueprint % is the Physics GRE's official per-topic weighting (stable for
20+ years). ``worth`` uses the **category-level** weight, so subtopics inherit
their category's %.

This table is intentionally duplicated per language (see
``docs/pgrep/planning/l1-coordination-schema.md`` §1) — it is a normal
cross-language boundary duplication. Do **not** factor it into a shared file or
import it across the Rust/Python boundary.
"""

from __future__ import annotations

# Category assigned to untagged / unrecognized cards (blueprint 0.0).
UNKNOWN_CATEGORY = "unknown"

# Canonical category slug -> blueprint weight, as a fraction of 1.0.
# Sum == 1.0.
BLUEPRINT_PERCENT: dict[str, float] = {
    "mechanics": 0.20,
    "electromagnetism": 0.18,
    "quantum": 0.13,
    "thermodynamics": 0.10,
    "atomic": 0.10,
    "optics_waves": 0.08,
    "special_relativity": 0.06,
    "lab": 0.06,
    "specialized": 0.09,
}

# The canonical category slugs, in blueprint order.
CATEGORY_SLUGS: tuple[str, ...] = tuple(BLUEPRINT_PERCENT.keys())


def blueprint_percent(category: str | None) -> float:
    """Blueprint weight (fraction of 1.0) for a category slug.

    Matching is case-insensitive. Untagged / unknown / unrecognized categories
    return ``0.0`` (never raises).
    """
    if not category:
        return 0.0
    return BLUEPRINT_PERCENT.get(category.strip().lower(), 0.0)
