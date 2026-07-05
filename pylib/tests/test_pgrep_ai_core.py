# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the shared pgrep AI core (L4.0f), the Collection-free layer.

These cover the parts that need no heavy deps and no model, so they run under
``just test-py`` in the app env with AI off: dedup, the giveaway verifier,
provenance cite-or-refuse, and generation orchestration with a fake LLM. The
CAS test skips when SymPy is absent (AI off), proving the import stays lazy.
"""

from __future__ import annotations

import pytest

from anki.pgrep.ai import generation_core as gc
from anki.pgrep.ai import provenance, verify

_GROUNDED = [
    {
        "score": 0.82,
        "text": "The photon energy is E = h c / lambda, with hc about 1240 eV nm.",
        "source_ref": "OpenStax University Physics Volume 3, p. 254",
        "chunk_id": "openstax-vol3#p0254#c001",
        "source_title": "OpenStax University Physics Volume 3",
    },
]
_UNGROUNDED = [
    {
        "score": 0.30,
        "text": "An unrelated passage about ocean tides.",
        "source_ref": "OpenStax Vol 1, p. 10",
        "chunk_id": "x",
        "source_title": "OpenStax Vol 1",
    }
]


class _FakeLLM:
    model = "fake-llm"

    def __init__(self, response: dict):
        self.response = response

    def complete_json(self, system: str, user: str) -> dict:
        return dict(self.response)


def test_dedup_normalizes_case_and_spacing():
    h1 = verify.normalized_front_hash("What is angular momentum?")
    h2 = verify.normalized_front_hash("what   is  angular  momentum ?")
    assert h1 == h2
    assert verify.is_duplicate("What is angular momentum?", {h2})


def test_giveaway_verifier_flags_leaks():
    assert verify.giveaway_safe("Think about the kind of problem.", "45 m")
    assert not verify.giveaway_safe("The answer is 45 m.", "45 m")
    assert not verify.giveaway_safe("It falls 45 meters.", "45 m")  # decisive number
    assert verify.find_giveaway("Use kinematics from rest.", "45 m") is None


def test_provenance_cite_or_refuse():
    ok = provenance.cite_or_refuse(
        {"back": "E = hc / lambda"}, _GROUNDED, claim_key="back"
    )
    assert not ok["refused"] and ok["source_ref"]
    bad = provenance.cite_or_refuse(
        {"back": "E = hc / lambda"}, _UNGROUNDED, claim_key="back"
    )
    assert bad["refused"] and bad["source_ref"] is None


def test_generate_card_grounded_and_confident():
    llm = _FakeLLM(
        {
            "front": "Photon energy for a wavelength?",
            "back": "E = h c / lambda with hc = 1240 eV nm.",
            "card_kind": "conceptual",
            "difficulty": 0.4,
            "confidence": 0.9,
            "computational": None,
            "refuse": False,
        }
    )
    card = gc.generate_card(topic="topic::atomic", retrieved=_GROUNDED, llm=llm)
    assert not card["refused"]
    assert not card["needs_review"]
    assert card["source_ref"]


def test_generate_card_low_confidence_routes_to_review():
    llm = _FakeLLM(
        {
            "front": "x",
            "back": "E = h c / lambda",
            "card_kind": "conceptual",
            "difficulty": 0.4,
            "confidence": 0.3,
            "computational": None,
            "refuse": False,
        }
    )
    card = gc.generate_card(topic="topic::atomic", retrieved=_GROUNDED, llm=llm)
    assert card["needs_review"]


def test_generate_card_ungrounded_refuses():
    llm = _FakeLLM(
        {
            "front": "q",
            "back": "E = h c / lambda",
            "card_kind": "conceptual",
            "difficulty": 0.4,
            "confidence": 0.9,
            "computational": None,
            "refuse": False,
        }
    )
    card = gc.generate_card(topic="topic::atomic", retrieved=_UNGROUNDED, llm=llm)
    assert card["refused"]


def _good_problem_response() -> dict:
    return {
        "stem": "A 500 nm photon has energy closest to (hc = 1240 eV nm)?",
        "choices": ["0.40 eV", "1.24 eV", "2.48 eV", "4.96 eV", "620 eV"],
        "key": "C",
        "distractors": [
            {
                "label": "A",
                "misconception_tag": "inverted-ratio",
                "rationale": "lambda over hc",
            },
            {
                "label": "B",
                "misconception_tag": "wrong-wavelength",
                "rationale": "used 1000 nm",
            },
            {
                "label": "D",
                "misconception_tag": "halved-wavelength",
                "rationale": "used 250 nm",
            },
            {
                "label": "E",
                "misconception_tag": "multiplied",
                "rationale": "multiplied hc by lambda",
            },
        ],
        "solution_decomposition": [
            {"subgoal": "Pick the relation", "rubric": "writes E = hc/lambda"}
        ],
        "problem_kind": "conceptual",
        "difficulty": 0.5,
        "confidence": 0.85,
        "computational": None,
        "refuse": False,
    }


def test_generate_problem_misconception_first():
    prob = gc.generate_problem(
        topic="topic::atomic",
        retrieved=_GROUNDED,
        llm=_FakeLLM(_good_problem_response()),
    )
    assert not prob["refused"] and not prob["needs_review"]
    assert prob["distractor_rationales"].get("A")


def test_generate_problem_giveaway_in_decomposition_refused():
    resp = _good_problem_response()
    resp["solution_decomposition"] = [
        {"subgoal": "Compute", "rubric": "the answer is 2.48 eV"}
    ]
    prob = gc.generate_problem(
        topic="topic::atomic", retrieved=_GROUNDED, llm=_FakeLLM(resp)
    )
    assert prob["refused"]


class _SeqLLM:
    """Fake that answers the generate call and the independent-solve call."""

    model = "fake-seq"

    def __init__(self, gen_resp: dict, solve_answer: str):
        self.gen_resp = gen_resp
        self.solve_answer = solve_answer

    def complete_json(self, system: str, user: str) -> dict:
        if system == gc.PROBLEM_SOLVE_SYSTEM:
            return {"answer": self.solve_answer}
        return dict(self.gen_resp)


def test_generate_problem_key_self_consistent_accepts():
    llm = _SeqLLM(_good_problem_response(), solve_answer="C")  # matches key C
    prob = gc.generate_problem(
        topic="topic::atomic", retrieved=_GROUNDED, llm=llm, verify_key=True, attempts=3
    )
    assert prob["key_self_consistent"] is True
    assert not prob["needs_review"]


def test_generate_problem_key_disagreement_flags_review():
    llm = _SeqLLM(_good_problem_response(), solve_answer="D")  # disagrees with key C
    prob = gc.generate_problem(
        topic="topic::atomic", retrieved=_GROUNDED, llm=llm, verify_key=True, attempts=3
    )
    assert prob["key_self_consistent"] is False
    assert prob["needs_review"]
    assert "independent solve" in prob["review_reason"]


def test_cas_check_when_sympy_available():
    pytest.importorskip("sympy")
    assert verify.cas_equivalent("2*x + x", "3*x")
    assert verify.cas_check_value("1240/500", 2.48, tolerance=1e-2)
