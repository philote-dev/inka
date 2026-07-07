"""Extract the raw-to-scaled score-conversion constants (numbers only).

Readiness (L5.3) maps an expected raw score to the 200-990 GRE Physics scale. The
complete raw-to-scaled table is published in physics-gre-prep-book.pdf p.8; this
parses it into JSON. It also dumps the GR0177 form conversion page so we can see
whether a percentile ("% below") column is available to add.

Constants only: no test items are read or written. Output goes to
content/tier3-private/constants/.

Run:
    conda run -n pgrep-ai --no-capture-output python content/tools/extract_constants.py
"""

from __future__ import annotations

import json
import os
import re

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
PREP = os.path.join(CONTENT, "reference", "physics-gre-prep-book.pdf")
GR0177 = os.path.join(CONTENT, "tier3-private", "forms", "exam-gr0177.pdf")
OUT_DIR = os.path.join(CONTENT, "tier3-private", "constants")

PAIR = re.compile(r"(\d{1,3})(?:\s*[\u2013\u2014\-\u2212]\s*(\d{1,3}))?\s+(\d{3})\b")


def parse_raw_to_scaled(text: str) -> list[dict]:
    rows = []
    for m in PAIR.finditer(text):
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        scaled = int(m.group(3))
        if scaled % 10 == 0 and 200 <= scaled <= 990 and 0 <= lo <= 100 and hi <= 100 and hi >= lo:
            rows.append({"raw_min": lo, "raw_max": hi, "scaled": scaled})
    # keep one row per scaled level, sorted high to low
    seen = {}
    for r in rows:
        seen.setdefault(r["scaled"], r)
    return [seen[s] for s in sorted(seen, reverse=True)]


def best_table_page(doc, lo_pages: int = 0) -> int:
    """Index of the page holding the most scaled-score-like numbers."""
    best_i, best_n = -1, 0
    for i in range(lo_pages, len(doc)):
        nums = re.findall(r"\b\d{3}\b", doc[i].get_text())
        n = sum(1 for x in nums if int(x) % 10 == 0 and 200 <= int(x) <= 990)
        if n > best_n:
            best_n, best_i = n, i
    return best_i


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    doc = fitz.open(PREP)
    table = parse_raw_to_scaled(doc[8].get_text())
    doc.close()

    payload = {
        "name": "GRE Physics raw-to-scaled score conversion",
        "source": "physics-gre-prep-book.pdf p.8 (published GRE Physics prep book conversion table)",
        "note": "Constants only, no items. Raw score = correct - incorrect/4, rounded to the "
                "nearest integer, over 100 scored questions. Scale is 200-990 in 10-point steps.",
        "raw_score_formula": "round(correct - incorrect/4)",
        "scale_min": 200,
        "scale_max": 990,
        "n_levels": len(table),
        "table": table,
    }
    out = os.path.join(OUT_DIR, "raw_to_scaled.json")
    json.dump(payload, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[raw->scaled] {len(table)} levels, {table[0]['scaled']} down to {table[-1]['scaled']}")
    print(f"  wrote {out}")

    # Inspect the GR0177 conversion page for a percentile column.
    d = fitz.open(GR0177)
    pi = best_table_page(d, lo_pages=60)
    print(f"\n[GR0177] richest score-table page index: {pi}")
    if pi >= 0:
        print(" ".join(d[pi].get_text().split())[:1400])
    d.close()


if __name__ == "__main__":
    main()
