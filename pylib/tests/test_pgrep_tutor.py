# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the scaffold-fade tutor (L4.3).

Covers the AI-off reveal-and-self-compare path (the spec baseline, no deps), the
AI-on rubric grading path with a faked LLM, the giveaway verifier refusing a
leaky probe, and session synthesis over the attempt log.
"""

from __future__ import annotations

import json
import time

from anki.pgrep import ai_config, attempt_log, problem, tutor
from anki.pgrep.ai import llm as llm_module
from tests.shared import getEmptyCol


def _make_problem(col) -> int:
    notetype = problem.ensure_problem_notetype(col)
    note = col.new_note(notetype)
    note[problem.FIELD_STEM] = "A 500 nm photon energy (hc = 1240 eV nm)?"
    note[problem.FIELD_CHOICES] = json.dumps(
        ["0.40 eV", "1.24 eV", "2.48 eV", "4.96 eV", "620 eV"]
    )
    note[problem.FIELD_CORRECT] = "C"
    note[problem.FIELD_DISTRACTOR_RATIONALES] = json.dumps({"A": "inverted"})
    note[problem.FIELD_SOLUTION_DECOMPOSITION] = json.dumps(
        [
            {"subgoal": "Pick the relation", "rubric": "writes E = hc/lambda"},
            {
                "subgoal": "Insert values",
                "rubric": "uses hc = 1240 eV nm with lambda in nm",
            },
        ]
    )
    note[problem.FIELD_DIFFICULTY] = "medium"
    note[problem.FIELD_SOURCE_REF] = "OpenStax Vol 3, p. 254"
    col.add_note(note, col.decks.id("PGRE::Problems"))
    return note.id


class _FakeLLM:
    def __init__(self, model, response, **_kw):
        self.model = model
        self._response = response

    def complete_json(self, system, user):
        return dict(self._response)


def test_grade_subgoal_ai_off_reveals_for_self_compare():
    col = getEmptyCol()
    nid = _make_problem(col)
    res = tutor.grade_subgoal(col, nid, 0, "E equals hc over lambda")
    assert res["ai"] == "off"
    assert res["mode"] == "reveal"
    assert res["subgoal"] == "Pick the relation"
    assert res["is_last"] is False


def test_grade_subgoal_ai_on_grades(monkeypatch):
    col = getEmptyCol()
    nid = _make_problem(col)
    ai_config.set_ai_enabled(col, True)
    ai_config.set_ai_model(col, "gpt-x-2026-01-01")
    monkeypatch.setattr(
        llm_module,
        "LLMClient",
        lambda m, **kw: _FakeLLM(
            m,
            {"coverage": "partial", "probe": "Which variable goes in the denominator?"},
        ),
    )
    res = tutor.grade_subgoal(col, nid, 0, "energy is proportional to wavelength")
    assert res["ai"] == "on" and res["mode"] == "grade"
    assert res["coverage"] == "partial"
    assert res["giveaway_blocked"] is False


def test_grade_subgoal_giveaway_probe_is_blocked(monkeypatch):
    col = getEmptyCol()
    nid = _make_problem(col)
    ai_config.set_ai_enabled(col, True)
    ai_config.set_ai_model(col, "gpt-x-2026-01-01")
    # A probe that leaks the key text must be refused and replaced.
    monkeypatch.setattr(
        llm_module,
        "LLMClient",
        lambda m, **kw: _FakeLLM(
            m, {"coverage": "missing", "probe": "Recall that the answer is 2.48 eV."}
        ),
    )
    res = tutor.grade_subgoal(col, nid, 0, "no idea")
    assert res["giveaway_blocked"] is True
    assert "2.48" not in res["probe"]


def test_session_synthesis_ai_off_score():
    col = getEmptyCol()
    base = int(time.time())
    for i in range(3):
        attempt_log.append_attempt(
            col,
            {
                "event_id": f"s1-{i}",
                "topic": "topic::atomic",
                "correct": i != 0,
                "session_id": "sess-1",
                # spread across ~4 minutes so the wall-clock duration is exercised
                "answered_at": base + i * 120,
            },
        )
    res = tutor.session_synthesis(col, "sess-1")
    assert res["ai"] == "off"
    assert res["score"] == {"correct": 2, "total": 3}
    assert res["duration_min"] == 4
    assert len(res["by_topic"]) == 1
    only = res["by_topic"][0]
    assert (only["correct"], only["total"]) == (2, 3)
    # AI off still names the weak topic as a miss card, with no invented evidence.
    assert res["patterns"] and res["patterns"][0]["kind"] == "miss"
    assert res["patterns"][0]["evidence"] == ""


def test_session_synthesis_preview_matches_contract():
    col = getEmptyCol()
    res = tutor.session_synthesis_preview(col)
    assert res["score"] == {"correct": 14, "total": 20}
    assert res["duration_min"] == 48
    assert len(res["by_topic"]) == 4
    kinds = {p["kind"] for p in res["patterns"]}
    assert kinds == {"miss", "save"}


class _CaptureLLM:
    """Records the user prompt so a test can assert the grounding fed to the model."""

    def __init__(self, model, seen, response, **_kw):
        self.model = model
        self._seen = seen
        self._response = response

    def complete_json(self, system, user):
        self._seen["user"] = user
        return dict(self._response)


def test_session_synthesis_ai_on_grounds_real_misses(monkeypatch):
    col = getEmptyCol()
    nid = _make_problem(col)
    ai_config.set_ai_enabled(col, True)
    ai_config.set_ai_model(col, "gpt-x-2026-01-01")
    seen: dict[str, str] = {}
    response = {
        "patterns": [
            {
                "title": "Inverted the photon energy relation",
                "count": 1,
                "evidence": r"Treats \(E \propto \lambda\) instead of \(E = hc/\lambda\).",
            }
        ]
    }
    monkeypatch.setattr(
        llm_module,
        "LLMClient",
        lambda m, **kw: _CaptureLLM(m, seen, response),
    )
    # One clean first-try miss on a real problem (picked A, whose stored rationale
    # is "inverted"; the key is C), plus one clean correct, in one session.
    base = int(time.time())
    attempt_log.append_attempt(
        col,
        {
            "event_id": "sx-0",
            "item_note_id": nid,
            "topic": "topic::atomic",
            "correct": False,
            "selected_option": "A",
            "session_id": "sess-x",
            "answered_at": base,
        },
    )
    attempt_log.append_attempt(
        col,
        {
            "event_id": "sx-1",
            "item_note_id": nid,
            "topic": "topic::atomic",
            "correct": True,
            "selected_option": "C",
            "session_id": "sess-x",
            "answered_at": base + 60,
        },
    )
    res = tutor.session_synthesis(col, "sess-x")
    assert res["ai"] == "on"
    assert res["score"] == {"correct": 1, "total": 2}
    assert res["patterns"] and res["patterns"][0]["kind"] == "miss"
    assert res["patterns"][0]["title"] == "Inverted the photon energy relation"
    # The model was grounded in the real miss: the stem, the picked wrong choice,
    # and that choice's stored rationale ("inverted").
    grounded = seen["user"].lower()
    assert "photon" in grounded
    assert "inverted" in grounded
