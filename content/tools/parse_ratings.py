"""Parse Frank's rated batch sheet into a rater-1 CSV for score_batch.

Reads content/gold/RATING-SHEET-rated.md and writes content/run/frank_ratings.csv
with columns target_id, system, useful, fact_precision, key_correct,
distractors_ok. Cells are left empty where Frank did not rate that field (cards
have no key/distractor rating; problems have no separate fact rating), so the
scorer overlays only what he actually judged.

Run:
    python content/tools/parse_ratings.py
"""

from __future__ import annotations

import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
SHEET = os.path.join(CONTENT, "gold", "RATING-SHEET-rated.md")
OUT = os.path.join(CONTENT, "run", "frank_ratings.csv")


def yn(block: str, field: str) -> str:
    m = re.search(rf"{field}\s*\(y/n\)\s*:\s*([yn])", block, flags=re.I)
    if not m:
        return ""
    return "yes" if m.group(1).lower() == "y" else "no"


def main() -> None:
    txt = open(SHEET, encoding="utf-8").read()
    blocks = re.split(r"^### [CP]\d+\.\s*`", txt, flags=re.M)[1:]
    rows = []
    for b in blocks:
        tid = re.match(r"([^`]+)`", b).group(1)
        if tid.startswith("cardtgt"):
            rows.append({"target_id": tid, "system": "ai", "useful": yn(b, "useful"),
                         "fact_precision": yn(b, "facts_ok"), "key_correct": "",
                         "distractors_ok": ""})
        else:
            rows.append({"target_id": tid, "system": "ai", "useful": yn(b, "useful"),
                         "fact_precision": "", "key_correct": yn(b, "key_correct"),
                         "distractors_ok": yn(b, "distractors_ok")})
    fields = ["target_id", "system", "useful", "fact_precision", "key_correct", "distractors_ok"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}  ({len(rows)} rated items)")


if __name__ == "__main__":
    main()
