"""Assemble the grown content bundle (does not wire figures or convert math).

Adds the accepted new problems (skipping ids already present), applies the
TEXT-ONLY stem rewrites and clears their figure requirement, attaches every
available decomposition by id (to new and to the deferred existing problems),
strips the internal ``figure_required`` helper key, and refreshes ``counts``.

Order in the landing pipeline:
  1. land_triple.py          (this: problems + decompositions + text-only edits)
  2. pgrep_math_convert.py   (--apply: bare math -> LaTeX)
  3. pgrep_wire_figures.py   (--figures approved_final.json: embed SVGs)
  4. pgrep_content_audit.py  (--strict) + check_figure_necessity.py

Writes the bundle in place (the worktree copy). Backs up first.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default="pylib/anki/pgrep/content_bundle.json")
    ap.add_argument("--accepted", nargs="+", default=[
        "content/run/triple/pool/merged/accepted_problems.json",
        "content/run/triple/pool/merged/accepted_from_review.json",
    ])
    ap.add_argument("--decomps", default="content/run/triple/decomp/all_decomps.json")
    ap.add_argument("--textonly", default="content/run/triple/figures/textonly_edits.json")
    args = ap.parse_args()

    shutil.copyfile(args.bundle, args.bundle.replace(".json", ".pre_triple.json"))
    bundle = json.load(open(args.bundle, encoding="utf-8"))
    existing = {p["id"] for p in bundle["problems"]}

    new: list[dict] = []
    for f in args.accepted:
        new += json.load(open(f, encoding="utf-8"))

    decomps = json.load(open(args.decomps, encoding="utf-8"))
    tedits = json.load(open(args.textonly, encoding="utf-8"))
    stem_edits = tedits.get("edits", {})

    added = 0
    for p in new:
        if p["id"] in existing:
            continue
        q = copy.deepcopy(p)
        q.pop("figure_required", None)
        if q["id"] in stem_edits:
            q["stem"] = stem_edits[q["id"]]
        t = decomps.get(q["id"])
        if t:
            q["decomposition_tutor"] = t
        bundle["problems"].append(q)
        existing.add(q["id"])
        added += 1

    filled = 0
    for p in bundle["problems"]:
        if not p.get("decomposition_tutor") and p["id"] in decomps:
            p["decomposition_tutor"] = decomps[p["id"]]
            filled += 1

    n_cards = len(bundle.get("cards", []))
    n_probs = len(bundle["problems"])
    bundle["counts"] = {"cards": n_cards, "problems": n_probs, "total": n_cards + n_probs}

    with open(args.bundle, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    with_decomp = sum(1 for p in bundle["problems"] if p.get("decomposition_tutor"))
    print(f"added {added} new problems; filled {filled} existing decompositions")
    print(f"problems now {n_probs}; with decomposition {with_decomp} "
          f"({100 * with_decomp // n_probs}%)")
    print(f"text-only stem edits applied: {len(stem_edits)}")


if __name__ == "__main__":
    main()
