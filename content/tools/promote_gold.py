"""Assemble the problem gold set from the CLEAN candidates.

Supersedes the problem-gold path in make_gold.py, which promoted the raw OCR
(tier3-private/items/GR9677.json) and let garbled stems through (for example
"Fy (B) Fs (C) Fc"). This reads the vision-cleaned, annotated candidate
(gr9677-problem-gold.json) and the community 70, normalizes both to the
gold-problem shape, and writes one file per item into content/gold/problems/.

GR9677 items arrive fully drafted: clean LaTeX stem, misconception-tagged
distractors with rationales, and a solution decomposition. They are marked
pending-frank (drafts awaiting the human rating pass, E4).

Community items arrive with a clean stem and a key but no distractor
annotations. They are marked pending-annotation and enriched later by
annotate_community.py before the rating pass.

Card gold is handled by author_card_gold.py, not here. This script never touches
content/gold/cards/.

No network. Run:
    python content/tools/promote_gold.py
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
GR9677_CANDIDATE = os.path.join(CONTENT, "gold", "candidates", "gr9677-problem-gold.json")
COMMUNITY_CANDIDATE = os.path.join(CONTENT, "gold", "candidates", "community-70.json")
PROBLEMS_OUT = os.path.join(CONTENT, "gold", "problems")

CHOICE_LETTERS = ("A", "B", "C", "D", "E")

# The nine stable blueprint-area slugs (gold-problem.schema.json enum).
AREA_ENUM = {
    "mechanics", "electromagnetism", "quantum", "thermo-stat-mech", "atomic",
    "optics-waves", "special-relativity", "lab-methods", "specialized",
}

# Map any looser area label onto the schema enum.
AREA_ALIAS = {
    "thermodynamics": "thermo-stat-mech",
    "thermo": "thermo-stat-mech",
    "thermodynamics-stat-mech": "thermo-stat-mech",
    "optics_waves": "optics-waves",
    "optics": "optics-waves",
    "waves": "optics-waves",
    "special_relativity": "special-relativity",
    "relativity": "special-relativity",
    "lab": "lab-methods",
    "laboratory": "lab-methods",
    "lab_methods": "lab-methods",
}

# Keyword classifier for community items, which carry no area label.
AREA_KEYWORDS = [
    ("special-relativity", ("relativ", "lorentz", "time dilation", "four-vector", "rest frame", "proper time")),
    ("quantum", ("wavefunction", "schrodinger", "schr\u00f6dinger", "eigenstate", "operator", "hermitian",
                 "spin", "hydrogen atom", "quantum", "\\psi", "hbar", "commutator", "perturbation", "unitary")),
    ("electromagnetism", ("charge", "capacitor", "magnetic", "electric field", "current",
                          "circuit", "gauss", "coulomb", "maxwell", "inductor", "resistor", "dipole")),
    ("thermo-stat-mech", ("entropy", "carnot", "ideal gas", "temperature", "heat", "partition function",
                          "thermodynam", "boltzmann", "adiabatic", "isotherm")),
    ("optics-waves", ("wavelength", "interference", "diffraction", "polariz", "lens", "refract",
                      "double-slit", "double slit", "grating", "doppler", "standing wave")),
    ("atomic", ("photon", "photoelectric", "spectrum", "spectral", "bohr", "energy level", "x-ray",
                "black-body", "blackbody", "emission line")),
    ("lab-methods", ("uncertainty", "standard deviation", "measurement error", "propagation of error",
                     "detector", "counting statistics")),
    ("mechanics", ("velocity", "acceleration", "momentum", "force", "kinetic energy", "orbit", "torque",
                   "oscillat", "pendulum", "lagrangian", "friction", "collision", "rotation", "spring")),
]

COMPUTATIONAL_HINTS = ("calculate", "compute", "what is the value", "find the", "how much",
                       "magnitude of", "how fast", "how far", "determine the")


def _norm_area(label: str) -> str:
    label = (label or "").strip().lower().replace(" ", "-")
    if label in AREA_ENUM:
        return label
    return AREA_ALIAS.get(label, "")


def _classify_area(stem: str) -> str:
    text = (stem or "").lower()
    for slug, keys in AREA_KEYWORDS:
        if any(k in text for k in keys):
            return slug
    return "specialized"


def _kind(stem: str) -> str:
    text = (stem or "").lower()
    if any(h in text for h in COMPUTATIONAL_HINTS) and re.search(r"\d", text):
        return "computational"
    return "conceptual"


def _topic_obj(raw, area: str) -> dict:
    if isinstance(raw, dict) and raw.get("category") and raw.get("subtopic"):
        return {"category": str(raw["category"]), "subtopic": str(raw["subtopic"])}
    return {"category": area, "subtopic": area}


def _parse_choices(raw) -> list:
    if isinstance(raw, list):
        return raw
    return []


def _promote_gr9677() -> list[dict]:
    data = json.load(open(GR9677_CANDIDATE, encoding="utf-8"))
    out = []
    for it in data:
        area = _norm_area(it.get("blueprint_area", "")) or _classify_area(it.get("stem", ""))
        choices_in = _parse_choices(it.get("choices", []))
        if len(choices_in) != 5:
            continue
        choices = []
        for i, lab in enumerate(CHOICE_LETTERS):
            c = choices_in[i]
            entry = {
                "label": lab,
                "text": str(c.get("text", "")).strip(),
                "is_key": bool(c.get("is_key")),
                "rationale": str(c.get("rationale", "")).strip() or "pending",
            }
            if not entry["is_key"]:
                entry["misconception_tag"] = str(c.get("misconception_tag", "")).strip() or "unspecified"
            choices.append(entry)
        prov = it.get("provenance", {}) or {}
        src = prov.get("source_ref", {}) or {}
        out.append({
            "id": "PLACEHOLDER",
            "schema_version": "1.0.0",
            "type": "problem",
            "problem_kind": it.get("problem_kind", "conceptual"),
            "topic": _topic_obj(it.get("topic"), area),
            "blueprint_area": area,
            "stem": str(it.get("stem", "")).strip(),
            "choices": choices,
            "key": str(it.get("key", "")).strip(),
            "solution_decomposition": it.get("solution_decomposition", []) or [],
            "provenance": {
                "tier": 3,
                "source_ref": {
                    "title": str(src.get("title") or "GRE Physics Test, form GR9677 (ETS)"),
                    "section": str(src.get("section") or "GR9677"),
                    "edition": str(src.get("edition") or "GR9677"),
                    "quote_anchor": str(src.get("quote_anchor") or it.get("stem", ""))[:180],
                },
            },
            "verification": {
                "status": "pending-frank",
                "method_draft": ["source-checked", "cas-checked"] if it.get("problem_kind") == "computational" else ["source-checked"],
                "note": "GR9677 vision-cleaned; key from ETS/Omnibus; distractor rationales and decomposition are LLM drafts. Frank verifies before promotion to verified.",
            },
            "leakage_class": "gold",
            "notes": f"source_id={it.get('id', '')}; GR9677 ETS Tier-3, gold eval only, never fed or indexed.",
        })
    return out


def _promote_community() -> list[dict]:
    data = json.load(open(COMMUNITY_CANDIDATE, encoding="utf-8"))
    out = []
    for it in data:
        key = str(it.get("key", "")).strip()
        stem = str(it.get("stem", "")).strip()
        choices_in = _parse_choices(it.get("choices", []))
        if key not in CHOICE_LETTERS or len(choices_in) != 5 or len(stem) < 15:
            continue
        area = _classify_area(stem)
        choices = []
        for i, lab in enumerate(CHOICE_LETTERS):
            entry = {
                "label": lab,
                "text": str(choices_in[i]).strip(),
                "is_key": lab == key,
                "rationale": "pending",
            }
            if lab != key:
                entry["misconception_tag"] = "pending"
            choices.append(entry)
        out.append({
            "id": "PLACEHOLDER",
            "schema_version": "1.0.0",
            "type": "problem",
            "problem_kind": _kind(stem),
            "topic": {"category": area, "subtopic": area},
            "blueprint_area": area,
            "stem": stem,
            "choices": choices,
            "key": key,
            "solution_decomposition": [],
            "provenance": {
                "tier": 3,
                "source_ref": {
                    "title": "physicsgre.com user-created 70-question sample",
                    "section": f"Question {it.get('number', '?')}",
                    "url": "https://www.physicsgre.com",
                },
            },
            "verification": {
                "status": "pending-annotation",
                "method_draft": ["source-checked"],
                "note": "Community key as given. Distractor misconception tags, rationales, and the solution decomposition still need authoring (annotate_community.py), then Frank verifies.",
            },
            "leakage_class": "gold",
            "notes": f"source_id={it.get('id', '')}; community 70 sample, gold eval only, never fed or indexed.",
        })
    return out


def _write(items: list[dict]) -> None:
    os.makedirs(PROBLEMS_OUT, exist_ok=True)
    for old in os.listdir(PROBLEMS_OUT):
        if old.endswith(".json"):
            os.remove(os.path.join(PROBLEMS_OUT, old))
    for i, item in enumerate(items, start=1):
        item["id"] = f"gold-problem-{i:04d}"
        with open(os.path.join(PROBLEMS_OUT, f"gold-problem-{i:04d}.json"), "w", encoding="utf-8") as fh:
            json.dump(item, fh, indent=2, ensure_ascii=False)


def main() -> None:
    gr = _promote_gr9677()
    com = _promote_community()
    items = gr + com
    _write(items)

    by_area: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    for p in items:
        by_area[p["blueprint_area"]] += 1
        by_status[p["verification"]["status"]] += 1

    print(f"problem gold written: {len(items)}  (GR9677 {len(gr)} + community {len(com)})")
    print("by status:")
    for s, n in sorted(by_status.items()):
        print(f"   {s:20} {n}")
    print("by area:")
    for area, n in sorted(by_area.items()):
        print(f"   {area:20} {n}")
    print(f"wrote {PROBLEMS_OUT}")


if __name__ == "__main__":
    main()
