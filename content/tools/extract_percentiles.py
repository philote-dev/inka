"""Extract the GR0177 score-conversion table with percentiles (numbers only).

The form GR0177 conversion page has raw -> scaled -> percent-below, from 10,947
examinees. Plain text extraction jumbles its two-column layout, so this rebuilds
rows from word coordinates: cluster words by y, sort by x, and read each row as
two (raw, scaled, percent) triples.

Constants only, no items. Output: content/tier3-private/constants/.

Run:
    conda run -n pgrep-ai --no-capture-output python content/tools/extract_percentiles.py
"""

from __future__ import annotations

import json
import os
import re

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
GR0177 = os.path.join(CONTENT, "tier3-private", "forms", "exam-gr0177.pdf")
OUT_DIR = os.path.join(CONTENT, "tier3-private", "constants")
PAGE = 72

RAW = re.compile(r"^\d{1,3}(?:[\u2013\u2014\-\u2212]\d{1,3})?$")


def rows_from_words(words: list) -> list[list]:
    """Group (x0,y0,x1,y1,word,...) tuples into rows by y, sorted by x."""
    rows: dict[int, list] = {}
    for w in words:
        x0, y0, _x1, _y1, text = w[0], w[1], w[2], w[3], w[4]
        key = round(y0 / 4.0)  # ~4pt row bucket
        rows.setdefault(key, []).append((x0, text))
    out = []
    for key in sorted(rows):
        toks = [t for _x, t in sorted(rows[key])]
        out.append(toks)
    return out


def triples_from_row(toks: list[str]) -> list[dict]:
    """A data row is two (raw, scaled, percent) triples; parse whatever aligns."""
    nums = [t for t in toks if RAW.match(t)]
    out = []
    i = 0
    while i + 2 < len(nums) + 1 and i + 2 < len(nums) + 0 + 1:
        if i + 2 >= len(nums):
            break
        raw, scaled, pct = nums[i], nums[i + 1], nums[i + 2]
        try:
            sc = int(scaled)
            pc = int(pct)
        except ValueError:
            i += 1
            continue
        if sc % 10 == 0 and 200 <= sc <= 990 and 0 <= pc <= 99 and "-" not in scaled and "-" not in pct:
            lo = int(raw.split("-")[0].replace("\u2013", "-").split("-")[0])
            hi = int(re.split(r"[\u2013\u2014\-\u2212]", raw)[-1])
            out.append({"raw_min": lo, "raw_max": hi, "scaled": sc, "percent_below": pc})
            i += 3
        else:
            i += 1
    return out


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    doc = fitz.open(GR0177)
    words = doc[PAGE].get_text("words")
    doc.close()

    table = []
    for toks in rows_from_words(words):
        table.extend(triples_from_row(toks))
    # dedup by scaled, sort desc
    seen = {}
    for r in table:
        seen.setdefault(r["scaled"], r)
    table = [seen[s] for s in sorted(seen, reverse=True)]

    payload = {
        "name": "GRE Physics score conversion with percentiles, form GR0177",
        "source": "exam-gr0177.pdf conversion page (Score Conversions and Percents Below)",
        "norm_population": "10,947 examinees, Physics Test, 2000-07-01 to 2003-06-30",
        "note": "Constants only, no items. raw -> scaled (200-990) and percent scoring below.",
        "n_levels": len(table),
        "table": table,
    }
    out = os.path.join(OUT_DIR, "gr0177_score_conversion.json")
    json.dump(payload, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[gr0177 conversion] {len(table)} levels")
    for r in table[:3] + table[-3:]:
        print("  ", r)
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
