#!/usr/bin/env python3
"""Compute final extraction stats across all produced datasets for the report."""
from __future__ import annotations

import glob
import json


def stem_ok(it):
    return bool(it.get("stem", "").strip()) and "missing" not in it.get("stem_source", "")


def main():
    print("=== ETS held-out items (tier3-private/items) ===")
    tot = 0
    tk = 0
    for path in sorted(glob.glob("tier3-private/items/GR*.json")):
        d = json.load(open(path))
        form = d[0]["form"]
        keys = sum(1 for it in d if it.get("key"))
        stems = sum(1 for it in d if stem_ok(it))
        fig = sum(1 for it in d if it.get("figure_dependent"))
        math = sum(1 for it in d if it.get("math_garbled"))
        ph = sum(1 for it in d if "missing" in it.get("stem_source", ""))
        src = d[0]["stem_source"].replace("_missing", "")
        print(f"  {form}: items={len(d)} keys={keys} real_stems={stems} "
              f"placeholders={ph} fig_dep={fig} math_garbled={math} src={src}")
        tot += len(d)
        tk += keys
    print(f"  TOTAL ETS: items={tot} keys={tk}")

    print("\n=== Gold candidate: community-70 ===")
    d = json.load(open("gold/candidates/community-70.json"))
    print(f"  items={len(d)} keys={sum(1 for it in d if it.get('key'))} "
          f"no_key_TBA={sum(1 for it in d if not it.get('key'))} "
          f"ets_lookalikes={sum(1 for it in d if it.get('ets_lookalike'))}")

    print("\n=== Reference-question examples ===")
    for path in sorted(glob.glob("examples/reference-questions/*.json")):
        d = json.load(open(path))
        if not isinstance(d, list) or not d:
            print(f"  {path.split('/')[-1]}: (empty)")
            continue
        keys = sum(1 for it in d if it.get("key"))
        stems = sum(1 for it in d if stem_ok(it))
        exps = sum(1 for it in d if it.get("explanation_if_any"))
        la = sum(1 for it in d if it.get("ets_lookalike"))
        print(f"  {path.split('/')[-1]}: items={len(d)} keys={keys} real_stems={stems} "
              f"explanations={exps} ets_lookalikes={la}")


if __name__ == "__main__":
    main()
