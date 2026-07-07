"""A tiny self-generated smoke batch to exercise the scorer end to end (L4.0e).

This is NOT the graded batch. It fabricates a handful of gold items and, for each,
candidate items from four systems (ai, keyword, vector, naive), grounding the AI
and baseline candidates in real corpus source refs from the built index. It lets
``score_batch.py --smoke`` prove the whole pipeline runs (metrics, CIs, per-area,
beat-baseline, kappa, manifest) offline, before Frank's gold sets land.

The gold content here is illustrative, kept out of the real ``content/gold/``
directories. The scored batch uses the real gold sets, never this fixture.
"""

from __future__ import annotations

import os

from baselines import KeywordBaseline, VectorBaseline, candidate

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
DEFAULT_DB = os.path.join(CONTENT, "index", "corpus.db")

# Illustrative gold cards (front, back, area). Facts are standard PGRE physics.
_GOLD_CARDS = [
    ("smoke-card-mech", "mechanics", "topic::mechanics::rotation",
     "For a mass m at radius r moving at speed v, what is its angular momentum about the axis?",
     "L = m v r for circular motion; in general L = r x p."),
    ("smoke-card-em", "electromagnetism", "topic::electromagnetism::electrostatics",
     "State Gauss's law in integral form.",
     "The flux of E through a closed surface equals the enclosed charge over epsilon-zero."),
    ("smoke-card-quantum", "quantum", "topic::quantum::schrodinger_solutions",
     "What are the energy levels of a 1D infinite square well of width L?",
     "E_n = n^2 pi^2 hbar^2 / (2 m L^2), n = 1, 2, 3, ..."),
    ("smoke-card-thermo", "thermodynamics", "topic::thermodynamics",
     "What is the efficiency of a Carnot engine between hot and cold reservoirs?",
     "eta = 1 - T_c / T_h with absolute temperatures."),
    ("smoke-card-atomic", "atomic", "topic::atomic",
     "Give the photon energy for wavelength lambda using hc = 1240 eV nm.",
     "E = hc / lambda; with hc = 1240 eV nm and lambda in nm the answer is in eV."),
    ("smoke-card-optics", "optics_waves", "topic::optics_waves",
     "State the double-slit condition for bright fringes.",
     "d sin theta = m lambda for integer m."),
]

# Illustrative gold problems (stem, choices A-E, key letter, area).
_GOLD_PROBLEMS = [
    ("smoke-prob-mech", "mechanics", "topic::mechanics::dynamics_energy",
     "A ball is dropped from rest and falls for 3.0 s with g = 10 m/s^2. How far does it fall?",
     ["5 m", "15 m", "30 m", "45 m", "90 m"], "D"),
    ("smoke-prob-em", "electromagnetism", "topic::electromagnetism::electrostatics",
     "Two 2 uC charges are 1.0 m apart in vacuum (k = 9e9). The force magnitude is closest to",
     ["0.018 N", "0.036 N", "0.072 N", "3.6 N", "36 N"], "B"),
    ("smoke-prob-quantum", "quantum", "topic::quantum::schrodinger_solutions",
     "An electron in a 1D infinite well has ground energy E1. The n = 3 level energy is",
     ["3 E1", "4 E1", "6 E1", "9 E1", "27 E1"], "D"),
    ("smoke-prob-thermo", "thermodynamics", "topic::thermodynamics",
     "A Carnot engine runs between 400 K and 300 K. Its maximum efficiency is closest to",
     ["25%", "33%", "57%", "75%", "133%"], "A"),
]


def build(db: str = DEFAULT_DB) -> tuple[dict, list[dict]]:
    """Return (gold_by_id, candidate_items) for the smoke batch."""
    kb = KeywordBaseline(db)
    vb = VectorBaseline(db)
    gold: dict[str, dict] = {}
    candidates: list[dict] = []
    try:
        for cid, area, topic, front, back in _GOLD_CARDS:
            gold[cid] = {"id": cid, "type": "card", "blueprint_area": area, "topic": topic,
                         "front": front, "back": back,
                         "fact_assertions": [{"text": back, "must_hold": True}]}
            target = {"id": cid, "query": front, "kind": "card",
                      "blueprint_area": area, "topic": topic}
            top = vb.top(front, 1)
            src = top[0]["source_ref"] if top else "corpus"
            candidates.append({"system": "ai", "target_id": cid, "kind": "card",
                               "blueprint_area": area, "topic": topic, "refused": False,
                               "front": front, "back": back, "source_ref": src})
            candidates.append(candidate(kb, target))
            candidates.append(candidate(vb, target))

        for pid, area, topic, stem, choices, key in _GOLD_PROBLEMS:
            gold[pid] = {"id": pid, "type": "problem", "blueprint_area": area, "topic": topic,
                         "stem": stem, "choices": choices, "key": key}
            target = {"id": pid, "query": stem, "kind": "problem",
                      "blueprint_area": area, "topic": topic}
            top = vb.top(stem, 1)
            src = top[0]["source_ref"] if top else "corpus"
            rationales = {c: f"trap for choice {c}" for c in ("A", "B", "C", "D", "E") if c != key}
            candidates.append({"system": "ai", "target_id": pid, "kind": "problem",
                               "blueprint_area": area, "topic": topic, "refused": False,
                               "stem": stem, "choices": choices, "key": key,
                               "distractor_rationales": rationales, "source_ref": src})
            # naive: choices but no misconception rationales.
            candidates.append({"system": "naive", "target_id": pid, "kind": "problem",
                               "blueprint_area": area, "topic": topic, "refused": False,
                               "stem": stem, "choices": choices, "key": key,
                               "distractor_rationales": {}, "source_ref": src})
            # retrieval baselines return a raw passage (no MCQ structure).
            candidates.append(candidate(kb, target))
            candidates.append(candidate(vb, target))
    finally:
        kb.close()
        vb.close()
    return gold, candidates
