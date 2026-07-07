"""Merge the Stage A grow batches into one candidate set and accepted problems.

Reads the per-group ``content_set.json`` files, concatenates them, drops stems
that duplicate each other or the shipped bundle, splits clean from flagged, and
normalizes the clean items to the shipped bundle problem shape:

  - ``topic`` from ``blueprint_tag`` (the generator's ``topic`` field is polluted
    with the presentation instruction),
  - ``correct`` from ``key``,
  - distractor ``misconception`` from ``misconception_tag``,
  - choice letter prefixes ("A. ") stripped, since the bundle carries none and the
    UI adds its own labels.

Math notation is left as-is; ``pgrep_math_convert.py --apply`` LaTeX-ifies it at
landing. Writes into ``--out`` (default content/run/triple/pool/merged):
  content_set.json (all, for the review sheet), accepted_problems.json (clean, in
  bundle shape, carrying figure_required for Stage B), flagged.json, and
  merge_report.json. Never touches the bundle.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import verify  # noqa: E402

LETTERS = "ABCDE"
FIG = re.compile(r'<div class="pg-figure">[\s\S]*?</div>')
LABEL = re.compile(r"^\s*([A-E])[.)]\s+")


def strip_labels(choices: list) -> list[str]:
    """Drop "A. " style prefixes, but only when all five are sequentially labeled."""
    if len(choices) == 5 and all(
        (m := LABEL.match(str(c))) and m.group(1) == LETTERS[i]
        for i, c in enumerate(choices)
    ):
        return [LABEL.sub("", str(c), count=1) for c in choices]
    return [str(c) for c in choices]


def to_bundle_problem(it: dict) -> dict:
    dists = []
    for d in it.get("distractors", []) or []:
        if isinstance(d, dict):
            dists.append({
                "label": d.get("label"),
                "misconception": d.get("misconception_tag") or d.get("misconception"),
                "rationale": d.get("rationale"),
            })
    return {
        "id": it["id"],
        "kind": "problem",
        "topic": it.get("blueprint_tag") or "",
        "stem": it.get("stem", ""),
        "choices": strip_labels(it.get("choices", []) or []),
        "correct": str(it.get("key", "")).strip().upper(),
        "distractors": dists,
        "solution_decomposition": it.get("solution_decomposition", []) or [],
        "difficulty": it.get("difficulty", 0.5),
        "source_ref": it.get("source_ref"),
        "figure_required": bool(it.get("figure_required")),
    }


def norm_hash(stem: str) -> str:
    return verify.normalized_front_hash(FIG.sub(" ", stem or ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--groups", nargs="+", default=[
        "content/run/triple/pool/g1",
        "content/run/triple/pool/g2",
        "content/run/triple/pool/g3",
    ])
    ap.add_argument("--bundle", default="pylib/anki/pgrep/content_bundle.json")
    ap.add_argument("--out", default="content/run/triple/pool/merged")
    args = ap.parse_args()

    items: list[dict] = []
    for g in args.groups:
        items += json.load(open(os.path.join(g, "content_set.json"), encoding="utf-8"))

    bundle = json.load(open(args.bundle, encoding="utf-8"))
    seen = {norm_hash(p.get("stem", "")) for p in bundle["problems"]}
    merged: list[dict] = []
    dropped_dup: list[dict] = []
    for it in items:
        h = norm_hash(it.get("stem", ""))
        if it.get("stem") and h in seen:
            it["dropped_reason"] = "duplicate stem (merge/bundle)"
            dropped_dup.append(it)
            continue
        seen.add(h)
        merged.append(it)

    clean = [it for it in merged if it.get("status") == "clean"]
    flagged = [it for it in merged if it.get("status") != "clean"]
    accepted = [to_bundle_problem(it) for it in clean]

    os.makedirs(args.out, exist_ok=True)
    json.dump(merged, open(os.path.join(args.out, "content_set.json"), "w",
                           encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(accepted, open(os.path.join(args.out, "accepted_problems.json"), "w",
                             encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(flagged, open(os.path.join(args.out, "flagged.json"), "w",
                            encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(dropped_dup, open(os.path.join(args.out, "dropped_duplicates.json"), "w",
                                encoding="utf-8"), indent=2, ensure_ascii=False)

    area = collections.Counter(it.get("blueprint_area") for it in merged)
    area_clean = collections.Counter(it.get("blueprint_area") for it in clean)
    reasons = collections.Counter(
        f.split(":", 1)[0] for it in flagged for f in it.get("flags", [])
    )
    report = {
        "merged": len(merged),
        "clean": len(clean),
        "flagged": len(flagged),
        "dropped_duplicates": len(dropped_dup),
        "figure_required_clean": sum(1 for it in clean if it.get("figure_required")),
        "figure_required_total": sum(1 for it in merged if it.get("figure_required")),
        "by_area": {a: {"total": area[a], "clean": area_clean.get(a, 0)}
                    for a in sorted(area)},
        "flag_reasons": dict(reasons),
    }
    json.dump(report, open(os.path.join(args.out, "merge_report.json"), "w",
                           encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
