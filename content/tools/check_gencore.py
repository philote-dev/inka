"""Offline checks for the generation plumbing core (L4.0f).

Exercises the shared core without the OpenAI API by injecting a fake LLM:
CAS (symbolic and numeric), the giveaway verifier, dedup, provenance
cite-or-refuse, and the confidence route. Proves the plumbing is correct before
any graded generation, and that AI-off imports never need the heavy deps.

Run:
    conda run -n pgrep-ai python content/tools/check_gencore.py
"""

from __future__ import annotations

import sys

import _ai_path

_ai_path.add_ai_core()

from pgrep.ai import generation_core as gc  # noqa: E402
from pgrep.ai import provenance, verify  # noqa: E402


class FakeLLM:
    model = "fake-llm"

    def __init__(self, response: dict):
        self.response = response

    def complete_json(self, system: str, user: str) -> dict:
        return dict(self.response)


GROUNDED = [
    {"score": 0.82, "text": "The photon energy is E = h c / lambda. With hc about "
     "1240 eV nm and lambda in nm, the energy is in eV.",
     "source_ref": "OpenStax University Physics Volume 3, p. 254, 6.2 Photoelectric Effect",
     "chunk_id": "openstax-vol3#p0254#c001", "source_title": "OpenStax University Physics Volume 3"},
    {"score": 0.61, "text": "Photoelectrons are emitted when light exceeds the work function.",
     "source_ref": "OpenStax University Physics Volume 3, p. 255",
     "chunk_id": "openstax-vol3#p0255#c002", "source_title": "OpenStax University Physics Volume 3"},
]
UNGROUNDED = [{"score": 0.30, "text": "Unrelated passage about tides.",
               "source_ref": "OpenStax Vol 1, p. 10", "chunk_id": "x", "source_title": "OpenStax"}]


def check_verify() -> None:
    assert verify.cas_equivalent("2*x + x", "3*x")
    assert not verify.cas_equivalent("x + 1", "x + 2")
    assert verify.cas_check_value("1240/500", 2.48, tolerance=1e-2)
    assert not verify.cas_check_value("1240/500", 9.9, tolerance=1e-2)
    assert verify.giveaway_safe("Think about what kind of problem this is.", "45 m")
    assert not verify.giveaway_safe("The answer is 45 m.", "45 m")
    assert not verify.giveaway_safe("Recall that it falls 45 meters.", "45 m")
    assert verify.find_giveaway("Use kinematics with g and t.", "45 m") is None
    h1 = verify.normalized_front_hash("What is angular momentum?")
    h2 = verify.normalized_front_hash("what   is   angular momentum ?")
    assert h1 == h2, "dedup normalization should ignore case and spacing"
    assert verify.is_duplicate("What is angular momentum?", {h2})
    print("[verify]  CAS, giveaway, dedup  ok")


def check_provenance() -> None:
    prov = provenance.best_support("photon energy hc over lambda", GROUNDED)
    assert prov is not None and "OpenStax" in prov.source_ref
    item = provenance.cite_or_refuse({"back": "E = hc/lambda"}, GROUNDED, claim_key="back")
    assert not item["refused"] and item["source_ref"]
    refused = provenance.cite_or_refuse({"back": "E = hc/lambda"}, UNGROUNDED, claim_key="back")
    assert refused["refused"] and refused["source_ref"] is None
    print("[provenance]  cite-or-refuse  ok")


def check_generation() -> None:
    good_card = FakeLLM({"front": "Photon energy for a wavelength?",
                         "back": "E = h c / lambda; with hc = 1240 eV nm and lambda in nm.",
                         "card_kind": "conceptual", "difficulty": 0.4, "confidence": 0.9,
                         "computational": None, "refuse": False})
    card = gc.generate_card(topic="topic::atomic", retrieved=GROUNDED, llm=good_card)
    assert not card["refused"] and not card["needs_review"] and card["source_ref"]

    low_conf = FakeLLM({"front": "x", "back": "E = h c / lambda", "card_kind": "conceptual",
                        "difficulty": 0.4, "confidence": 0.3, "computational": None, "refuse": False})
    card2 = gc.generate_card(topic="topic::atomic", retrieved=GROUNDED, llm=low_conf)
    assert card2["needs_review"], "low confidence must route to human review"

    refuse_card = FakeLLM({"refuse": True, "confidence": 0.1})
    card3 = gc.generate_card(topic="topic::atomic", retrieved=GROUNDED, llm=refuse_card)
    assert card3["refused"]

    ungrounded_card = gc.generate_card(topic="topic::atomic", retrieved=UNGROUNDED, llm=good_card)
    assert ungrounded_card["refused"], "no grounding must refuse"

    good_problem = FakeLLM({
        "stem": "A 500 nm photon has energy closest to (hc = 1240 eV nm)?",
        "choices": ["0.40 eV", "1.24 eV", "2.48 eV", "4.96 eV", "620 eV"],
        "key": "C",
        "distractors": [
            {"label": "A", "misconception_tag": "inverted-ratio", "rationale": "computed lambda over hc"},
            {"label": "B", "misconception_tag": "wrong-wavelength", "rationale": "used 1000 nm"},
            {"label": "D", "misconception_tag": "halved-wavelength", "rationale": "used 250 nm"},
            {"label": "E", "misconception_tag": "multiplied", "rationale": "multiplied hc by lambda"}],
        "solution_decomposition": [
            {"subgoal": "Pick the relation", "rubric": "writes E = hc/lambda"},
            {"subgoal": "Insert values", "rubric": "uses hc = 1240 eV nm with lambda in nm"}],
        "problem_kind": "computational", "difficulty": 0.5, "confidence": 0.85,
        "computational": {"expression": "1240/500", "expected": 2.48, "tolerance": 0.05},
        "refuse": False})
    prob = gc.generate_problem(topic="topic::atomic", retrieved=GROUNDED, llm=good_problem)
    assert not prob["refused"] and not prob["needs_review"]
    assert prob["distractor_rationales"].get("A") and prob.get("cas_verified")

    leaky = dict(good_problem.response)
    leaky["solution_decomposition"] = [{"subgoal": "Compute", "rubric": "the answer is 2.48 eV"}]
    prob2 = gc.generate_problem(topic="topic::atomic", retrieved=GROUNDED, llm=FakeLLM(leaky))
    assert prob2["refused"], "a decomposition that leaks the key must be refused"
    print("[generation]  card + problem, grounding + confidence + giveaway  ok")


def main() -> None:
    check_verify()
    check_provenance()
    check_generation()
    print("\nAll generation-core checks passed.")


if __name__ == "__main__":
    main()
