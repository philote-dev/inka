"""Assemble the PROVISIONAL gold sets for the L4.0 gate.

Gold verification (Frank's rating, E4) is deferred and does NOT block the build
or merge. The keys used here are authoritative: GR9677 keys from the official ETS
omnibus solutions, community-70 keys as given. Every item is written with
``verification.status = "provisional"`` so the human spot-check is visible.

Sources:
  - Problem gold: GR9677 (official ETS keys) plus the 70 community questions,
    filtered to clean 5-choice items with a key, spread across the nine areas.
    (Note: this uses GR9677 as a provisional gold source. The locked allocation
    had GR9677 held-out and GR0877 gold; recorded here for Frank to confirm.)
  - Card gold: no authoritative source exists (PGRE is all MCQ, and the CWRU
    transcription is incomplete), so card anchors are the blueprint finest units.
    The physics-capable judge grades generated cards on their own merits plus the
    cited corpus source. Clearly provisional.

Writes content/gold/problems/*.json and content/gold/cards/*.json. These live in
the private, git-ignored content/ tree and never enter the corpus or a prompt.

Run:
    conda run -n pgrep-ai python content/tools/make_gold.py
"""

from __future__ import annotations

import ast
import json
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
ITEMS_DIR = os.path.join(CONTENT, "tier3-private", "items")
CANDIDATES = os.path.join(CONTENT, "gold", "candidates", "community-70.json")
BLUEPRINT = os.path.join(CONTENT, "blueprint", "blueprint.json")
PROBLEMS_OUT = os.path.join(CONTENT, "gold", "problems")
CARDS_OUT = os.path.join(CONTENT, "gold", "cards")

CHOICE_LETTERS = ("A", "B", "C", "D", "E")

# ETS category name (GR9677 topic_guess) -> blueprint slug.
AREA_NAME_TO_SLUG = {
    "classical mechanics": "mechanics",
    "electromagnetism": "electromagnetism",
    "quantum mechanics": "quantum",
    "thermodynamics and statistical mechanics": "thermodynamics",
    "thermodynamics": "thermodynamics",
    "atomic physics": "atomic",
    "optics and wave phenomena": "optics_waves",
    "special relativity": "special_relativity",
    "laboratory methods": "lab",
    "specialized topics": "specialized",
    "specialized topics in physics": "specialized",
}

# Keyword classifier for items lacking a topic_guess (community-70).
AREA_KEYWORDS = [
    ("special_relativity", ("relativ", "lorentz", "time dilation", "four-vector", "rest frame")),
    ("quantum", ("wavefunction", "schrodinger", "schr\u00f6dinger", "eigenstate", "operator",
                 "spin", "hydrogen", "quantum", "psi", "hbar", "commutator", "perturbation")),
    ("electromagnetism", ("charge", "capacitor", "magnetic", "electric field", "current",
                          "circuit", "gauss", "coulomb", "maxwell", "inductor", "resistor")),
    ("thermodynamics", ("entropy", "carnot", "ideal gas", "temperature", "heat", "partition",
                        "thermodynam", "boltzmann", "adiabatic")),
    ("optics_waves", ("wavelength", "interference", "diffraction", "polariz", "lens", "refract",
                      "double-slit", "doppler")),
    ("atomic", ("photon", "photoelectric", "spectrum", "bohr", "energy level", "x-ray",
                "black-body", "blackbody")),
    ("lab", ("uncertainty", "error", "standard deviation", "measurement", "statistic", "detector")),
    ("mechanics", ("velocity", "acceleration", "momentum", "force", "energy", "orbit", "torque",
                   "oscillat", "pendulum", "lagrangian", "friction", "collision", "rotation")),
]


def _parse_choices(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(c) for c in raw]
    if isinstance(raw, str):
        for parser in (json.loads, ast.literal_eval):
            try:
                val = parser(raw)
                if isinstance(val, list):
                    return [str(c) for c in val]
            except (ValueError, SyntaxError):
                continue
    return []


def _classify(stem: str) -> str:
    text = stem.lower()
    for slug, keys in AREA_KEYWORDS:
        if any(k in text for k in keys):
            return slug
    return "specialized"


def _usable(stem: str, choices: list[str], key: str) -> bool:
    if not stem or len(stem) < 15:
        return False
    if len(choices) != 5 or any(not c.strip() for c in choices):
        return False
    return key in CHOICE_LETTERS


def _gold_problem(item_id: str, stem: str, choices: list[str], key: str, area: str,
                  source: str) -> dict:
    return {
        "id": item_id,
        "schema_version": 1,
        "type": "problem",
        "problem_kind": "conceptual",
        "topic": f"topic::{area}",
        "blueprint_area": area,
        "stem": stem,
        "choices": [
            {"label": lab, "text": choices[i], "is_key": lab == key,
             "misconception_tag": None, "rationale": None}
            for i, lab in enumerate(CHOICE_LETTERS)
        ],
        "key": key,
        "solution_decomposition": [],
        "provenance": {"tier": 3, "source_ref": source},
        "verification": {"status": "provisional", "method": "authoritative key (ETS/community)",
                         "human_spotcheck": "pending (E4)"},
        "leakage_class": "gold",
        "provisional": True,
    }


def _load_gr9677() -> list[dict]:
    path = os.path.join(ITEMS_DIR, "GR9677.json")
    data = json.load(open(path, encoding="utf-8"))
    out = []
    for it in data:
        if it.get("figure_dependent") or it.get("math_garbled"):
            continue
        stem = str(it.get("stem", "")).strip()
        choices = _parse_choices(it.get("choices", []))
        key = str(it.get("key", "")).strip()
        if not _usable(stem, choices, key):
            continue
        area = AREA_NAME_TO_SLUG.get(str(it.get("topic_guess", "")).strip().lower())
        if not area:
            area = _classify(stem)
        out.append(_gold_problem(it.get("id", ""), stem, choices, key, area,
                                 "GR9677 (official ETS key, provisional)"))
    return out


def _load_community() -> list[dict]:
    if not os.path.exists(CANDIDATES):
        return []
    data = json.load(open(CANDIDATES, encoding="utf-8"))
    out = []
    for it in data:
        stem = str(it.get("stem", "")).strip()
        choices = _parse_choices(it.get("choices", []))
        key = str(it.get("key", "")).strip()
        if not _usable(stem, choices, key):
            continue
        out.append(_gold_problem(it.get("id", ""), stem, choices, key, _classify(stem),
                                 "community-70 (key as given, provisional)"))
    return out


def _finest_units() -> list[dict]:
    bp = json.load(open(BLUEPRINT, encoding="utf-8"))
    units = []
    for cat in bp["categories"]:
        for unit in cat["finest_units"]:
            units.append({"slug": unit["slug"], "name": unit["name"], "tag": unit["tag"],
                          "area": cat["slug"], "ets_content": unit.get("ets_content", "")})
    return units


def _write(directory: str, prefix: str, items: list[dict]) -> None:
    os.makedirs(directory, exist_ok=True)
    for old in os.listdir(directory):
        if old.endswith(".json"):
            os.remove(os.path.join(directory, old))
    for i, item in enumerate(items, start=1):
        with open(os.path.join(directory, f"{prefix}-{i:04d}.json"), "w", encoding="utf-8") as fh:
            json.dump(item, fh, indent=2, ensure_ascii=False)


def main() -> None:
    problems = _load_gr9677() + _load_community()
    by_area: dict[str, int] = defaultdict(int)
    for p in problems:
        by_area[p["blueprint_area"]] += 1
    _write(PROBLEMS_OUT, "gold-problem", problems)

    # Card anchors: one per finest unit, judge grades generated cards on merits.
    cards = []
    for i, unit in enumerate(_finest_units(), start=1):
        cards.append({
            "id": f"gold-card-anchor-{i:04d}", "schema_version": 1, "type": "card",
            "card_kind": "conceptual", "topic": unit["tag"], "blueprint_area": unit["area"],
            "front": f"Core idea to test: {unit['name']} ({unit['ets_content']})",
            "back": "", "fact_assertions": [],
            "provenance": {"tier": 1, "source_ref": "blueprint finest unit"},
            "verification": {"status": "provisional",
                             "method": "topic anchor; judge grades on merits + cited source",
                             "human_spotcheck": "pending (E4)"},
            "leakage_class": "gold", "provisional": True})
    _write(CARDS_OUT, "gold-card", cards)

    print(f"problem gold: {len(problems)} items")
    for area, n in sorted(by_area.items()):
        print(f"   {area:18} {n}")
    print(f"card anchors: {len(cards)} finest units")
    print(f"wrote {PROBLEMS_OUT} and {CARDS_OUT}")


if __name__ == "__main__":
    main()
