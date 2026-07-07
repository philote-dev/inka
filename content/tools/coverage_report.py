"""Corpus coverage report against the 25 blueprint finest units.

For every finest unit in ``content/blueprint/blueprint.json`` this queries the
built RAG index (``content/index/corpus.db``) with the unit name plus its ETS
content description, then reports the best match score, the source it came from,
and how many of the top-k chunks clear a similarity floor. Units whose best
match falls below the floor are flagged as weak, so a coverage gap shows before
any generation runs.

This reads the corpus index only. It never touches gold, held-out, or Tier-3
material.

Run:
    conda run -n pgrep-ai python content/tools/coverage_report.py
    conda run -n pgrep-ai python content/tools/coverage_report.py --floor 0.55 -k 20
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

from query_index import connect, search
from sentence_transformers import SentenceTransformer

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
BLUEPRINT = os.path.join(CONTENT, "blueprint", "blueprint.json")
DB_PATH = os.path.join(CONTENT, "index", "corpus.db")

MODEL_NAME = "BAAI/bge-small-en-v1.5"


def load_finest_units() -> list[dict]:
    """Flatten the blueprint into one row per finest unit."""
    with open(BLUEPRINT, encoding="utf-8") as fh:
        bp = json.load(fh)
    units = []
    for cat in bp["categories"]:
        for unit in cat["finest_units"]:
            units.append({
                "category": cat["slug"],
                "category_name": cat["name"],
                "weight_pct": cat["weight_pct"],
                "slug": unit["slug"],
                "name": unit["name"],
                "tag": unit["tag"],
                "ets_content": unit.get("ets_content", ""),
            })
    return units


def main() -> None:
    ap = argparse.ArgumentParser(description="Corpus coverage vs the 25 finest units.")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("-k", "--top-k", type=int, default=20)
    ap.add_argument("--floor", type=float, default=0.55,
                    help="cosine similarity floor for a chunk to count as coverage")
    args = ap.parse_args()

    units = load_finest_units()
    db = connect(args.db)
    model = SentenceTransformer(MODEL_NAME)

    print(f"coverage report over {args.db}")
    print(f"floor={args.floor}  k={args.top_k}  finest_units={len(units)}\n")

    weak: list[dict] = []
    by_cat: dict[str, list[float]] = defaultdict(list)
    header = f"{'#':>2}  {'unit':38}  {'best':>5}  {'>=floor':>7}  source"
    print(header)
    print("-" * len(header))
    for i, unit in enumerate(units, start=1):
        query = f"{unit['name']}. {unit['ets_content']}"
        results = search(db, model, query, args.top_k)
        best = results[0]["score"] if results else 0.0
        n_ok = sum(1 for r in results if r["score"] >= args.floor)
        by_cat[unit["category"]].append(best)
        src = results[0]["source_title"] if results else "(none)"
        flag = " " if best >= args.floor else "!"
        print(f"{i:>2}{flag} {unit['name'][:38]:38}  {best:>5.3f}  "
              f"{n_ok:>3}/{args.top_k}  {src}")
        if best < args.floor:
            weak.append(unit)

    print("\nper-category best-match average")
    for cat, scores in by_cat.items():
        avg = sum(scores) / len(scores)
        print(f"   {cat:18}  units={len(scores):>2}  avg_best={avg:.3f}")

    print(f"\ncovered: {len(units) - len(weak)}/{len(units)} finest units clear the floor")
    if weak:
        print("weak units (best match below floor):")
        for unit in weak:
            print(f"   ! {unit['tag']}  ({unit['name']})")
    else:
        print("no weak units: every finest unit has corpus coverage above the floor")
    db.close()


if __name__ == "__main__":
    main()
