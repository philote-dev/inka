# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the two-level topic-tag parsing helpers (L1.2).

Contract: docs/pgrep/planning/l1-coordination-schema.md §1.
"""

from __future__ import annotations

import pytest

from anki.pgrep.blueprint import (
    BLUEPRINT_PERCENT,
    CATEGORY_SLUGS,
    UNKNOWN_CATEGORY,
    blueprint_percent,
)
from anki.pgrep.tags import (
    blueprint_percent_for,
    category_for,
    category_of,
    finest_topic,
    topic_tags,
)


def test_blueprint_table_sums_to_one():
    assert pytest.approx(sum(BLUEPRINT_PERCENT.values()), abs=1e-9) == 1.0
    assert len(CATEGORY_SLUGS) == 9


def test_blueprint_percent_lookup_by_category():
    assert blueprint_percent("mechanics") == 0.20
    assert blueprint_percent("electromagnetism") == 0.18
    assert blueprint_percent("quantum") == 0.13
    assert blueprint_percent("specialized") == 0.09


def test_blueprint_percent_is_case_insensitive():
    assert blueprint_percent("Mechanics") == 0.20
    assert blueprint_percent(" QUANTUM ") == 0.13


def test_blueprint_percent_unknown_is_zero():
    assert blueprint_percent("not_a_real_category") == 0.0
    assert blueprint_percent(UNKNOWN_CATEGORY) == 0.0
    assert blueprint_percent("") == 0.0
    assert blueprint_percent(None) == 0.0


def test_category_extraction():
    assert category_of("topic::mechanics") == "mechanics"
    assert category_of("topic::mechanics::lagrangian") == "mechanics"
    assert category_of("topic::electromagnetism::maxwell") == "electromagnetism"


def test_category_extraction_is_case_insensitive_on_prefix():
    assert category_of("Topic::Mechanics::Lagrangian") == "mechanics"


def test_category_of_non_topic_or_empty_is_unknown():
    assert category_of("deck::foo") == UNKNOWN_CATEGORY
    assert category_of("topic") == UNKNOWN_CATEGORY
    assert category_of("topic::") == UNKNOWN_CATEGORY
    assert category_of(None) == UNKNOWN_CATEGORY


def test_topic_tags_filters_only_topic_tags():
    tags = ["marked", "topic::mechanics::lagrangian", "leech"]
    assert topic_tags(tags) == ["topic::mechanics::lagrangian"]


def test_finest_topic_returns_full_tag():
    tags = ["topic::quantum::spin", "other"]
    assert finest_topic(tags) == "topic::quantum::spin"


def test_finest_topic_untagged_is_none():
    assert finest_topic(["marked", "leech"]) is None
    assert finest_topic([]) is None
    assert finest_topic("") is None
    assert finest_topic(None) is None


def test_multiple_topic_tags_first_wins():
    tags = ["topic::optics_waves::diffraction", "topic::mechanics::lagrangian"]
    assert finest_topic(tags) == "topic::optics_waves::diffraction"
    assert category_for(tags) == "optics_waves"
    assert blueprint_percent_for(tags) == 0.08


def test_subtopic_inherits_category_percent():
    # a subtopic uses its category's blueprint weight
    assert blueprint_percent_for(["topic::mechanics::lagrangian"]) == 0.20
    assert blueprint_percent_for(["topic::mechanics"]) == 0.20
    assert blueprint_percent_for(["topic::mechanics::rotational_dynamics"]) == (
        blueprint_percent_for(["topic::mechanics"])
    )


def test_untagged_blueprint_is_zero_and_unknown():
    assert category_for(["marked"]) == UNKNOWN_CATEGORY
    assert blueprint_percent_for(["marked"]) == 0.0
    assert blueprint_percent_for([]) == 0.0
    assert blueprint_percent_for(None) == 0.0


def test_str_vs_list_input_equivalent():
    as_str = "topic::thermodynamics::entropy extra_tag"
    as_list = ["topic::thermodynamics::entropy", "extra_tag"]
    assert topic_tags(as_str) == topic_tags(as_list)
    assert finest_topic(as_str) == finest_topic(as_list)
    assert category_for(as_str) == "thermodynamics"
    assert blueprint_percent_for(as_str) == 0.10
    # Anki's DB tag form has leading/trailing spaces; that must parse too.
    assert category_for(" topic::atomic::hydrogen ") == "atomic"
