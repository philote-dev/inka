# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the gated decomposition tutor (WS4).

Covers the stored tutor blob and variant selection, the MCQ gate (which withholds
the key on a wrong pick), the lenient "explain why" grader (AI-off deterministic
plus a light AI-on shape and the giveaway guard), and the renumbered parent
variant used when a missed problem recurs.
"""

from __future__ import annotations

import json

from anki.pgrep import ai_config, decomposition, problem
from anki.pgrep.ai import llm as llm_module
from tests.shared import getEmptyCol

# A compact, self-contained tutor blob: two subproblems (the first with two
# numeric variants, so rotation is observable), plus one renumbered parent.
_TUTOR = {
    "subproblems": [
        {
            "prompt": "Pin the relation.",
            "variants": [
                {
                    "stem": "Variant zero stem",
                    "choices": ["c0", "c1", "c2", "c3", "c4"],
                    "key": "B",
                    "distractor_rationales": {
                        "A": "ra0",
                        "C": "rc0",
                        "D": "rd0",
                        "E": "re0",
                    },
                    "explain_why": "Because the relation is linear.",
                    "source_ref": "OpenStax Vol 1, p. 100",
                },
                {
                    "stem": "Variant one stem",
                    "choices": ["d0", "d1", "d2", "d3", "d4"],
                    "key": "C",
                    "distractor_rationales": {
                        "A": "ra1",
                        "B": "rb1",
                        "D": "rd1",
                        "E": "re1",
                    },
                    "explain_why": "Because the second variant is quadratic.",
                    "source_ref": "OpenStax Vol 1, p. 100",
                },
            ],
        },
        {
            "prompt": "Insert the values.",
            "variants": [
                {
                    "stem": "Second subproblem stem",
                    "choices": ["e0", "e1", "e2", "e3", "e4"],
                    "key": "A",
                    "distractor_rationales": {
                        "B": "x",
                        "C": "x",
                        "D": "x",
                        "E": "x",
                    },
                    "explain_why": "Because A follows from the setup.",
                    "source_ref": "OpenStax Vol 1, p. 101",
                },
            ],
        },
    ],
    "parent_variants": [
        {
            "stem": "Renumbered parent stem",
            "choices": ["p0", "p1", "p2", "p3", "p4"],
            "key": "E",
        }
    ],
}


class _FakeLLM:
    def __init__(self, model, response, **_kw):
        self.model = model
        self._response = response

    def complete_json(self, system, user):
        return dict(self._response)


def _add_problem(col, *, correct="C", tutor=None, correct_text="a specific value"):
    notetype = problem.ensure_problem_notetype(col)
    note = col.new_note(notetype)
    note[problem.FIELD_STEM] = "Parent stem."
    choices = ["w", "x", "y", "z", "q"]
    choices[problem.CHOICE_LETTERS.index(correct)] = correct_text
    note[problem.FIELD_CHOICES] = json.dumps(choices)
    note[problem.FIELD_CORRECT] = correct
    note[problem.FIELD_DISTRACTOR_RATIONALES] = json.dumps({})
    note[problem.FIELD_SOLUTION_DECOMPOSITION] = json.dumps([])
    note[problem.FIELD_DIFFICULTY] = "3.0"
    note[problem.FIELD_SOURCE_REF] = "Parent source"
    note[problem.FIELD_DECOMPOSITION_TUTOR] = json.dumps(tutor or {"subproblems": []})
    note.tags = ["topic::mechanics"]
    col.add_note(note, col.decks.id(problem.PROBLEM_DECK_NAME))
    return int(note.id)


# load_tutor + variant selection
##########################################################################


def test_load_tutor_withholds_key_rationales_and_explanation():
    col = getEmptyCol()
    nid = _add_problem(col, tutor=_TUTOR)

    loaded = decomposition.load_tutor(col, nid, 0)
    assert loaded["count"] == 2
    assert loaded["variant_round"] == 0
    first = loaded["subproblems"][0]
    assert first["index"] == 0
    assert first["variant_index"] == 0
    assert first["prompt"] == "Pin the relation."
    assert first["stem_html"] == "Variant zero stem"
    assert first["choices"] == ["c0", "c1", "c2", "c3", "c4"]
    # The key, rationales and the model explanation are all withheld.
    assert "key" not in first
    assert "distractor_rationales" not in first
    assert "explain_why" not in first


def test_load_tutor_rotates_numeric_variants_by_round():
    col = getEmptyCol()
    nid = _add_problem(col, tutor=_TUTOR)

    # The first subproblem has two variants; the round selects which numbers show.
    assert decomposition.load_tutor(col, nid, 0)["subproblems"][0]["stem_html"] == (
        "Variant zero stem"
    )
    assert decomposition.load_tutor(col, nid, 1)["subproblems"][0]["stem_html"] == (
        "Variant one stem"
    )
    # It wraps: round 2 returns variant 0 again (two variants).
    assert decomposition.load_tutor(col, nid, 2)["subproblems"][0]["variant_index"] == 0
    # The single-variant subproblem always serves variant 0.
    assert decomposition.load_tutor(col, nid, 1)["subproblems"][1]["variant_index"] == 0


def test_has_tutor_true_only_with_usable_subproblems():
    col = getEmptyCol()
    with_tutor = _add_problem(col, tutor=_TUTOR)
    without = _add_problem(col, tutor={"subproblems": []})
    assert decomposition.has_tutor(col, with_tutor) is True
    assert decomposition.has_tutor(col, without) is False


# MCQ gate
##########################################################################


def test_check_mcq_wrong_pick_withholds_the_key():
    col = getEmptyCol()
    nid = _add_problem(col, tutor=_TUTOR)
    # Subproblem 0, variant 0 has key B; pick A.
    res = decomposition.check_mcq(col, nid, 0, 0, "A")
    assert res["correct"] is False
    assert res["rationale_html"] == "ra0"
    # A wrong pick never reveals the correct choice.
    assert "correct_choice" not in res
    assert "key" not in res


def test_check_mcq_correct_pick_reveals_rationale_and_gates_explanation():
    col = getEmptyCol()
    nid = _add_problem(col, tutor=_TUTOR)
    res = decomposition.check_mcq(col, nid, 0, 0, "b")
    assert res["correct"] is True
    assert res["correct_choice"] == "B"
    assert res["explain_why_html"] == "Because the relation is linear."
    # AI off by default, so the explanation gate does not apply.
    assert res["needs_explanation"] is False


def test_check_mcq_needs_explanation_tracks_ai_toggle():
    col = getEmptyCol()
    nid = _add_problem(col, tutor=_TUTOR)
    ai_config.set_ai_enabled(col, True)
    res = decomposition.check_mcq(col, nid, 0, 0, "B")
    assert res["needs_explanation"] is True


# Explanation gate
##########################################################################


def test_grade_explanation_ai_off_passes_without_a_model():
    col = getEmptyCol()
    nid = _add_problem(col, tutor=_TUTOR)
    # AI off: the explanation step is skipped, so a defensive call passes cleanly
    # and never touches the network.
    res = decomposition.grade_explanation(col, nid, 0, 0, "any text")
    assert res["ai"] == "off"
    assert res["pass"] is True
    assert res["explain_why_html"] == "Because the relation is linear."


def test_grade_explanation_ai_on_lenient_pass(monkeypatch):
    col = getEmptyCol()
    nid = _add_problem(col, tutor=_TUTOR)
    ai_config.set_ai_enabled(col, True)
    ai_config.set_ai_model(col, "gpt-x-2026-01-01")
    monkeypatch.setattr(
        llm_module,
        "LLMClient",
        lambda m, **kw: _FakeLLM(m, {"pass": True, "feedback": "Good enough."}),
    )
    res = decomposition.grade_explanation(col, nid, 0, 0, "it is linear")
    assert res["ai"] == "on"
    assert res["pass"] is True
    assert res["feedback"] == "Good enough."
    assert res["explain_why_html"] == "Because the relation is linear."


def test_grade_explanation_ai_on_empty_text_fails_without_a_call(monkeypatch):
    col = getEmptyCol()
    nid = _add_problem(col, tutor=_TUTOR)
    ai_config.set_ai_enabled(col, True)

    def _boom(*_a, **_k):
        raise AssertionError("must not call the model for empty text")

    monkeypatch.setattr(llm_module, "LLMClient", _boom)
    res = decomposition.grade_explanation(col, nid, 0, 0, "   ")
    assert res["pass"] is False


def test_grade_explanation_giveaway_guard_replaces_leaky_feedback(monkeypatch):
    col = getEmptyCol()
    # The parent answer carries a distinctive value the guard can catch.
    nid = _add_problem(col, tutor=_TUTOR, correct="C", correct_text="42.0 joules")
    ai_config.set_ai_enabled(col, True)
    ai_config.set_ai_model(col, "gpt-x-2026-01-01")
    monkeypatch.setattr(
        llm_module,
        "LLMClient",
        lambda m, **kw: _FakeLLM(
            m, {"pass": True, "feedback": "Right, the parent answer is 42.0 joules."}
        ),
    )
    res = decomposition.grade_explanation(col, nid, 0, 0, "some reasoning")
    # The leaking feedback is replaced; the parent value never reaches the learner.
    assert "42" not in res["feedback"]


# Parent variant (re-serve)
##########################################################################


def test_parent_variant_renumbers_only_on_a_reserve():
    col = getEmptyCol()
    nid = _add_problem(col, tutor=_TUTOR)
    # Round 0 is the base serving, so no renumbered stem.
    assert decomposition.parent_variant(col, nid, 0) is None
    variant = decomposition.parent_variant(col, nid, 1)
    assert variant is not None
    assert variant["stem"] == "Renumbered parent stem"
    assert variant["key"] == "E"
    assert len(variant["choices"]) == 5
