# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the dev-only pgrep demo profile injector (L5.9 P5).

The injector is a hands-on test and sync-demo tool. Injecting a hypothetical
profile lights up the scores on demand, while a fresh, non-injected collection
must still abstain everywhere so real accounts stay honest by construction.

These tests prove: the fresh-collection abstain (the dev-only safety property);
that a broad stage clears every gate; the demo marker; idempotency; reversibility
(clear reverts to abstain and touches only demo data); that the injected attempts
are clean; that the stages form a rising progression whose coverage grows so
Readiness honestly abstains early and appears once enough of the exam is covered;
and that preview projects a stage's scores without committing.
"""

from __future__ import annotations

import inspect

from anki.pgrep import demo_profile
from anki.pgrep.attempt_log import attempts
from anki.pgrep.blueprint import BLUEPRINT_PERCENT
from anki.pgrep.demo_profile import (
    ATTEMPTS_PER_CATEGORY,
    CARDS_PER_CATEGORY,
    DEFAULT_PROFILE,
    DEMO_DECK_NAME,
    DEMO_TAG,
    PROFILES,
    clear_demo_profile,
    demo_status,
    inject_demo_profile,
    is_demo_injected,
    preview_demo_profile,
)
from anki.pgrep.memory import K_MEM_DEFAULT, memory_score
from anki.pgrep.performance import (
    K_PERF_DEFAULT,
    MIN_RESPONSE_MS_DEFAULT,
    RECENCY_WINDOW_DEFAULT,
    performance_score,
)
from anki.pgrep.readiness import readiness_score
from tests.shared import getEmptyCol


def _categories(key: str) -> tuple[str, ...]:
    """The blueprint categories a stage covers (grows stage to stage)."""
    return tuple(category for category, _, _ in PROFILES[key].covered)


def _coverage_weight(key: str) -> float:
    return sum(BLUEPRINT_PERCENT[category] for category in _categories(key))


def _cards_for(key: str) -> int:
    return CARDS_PER_CATEGORY * len(PROFILES[key].covered)


def _attempts_for(key: str) -> int:
    return ATTEMPTS_PER_CATEGORY * len(PROFILES[key].covered)


# The bare inject / sync default is the broad exam-ready stage.
_DEFAULT_CARDS = _cards_for(DEFAULT_PROFILE)
_DEFAULT_ATTEMPTS = _attempts_for(DEFAULT_PROFILE)


def _topic(data: dict, category: str) -> dict:
    return next(t for t in data["by_topic"] if t["category"] == category)


def _scores_close(a: dict, b: dict, tol: float = 1e-6) -> bool:
    """Whether two score snapshots agree to well below display precision.

    FSRS retrievability is a continuous function of wall-clock time, so two score
    calls a moment apart can differ by a hair. The demo's contract is that the
    numbers the user sees do not jump, so we compare numerics with a tolerance and
    everything else (``abstain`` flags, ``reason`` strings) exactly.
    """
    if a.keys() != b.keys():
        return False
    for block in a:
        for field, x in a[block].items():
            y = b[block][field]
            numeric = isinstance(x, (int, float)) and not isinstance(x, bool)
            if numeric and isinstance(y, (int, float)) and not isinstance(y, bool):
                if abs(x - y) > tol:
                    return False
            elif x != y:
                return False
    return True


# --- dev-only safety: a fresh account abstains by construction ---------------


def test_fresh_collection_abstains_everywhere():
    # The core safety property: with no injection, all three scores abstain, so a
    # real account is honest by construction. Nothing auto-injects.
    col = getEmptyCol()

    assert is_demo_injected(col) is False
    assert memory_score(col)["overall"]["abstain"] is True
    assert performance_score(col)["overall"]["abstain"] is True
    assert readiness_score(col)["abstain"] is True


# --- a broad inject clears all three abstain gates ---------------------------


def test_inject_clears_all_three_gates():
    col = getEmptyCol()

    summary = inject_demo_profile(col)

    assert summary["already_injected"] is False
    assert summary["cards_created"] == _DEFAULT_CARDS
    assert summary["attempts_created"] == _DEFAULT_ATTEMPTS

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

    for category in _categories(DEFAULT_PROFILE):
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

    assert abs(readiness["coverage_pct"] - _coverage_weight(DEFAULT_PROFILE)) < 1e-9
    assert readiness["coverage_pct"] >= readiness["coverage_gate"]
    # The uncovered minority is still named honestly rather than faked.
    assert set(readiness["uncovered_topics"]) == {"lab", "specialized"}


# --- the demo marker is present ----------------------------------------------


def test_demo_marker_present_after_inject():
    col = getEmptyCol()
    inject_demo_profile(col)

    assert is_demo_injected(col) is True
    assert len(col.find_notes(f"tag:{DEMO_TAG}")) == _DEFAULT_CARDS


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
    assert len(col.find_notes(f"tag:{DEMO_TAG}")) == _DEFAULT_CARDS


def test_inject_switches_profiles_without_a_manual_clear():
    # Injecting a different stage over an existing one switches to it, instead
    # of the old silent no-op that stranded the lab on the first stage.
    col = getEmptyCol()
    inject_demo_profile(col, "nearing_exam")
    ready_scaled = readiness_score(col)["scaled"]

    switched = inject_demo_profile(col, "training")

    assert switched["already_injected"] is False
    assert switched["profile"] == "training"
    assert demo_status(col)["profile"] == "training"
    # No stale data: exactly the new stage's worth of demo cards after the switch.
    assert len(col.find_notes(f"tag:{DEMO_TAG}")) == _cards_for("training")
    # The scores now read as the earlier stage, lower than the exam-ready one.
    assert readiness_score(col)["scaled"] < ready_scaled


# --- reversibility -----------------------------------------------------------


def test_clear_reverts_to_abstain():
    col = getEmptyCol()
    inject_demo_profile(col)

    result = clear_demo_profile(col)

    assert result["cleared"] is True
    assert result["cards_removed"] == _DEFAULT_CARDS
    assert result["attempts_removed"] == _DEFAULT_ATTEMPTS
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


def test_clear_removes_the_empty_demo_deck():
    # A leftover empty demo deck would otherwise ride to mobile on the next sync.
    col = getEmptyCol()
    inject_demo_profile(col)
    assert col.decks.id_for_name(DEMO_DECK_NAME) is not None

    result = clear_demo_profile(col)

    assert result["deck_removed"] is True
    assert col.decks.id_for_name(DEMO_DECK_NAME) is None


def test_inject_after_clear_creates_a_fresh_profile():
    col = getEmptyCol()
    inject_demo_profile(col)
    clear_demo_profile(col)

    again = inject_demo_profile(col)

    assert again["already_injected"] is False
    assert again["cards_created"] == _DEFAULT_CARDS
    assert readiness_score(col)["abstain"] is False


# --- the injected attempts are clean and reversible --------------------------


def test_injected_attempts_are_clean_and_marked():
    col = getEmptyCol()
    inject_demo_profile(col)

    events = attempts(col)
    assert len(events) == _DEFAULT_ATTEMPTS
    for event in events:
        # Clean by construction: first-try (no ladder) and not a rapid guess.
        assert event.payload.get("ladder_depth") == 0
        assert event.payload.get("response_ms") >= MIN_RESPONSE_MS_DEFAULT
        # Marked so clear can find it without mutating the immutable note.
        assert event.payload.get("demo") is True


# --- profiles / stages -------------------------------------------------------


def test_nearing_exam_has_varied_correctness_and_recent_failures():
    # The exam-ready stage must feed a real recent-failure term, not a hidden miss
    # front-loaded outside the recency window. Every covered area has varied
    # correctness (neither a perfect run nor an all-miss run), and most feed a
    # non-zero recent-failure count over the last RECENCY_WINDOW attempts.
    col = getEmptyCol()
    inject_demo_profile(col, "nearing_exam")

    topics_with_recent_miss = 0
    categories = _categories("nearing_exam")
    for category in categories:
        events = attempts(col, topic=f"topic::{category}")  # oldest first
        assert len(events) == ATTEMPTS_PER_CATEGORY
        n_correct = sum(1 for event in events if event.correct)
        assert 0 < n_correct < ATTEMPTS_PER_CATEGORY, category
        window = events[-RECENCY_WINDOW_DEFAULT:]
        if any(not event.correct for event in window):
            topics_with_recent_miss += 1

    # Most covered areas (here, all of them) exercise the recency-failure term.
    assert topics_with_recent_miss >= len(categories) - 1
    # It still reads as a strong learner overall.
    assert performance_score(col)["overall"]["point"] > 0.7


def test_diagnostic_has_scores_but_no_readiness_yet():
    # The day-one stage: the learner has reviewed cards and done some practice, so
    # Memory and Performance score, but they have not covered enough of the exam
    # for a Readiness score. That "no Readiness yet" state is the point of it.
    col = getEmptyCol()
    inject_demo_profile(col, "diagnostic")

    assert memory_score(col)["overall"]["abstain"] is False
    assert performance_score(col)["overall"]["abstain"] is False

    readiness = readiness_score(col)
    assert readiness["abstain"] is True
    assert readiness["scaled"] is None
    assert readiness["reason"]  # an honest, non-empty reason
    # Coverage really is below the gate (not a data accident).
    assert readiness["coverage_pct"] < readiness["coverage_gate"]


def test_stages_form_a_rising_progression_with_growing_coverage():
    # The stages step from a day-one diagnostic to exam-ready: Memory, Performance
    # and blueprint coverage all climb. Readiness abstains at the diagnostic (below
    # the coverage gate), then appears and climbs once the learner covers enough.
    memory: list[float] = []
    perf: list[float] = []
    coverage: list[float] = []
    readiness_scaled: list[float] = []
    for key in ("diagnostic", "training", "nearing_exam"):
        col = getEmptyCol()
        inject_demo_profile(col, key)
        memory.append(memory_score(col)["overall"]["point"])
        perf.append(performance_score(col)["overall"]["point"])
        readiness = readiness_score(col)
        coverage.append(readiness["coverage_pct"])

        if key == "diagnostic":
            assert readiness["abstain"] is True
        else:
            assert readiness["abstain"] is False
            readiness_scaled.append(readiness["scaled"])

    assert memory[0] < memory[1] < memory[2]
    assert perf[0] < perf[1] < perf[2]
    assert coverage[0] < coverage[1] < coverage[2]
    # Diagnostic is below the gate; the other two are above and climb.
    assert coverage[0] < 0.70 <= coverage[1]
    assert readiness_scaled[0] < readiness_scaled[1]


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
    # Nothing injected: no covered areas claimed.
    assert before["covered_categories"] == []

    inject_demo_profile(col, "nearing_exam")
    after = demo_status(col)

    assert after["injected"] is True
    assert after["profile"] == "nearing_exam"
    assert after["demo_cards"] == _cards_for("nearing_exam")
    assert after["demo_attempts"] == _attempts_for("nearing_exam")
    assert set(after["covered_categories"]) == set(_categories("nearing_exam"))
    assert after["scores"]["memory"]["abstain"] is False
    assert after["scores"]["performance"]["abstain"] is False
    assert after["scores"]["readiness"]["abstain"] is False
    assert after["scores"]["readiness"]["scaled"] is not None


def test_demo_status_reports_the_active_stage_coverage():
    # Each stage reports its own covered slice (the lab caption reads from this).
    col = getEmptyCol()
    inject_demo_profile(col, "diagnostic")

    status = demo_status(col)
    assert set(status["covered_categories"]) == set(_categories("diagnostic"))
    assert abs(status["coverage_weight"] - _coverage_weight("diagnostic")) < 1e-9
    # Diagnostic's slice is below the gate, so the snapshot's readiness abstains.
    assert status["scores"]["readiness"]["abstain"] is True


# --- preview: scores on selection, without committing ------------------------


def test_preview_reports_scores_without_committing():
    # Selecting a stage previews its scores, but must not write to the collection:
    # the committed state stays empty so a real account is still honest.
    col = getEmptyCol()

    snapshot = preview_demo_profile(col, "nearing_exam")

    assert snapshot["preview"] is True
    assert snapshot["preview_profile"] == "nearing_exam"
    # The preview carries real, lit-up scores...
    assert snapshot["scores"]["readiness"]["abstain"] is False
    assert snapshot["scores"]["memory"]["abstain"] is False
    assert snapshot["scores"]["performance"]["abstain"] is False
    # ...but reports the (empty) committed state and leaves nothing behind.
    assert snapshot["injected"] is False
    assert snapshot["profile"] is None
    assert is_demo_injected(col) is False
    assert col.note_count() == 0


def test_preview_scores_match_a_real_inject():
    # The preview projection must equal what committing the stage actually yields,
    # so the numbers do not jump when the user clicks Inject.
    preview_col = getEmptyCol()
    inject_col = getEmptyCol()

    previewed = preview_demo_profile(preview_col, "training")
    inject_demo_profile(inject_col, "training")
    committed = demo_status(inject_col)

    assert _scores_close(previewed["scores"], committed["scores"])
    assert previewed["coverage_pct"] == committed["coverage_pct"]


def test_preview_restores_a_previously_committed_stage():
    # Previewing a different stage while one is committed must leave the committed
    # stage exactly as it was (same data, same scores).
    col = getEmptyCol()
    inject_demo_profile(col, "diagnostic")
    committed_before = demo_status(col)

    snapshot = preview_demo_profile(col, "nearing_exam")

    # The preview shows the requested stage but names the committed one.
    assert snapshot["preview"] is True
    assert snapshot["preview_profile"] == "nearing_exam"
    assert snapshot["injected"] is True
    assert snapshot["profile"] == "diagnostic"
    # The committed stage is untouched: still diagnostic, same data and scores.
    assert is_demo_injected(col) is True
    assert demo_status(col)["profile"] == "diagnostic"
    assert len(col.find_notes(f"tag:{DEMO_TAG}")) == _cards_for("diagnostic")
    assert _scores_close(demo_status(col)["scores"], committed_before["scores"])


def test_preview_of_the_committed_stage_is_live_not_a_projection():
    # Previewing the stage that is already committed is its live status (no churn),
    # so it is not flagged as a projection.
    col = getEmptyCol()
    inject_demo_profile(col, "training")

    snapshot = preview_demo_profile(col, "training")

    assert snapshot["preview"] is False
    assert snapshot["injected"] is True
    assert snapshot["profile"] == "training"


def test_all_profiles_preview_cleanly():
    # Every stage previews and rolls back cleanly on a fresh collection. Memory
    # scores for every stage; Readiness only once the stage covers enough.
    col = getEmptyCol()
    for key in PROFILES:
        snapshot = preview_demo_profile(col, key)
        assert snapshot["preview"] is True
        assert snapshot["scores"]["memory"]["abstain"] is False
        expected_abstain = _coverage_weight(key) < snapshot["coverage_gate"]
        assert snapshot["scores"]["readiness"]["abstain"] is expected_abstain
        assert is_demo_injected(col) is False
        assert col.note_count() == 0


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
