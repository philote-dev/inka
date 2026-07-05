# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the dev-only pgrep demo profile injector (L5.9 P5).

The injector is a hands-on test and sync-demo tool. Injecting a hypothetical
profile must clear all three abstain gates (Memory, Performance, Readiness) so
the scores light up on demand, while a fresh, non-injected collection must still
abstain everywhere so real accounts stay honest by construction.

These tests prove: the fresh-collection abstain (the dev-only safety property),
that injection clears every gate, the demo marker, idempotency, reversibility
(clear reverts to abstain and touches only demo data), that the injected
attempts are clean, and that the two profiles differ in magnitude while both
clear the gates.
"""

from __future__ import annotations

import inspect

from anki.pgrep import demo_profile
from anki.pgrep.attempt_log import attempts
from anki.pgrep.demo_profile import (
    ATTEMPTS_PER_CATEGORY,
    CARDS_PER_CATEGORY,
    COVERAGE_WEIGHT,
    COVERED_CATEGORIES,
    DEFAULT_PROFILE,
    DEMO_TAG,
    clear_demo_profile,
    demo_status,
    inject_demo_profile,
    is_demo_injected,
)
from anki.pgrep.memory import K_MEM_DEFAULT, memory_score
from anki.pgrep.performance import K_PERF_DEFAULT, MIN_RESPONSE_MS_DEFAULT, performance_score
from anki.pgrep.readiness import readiness_score
from tests.shared import getEmptyCol

_EXPECTED_CARDS = CARDS_PER_CATEGORY * len(COVERED_CATEGORIES)
_EXPECTED_ATTEMPTS = ATTEMPTS_PER_CATEGORY * len(COVERED_CATEGORIES)


def _topic(data: dict, category: str) -> dict:
    return next(t for t in data["by_topic"] if t["category"] == category)


# --- dev-only safety: a fresh account abstains by construction ---------------


def test_fresh_collection_abstains_everywhere():
    # The core safety property: with no injection, all three scores abstain, so a
    # real account is honest by construction. Nothing auto-injects.
    col = getEmptyCol()

    assert is_demo_injected(col) is False
    assert memory_score(col)["overall"]["abstain"] is True
    assert performance_score(col)["overall"]["abstain"] is True
    assert readiness_score(col)["abstain"] is True


# --- injection clears all three abstain gates --------------------------------


def test_inject_clears_all_three_gates():
    col = getEmptyCol()

    summary = inject_demo_profile(col)

    assert summary["already_injected"] is False
    assert summary["cards_created"] == _EXPECTED_CARDS
    assert summary["attempts_created"] == _EXPECTED_ATTEMPTS

    # Memory, Performance, and Readiness all produce real numbers now.
    memory = memory_score(col)
    performance = performance_score(col)
    readiness = readiness_score(col)

    assert memory["overall"]["abstain"] is False
    assert 0.0 < memory["overall"]["point"] <= 1.0

    assert performance["overall"]["abstain"] is False
    assert 0.0 < performance["overall"]["point"] < 1.0

    assert readiness["abstain"] is False
    assert readiness["reason"] is None
    assert 360 <= readiness["scaled"] <= 990
    assert readiness["low"] <= readiness["scaled"] <= readiness["high"]


def test_each_covered_category_scores_memory_and_performance():
    col = getEmptyCol()
    inject_demo_profile(col)

    memory = memory_score(col)
    performance = performance_score(col)

    for category in COVERED_CATEGORIES:
        mem_entry = _topic(memory, category)
        assert mem_entry["abstain"] is False, category
        assert mem_entry["n_cards"] >= K_MEM_DEFAULT

        perf_entry = _topic(performance, category)
        assert perf_entry["abstain"] is False, category
        assert perf_entry["n_attempts"] >= K_PERF_DEFAULT


def test_coverage_clears_the_readiness_gate():
    col = getEmptyCol()
    inject_demo_profile(col)

    readiness = readiness_score(col)

    assert abs(readiness["coverage_pct"] - COVERAGE_WEIGHT) < 1e-9
    assert readiness["coverage_pct"] >= readiness["coverage_gate"]
    # The uncovered minority is still named honestly rather than faked.
    assert set(readiness["uncovered_topics"]) == {"lab", "specialized"}


# --- the demo marker is present ----------------------------------------------


def test_demo_marker_present_after_inject():
    col = getEmptyCol()
    inject_demo_profile(col)

    assert is_demo_injected(col) is True
    assert len(col.find_notes(f"tag:{DEMO_TAG}")) == _EXPECTED_CARDS


# --- idempotency -------------------------------------------------------------


def test_inject_is_idempotent():
    col = getEmptyCol()
    inject_demo_profile(col)
    cards_before = col.card_count()
    notes_before = col.note_count()

    again = inject_demo_profile(col)

    assert again["already_injected"] is True
    assert again["cards_created"] == 0
    assert again["attempts_created"] == 0
    # No duplicate cards or notes on a repeat call.
    assert col.card_count() == cards_before
    assert col.note_count() == notes_before
    assert len(col.find_notes(f"tag:{DEMO_TAG}")) == _EXPECTED_CARDS


# --- reversibility -----------------------------------------------------------


def test_clear_reverts_to_abstain():
    col = getEmptyCol()
    inject_demo_profile(col)

    result = clear_demo_profile(col)

    assert result["cleared"] is True
    assert result["cards_removed"] == _EXPECTED_CARDS
    assert result["attempts_removed"] == _EXPECTED_ATTEMPTS
    assert is_demo_injected(col) is False
    # Back to the honest, fresh-account behaviour: abstain everywhere.
    assert memory_score(col)["overall"]["abstain"] is True
    assert performance_score(col)["overall"]["abstain"] is True
    assert readiness_score(col)["abstain"] is True
    assert col.note_count() == 0


def test_clear_only_touches_demo_data():
    # Clearing the demo must leave any real (here, seed) data untouched.
    from anki.pgrep.seed import SEEDED_TAG, seed_sample_content

    col = getEmptyCol()
    seed_sample_content(col)
    seed_notes = set(col.find_notes(f"tag:{SEEDED_TAG}"))
    assert seed_notes

    inject_demo_profile(col)
    clear_demo_profile(col)

    assert set(col.find_notes(f"tag:{SEEDED_TAG}")) == seed_notes
    assert is_demo_injected(col) is False


def test_inject_after_clear_creates_a_fresh_profile():
    col = getEmptyCol()
    inject_demo_profile(col)
    clear_demo_profile(col)

    again = inject_demo_profile(col)

    assert again["already_injected"] is False
    assert again["cards_created"] == _EXPECTED_CARDS
    assert readiness_score(col)["abstain"] is False


# --- the injected attempts are clean and reversible --------------------------


def test_injected_attempts_are_clean_and_marked():
    col = getEmptyCol()
    inject_demo_profile(col)

    events = attempts(col)
    assert len(events) == _EXPECTED_ATTEMPTS
    for event in events:
        # Clean by construction: first-try (no ladder) and not a rapid guess.
        assert event.payload.get("ladder_depth") == 0
        assert event.payload.get("response_ms") >= MIN_RESPONSE_MS_DEFAULT
        # Marked so clear can find it without mutating the immutable note.
        assert event.payload.get("demo") is True


# --- profiles ----------------------------------------------------------------


def test_strong_scores_higher_than_rusty_but_both_clear_gates():
    strong = getEmptyCol()
    rusty = getEmptyCol()
    inject_demo_profile(strong, "strong")
    inject_demo_profile(rusty, "rusty")

    strong_readiness = readiness_score(strong)
    rusty_readiness = readiness_score(rusty)

    # Both clear every gate...
    assert strong_readiness["abstain"] is False
    assert rusty_readiness["abstain"] is False
    # ...but the strong learner projects a higher scaled score and Performance.
    assert strong_readiness["scaled"] > rusty_readiness["scaled"]
    assert (
        performance_score(strong)["overall"]["point"]
        > performance_score(rusty)["overall"]["point"]
    )


def test_unknown_profile_falls_back_to_default():
    col = getEmptyCol()

    summary = inject_demo_profile(col, "does-not-exist")

    assert summary["profile"] == DEFAULT_PROFILE
    assert readiness_score(col)["abstain"] is False


# --- the status snapshot the lab surface renders -----------------------------


def test_demo_status_reports_injection_and_scores():
    col = getEmptyCol()

    before = demo_status(col)
    assert before["injected"] is False
    assert before["profile"] is None
    assert before["scores"]["memory"]["abstain"] is True
    assert before["scores"]["performance"]["abstain"] is True
    assert before["scores"]["readiness"]["abstain"] is True

    inject_demo_profile(col, "strong")
    after = demo_status(col)

    assert after["injected"] is True
    assert after["profile"] == "strong"
    assert after["demo_cards"] == _EXPECTED_CARDS
    assert after["demo_attempts"] == _EXPECTED_ATTEMPTS
    assert after["scores"]["memory"]["abstain"] is False
    assert after["scores"]["performance"]["abstain"] is False
    assert after["scores"]["readiness"]["abstain"] is False
    assert after["scores"]["readiness"]["scaled"] is not None


# --- AI-off by construction --------------------------------------------------


def test_ai_off_no_ai_imports():
    # A dev seeding tool must never drag in AI or the network. Guard the source.
    source = inspect.getsource(demo_profile)
    forbidden = (
        "pgrep.ai",
        "import openai",
        "import anthropic",
        "import httpx",
        "import requests",
        "import torch",
        "urllib",
    )
    for token in forbidden:
        assert token not in source, f"unexpected AI/network import: {token}"
