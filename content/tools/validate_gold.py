"""Validate the gold sets before the rating pass and the graded run.

Checks structural integrity (the shape the loader and the schema expect) and
flags any leftover draft placeholders ("pending") that slipped through, plus the
key-agreement status so the rating sheet knows what needs a human key check.
Read-only. Run:
    python content/tools/validate_gold.py
"""

from __future__ import annotations

import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
PROBLEMS = os.path.join(CONTENT, "gold", "problems")
CARDS = os.path.join(CONTENT, "gold", "cards")

AREAS = {"mechanics", "electromagnetism", "quantum", "thermo-stat-mech", "atomic",
         "optics-waves", "special-relativity", "lab-methods", "specialized"}
PLACEHOLDER = {"pending", "PENDING", "unspecified", ""}


def _load(directory: str) -> list[tuple[str, dict]]:
    out = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            out.append((name, json.load(open(os.path.join(directory, name), encoding="utf-8"))))
    return out


def check_problem(name: str, it: dict) -> list[str]:
    errs = []
    if it.get("blueprint_area") not in AREAS:
        errs.append(f"bad blueprint_area {it.get('blueprint_area')!r}")
    ch = it.get("choices", [])
    if len(ch) != 5:
        errs.append(f"{len(ch)} choices (need 5)")
    n_key = sum(1 for c in ch if c.get("is_key"))
    if n_key != 1:
        errs.append(f"{n_key} choices flagged is_key (need 1)")
    if ch and it.get("key") not in {c["label"] for c in ch if c.get("is_key")}:
        errs.append(f"key {it.get('key')!r} does not match the is_key choice")
    for c in ch:
        if (c.get("rationale") or "").strip() in PLACEHOLDER:
            errs.append(f"choice {c.get('label')} rationale is placeholder")
        if not c.get("is_key") and (c.get("misconception_tag") or "").strip() in PLACEHOLDER:
            errs.append(f"choice {c.get('label')} misconception_tag is placeholder")
    dec = it.get("solution_decomposition", [])
    if not dec or any((s.get("subgoal") or "").strip() in PLACEHOLDER for s in dec):
        errs.append("solution_decomposition missing or placeholder")
    if not (it.get("stem") or "").strip():
        errs.append("empty stem")
    return errs


def check_card(name: str, it: dict) -> list[str]:
    errs = []
    if it.get("blueprint_area") not in AREAS:
        errs.append(f"bad blueprint_area {it.get('blueprint_area')!r}")
    if (it.get("front") or "").strip() in PLACEHOLDER:
        errs.append("front is placeholder")
    if (it.get("back") or "").strip() in PLACEHOLDER:
        errs.append("back is placeholder")
    fa = it.get("fact_assertions", [])
    if not fa or any((f.get("claim") or "").strip() in PLACEHOLDER for f in fa):
        errs.append("fact_assertions missing or placeholder")
    if it.get("card_kind") == "computational" and not it.get("computational"):
        errs.append("computational card without a computational block")
    return errs


def report(kind: str, directory: str, checker) -> None:
    items = _load(directory)
    status = Counter(it.get("verification", {}).get("status", "?") for _n, it in items)
    area = Counter(it.get("blueprint_area", "?") for _n, it in items)
    bad = [(n, checker(n, it)) for n, it in items]
    bad = [(n, e) for n, e in bad if e]
    print(f"\n=== {kind} gold: {len(items)} items ===")
    print("status:", dict(status))
    print("areas :", dict(sorted(area.items())))
    if kind == "problem":
        need_key = [n for n, it in items if it.get("verification", {}).get("status") == "needs-frank-key"]
        print(f"needs-frank-key (independent solve disagreed): {len(need_key)}")
    if bad:
        print(f"STRUCTURAL ISSUES: {len(bad)} items")
        for n, e in bad[:40]:
            print(f"   {n}: {'; '.join(e)}")
    else:
        print("structural issues: none")


def main() -> None:
    report("problem", PROBLEMS, check_problem)
    report("card", CARDS, check_card)


if __name__ == "__main__":
    main()
