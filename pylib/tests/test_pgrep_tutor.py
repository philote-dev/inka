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


def test_session_synthesis_ai_off_recap():
    col = getEmptyCol()
    now = int(time.time())
    for i in range(3):
        attempt_log.append_attempt(
            col,
            {
                "event_id": f"s1-{i}",
                "topic": "topic::atomic",
                "correct": i != 0,
                "session_id": "sess-1",
                "answered_at": now,
            },
        )
    res = tutor.session_synthesis(col, "sess-1")
    assert res["ai"] == "off"
    assert res["recap"]["attempted"] == 3
    assert res["recap"]["correct"] == 2
