# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for misconception-first problem generation (L4.2).

Covers AI-off (no generation, the curated pool stands) and AI-on with retrieval
and the LLM faked, so a generated MCQ lands as a ``pgrep::Problem`` note with its
stored decomposition and per-distractor rationales, no heavy deps needed.
"""

from __future__ import annotations

import json

from anki.pgrep import ai_config, problem, problem_gen
from anki.pgrep.ai import llm as llm_module
from tests.shared import getEmptyCol

_GROUNDED = [
    {"score": 0.80,
     "text": "A photon of wavelength lambda has energy E = h c / lambda.",
     "source_ref": "OpenStax University Physics Volume 3, p. 254",
     "chunk_id": "openstax-vol3#p0254#c001",
     "source_title": "OpenStax University Physics Volume 3"}]


def _good_problem() -> dict:
    return {
        "stem": "A 500 nm photon has energy closest to (hc = 1240 eV nm)?",
        "choices": ["0.40 eV", "1.24 eV", "2.48 eV", "4.96 eV", "620 eV"],
        "key": "C",
        "distractors": [
            {"label": "A", "misconception_tag": "inverted-ratio", "rationale": "lambda over hc"},
            {"label": "B", "misconception_tag": "wrong-wavelength", "rationale": "used 1000 nm"},
            {"label": "D", "misconception_tag": "halved-wavelength", "rationale": "used 250 nm"},
            {"label": "E", "misconception_tag": "multiplied", "rationale": "multiplied hc by lambda"}],
        "solution_decomposition": [
            {"subgoal": "Pick the relation", "rubric": "writes E = hc/lambda"},
            {"subgoal": "Insert values", "rubric": "uses hc = 1240 eV nm with lambda in nm"}],
        "problem_kind": "conceptual", "difficulty": 0.5, "confidence": 0.85,
        "computational": None, "refuse": False}


class _FakeLLM:
    def __init__(self, model, response=None, **_kw):
        self.model = model
        self._response = response or _good_problem()

    def complete_json(self, system, user):
        return dict(self._response)


def _enable_ai(col):
    ai_config.set_ai_enabled(col, True)
    ai_config.set_ai_model(col, "gpt-x-2026-01-01")


def test_problem_gen_ai_off():
    col = getEmptyCol()
    res = problem_gen.generate(col, topic="topic::atomic", n=1)
    assert res["ai"] == "off"
    assert res["added"] == []


def test_problem_gen_ai_on_adds_problem(monkeypatch):
    col = getEmptyCol()
    _enable_ai(col)
    monkeypatch.setattr(problem_gen, "_retrieve", lambda col, query: list(_GROUNDED))
    monkeypatch.setattr(llm_module, "LLMClient", _FakeLLM)

    res = problem_gen.generate(col, topic="topic::atomic", n=1)
    assert res["ai"] == "on"
    assert len(res["added"]) == 1
    note = col.get_note(res["added"][0]["note_id"])
    assert note[problem.FIELD_CORRECT] == "C"
    decomposition = json.loads(note[problem.FIELD_SOLUTION_DECOMPOSITION])
    assert decomposition and decomposition[0]["subgoal"]
    rationales = json.loads(note[problem.FIELD_DISTRACTOR_RATIONALES])
    assert rationales.get("A")
    assert problem_gen.GENERATED_TAG in note.tags
    assert "topic::atomic" in note.tags


def test_problem_gen_giveaway_in_decomposition_refused(monkeypatch):
    col = getEmptyCol()
    _enable_ai(col)
    leaky = _good_problem()
    leaky["solution_decomposition"] = [{"subgoal": "Compute", "rubric": "the answer is 2.48 eV"}]
    monkeypatch.setattr(problem_gen, "_retrieve", lambda col, query: list(_GROUNDED))
    monkeypatch.setattr(llm_module, "LLMClient", lambda model, **kw: _FakeLLM(model, response=leaky))

    res = problem_gen.generate(col, topic="topic::atomic", n=1)
    assert res["added"] == []
    assert len(res["refused"]) == 1
