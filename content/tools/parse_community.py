#!/usr/bin/env python3
"""Parse the community "70 sample questions" thread into structured items.

Source: content/gold/candidates/User-created-70-sample.rtfd (forum export),
converted to text with `textutil`. Math is authored in LaTeX ($$..$$), which
we keep verbatim. Keys come from the thread's own answer section; 13 are TBA.
Output: content/gold/candidates/community-70.json (gold CANDIDATE, not ETS).
"""
from __future__ import annotations

import json
import re
import sys

sys.path.insert(0, "tools")
from pgre_common import clean_ws, split_stem_choices  # noqa: E402

SRC = "gold/candidates/_work/community-70.txt"
OUT = "gold/candidates/community-70.json"

QHEADER = re.compile(r"(?m)^SAMPLE QUESTION\s+(\d{1,2})\s*:")
ANS_SPLIT = "ANSWERS TO ALL POSTED SAMPLE QUESTIONS:"

# forum furniture lines to drop from a question block
FURNITURE = re.compile(
    r"(?m)^(Post|Top|by \w+.*|physics_auth|blackcat007|Posts:.*|Joined:.*|"
    r"Last edited by.*|.*wrote:|-{5,}.*|Notice:.*|Time alloted:.*|"
    r"\d+ NEW SAMPLE.*|SAMPLE QUESTIONS.*HOW TO FIND.*)$"
)

GREEK_TO_LATIN = {"Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I"}


def norm_key_char(c: str) -> str:
    return GREEK_TO_LATIN.get(c, c)


def parse_keys(answer_text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for m in re.finditer(r"(?m)^SAMPLE QUESTION\s+(\d{1,2})\s*:\s*(.+?)\s*$", answer_text):
        num = int(m.group(1))
        val = m.group(2).strip()
        km = re.search(r"\(?\s*([A-EΑΒΕ])\s*\)?", val)
        if "TBA" in val.upper() or not km:
            out[num] = None
        else:
            out[num] = norm_key_char(km.group(1))
    return out


def clean_block(block: str) -> str:
    block = FURNITURE.sub("", block)
    return block


def strip_trailing_note(choice_e: str) -> tuple[str, str]:
    """Split a trailing {..} clarification off the last choice."""
    m = re.search(r"\{[^}]*\}\s*$", choice_e)
    if m:
        return choice_e[: m.start()].strip(), m.group(0).strip("{} ")
    return choice_e, ""


def main():
    with open(SRC, encoding="utf-8") as f:
        text = f.read()
    q_region, _, a_region = text.partition(ANS_SPLIT)
    keys = parse_keys(a_region)

    headers = list(QHEADER.finditer(q_region))
    items = []
    seen = set()
    for i, m in enumerate(headers):
        num = int(m.group(1))
        if num in seen or not (1 <= num <= 70):
            continue
        seen.add(num)
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(q_region)
        block = clean_block(q_region[start:end])
        stem, choices, found_all = split_stem_choices(block)
        note = ""
        if choices["E"]:
            choices["E"], note = strip_trailing_note(choices["E"])
        if note and note not in stem:
            stem = clean_ws(stem + " (" + note + ")")
        items.append({
            "id": f"community-70-{num:03d}",
            "source": "physicsgre.com user-created 70 sample thread",
            "number": num,
            "stem": stem,
            "choices": [choices[c] for c in ["A", "B", "C", "D", "E"]],
            "key": keys.get(num),
            "explanation_if_any": None,
            "ets_lookalike": None,  # filled by leakage_check.py
            "leakage_class": "gold_candidate",
            "needs_review": (not found_all) or keys.get(num) is None,
        })
    items.sort(key=lambda it: it["number"])
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)

    with_key = sum(1 for it in items if it["key"])
    tba = [it["number"] for it in items if it["key"] is None]
    empties = [it["number"] for it in items if not it["stem"].strip()]
    print(f"community-70: parsed {len(items)} items, with_key={with_key}, "
          f"TBA/no-key={len(tba)} {tba}, empty_stem={empties}")


if __name__ == "__main__":
    main()
