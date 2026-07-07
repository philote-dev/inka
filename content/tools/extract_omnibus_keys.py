#!/usr/bin/env python3
"""Extract answer keys (and recommended-solution text) from the Faucett Omnibus.

The Omnibus reproduces a worked solution per problem, each anchored by a
`PGRE<form> #<n>` heading and terminated by a `Correct Answer\\n(X)` block.
It does NOT reproduce stems/choices, so this yields keys + solutions only.

Writes nothing; importable. Run directly to print per-form key counts.
"""
from __future__ import annotations

import json
import re
import sys

import fitz

OMNIBUS = "tier3-private/solutions/Physics-GRE-Solutions-Omnibus.pdf"

# nearest preceding problem anchor for each "Correct Answer (X)"
ANCHOR = re.compile(r"PGRE(\d{4})\s*#(\d{1,3})")
ANSWER = re.compile(r"Correct\s+Answer\s*\n?\s*\(\s*([A-E])\s*\)")


def full_text(path: str) -> str:
    doc = fitz.open(path)
    parts = [doc[i].get_text() for i in range(doc.page_count)]
    doc.close()
    return "\n".join(parts)


def extract(path: str = OMNIBUS) -> dict[str, dict[int, dict]]:
    text = full_text(path)
    anchors = [(m.start(), m.group(1), int(m.group(2))) for m in ANCHOR.finditer(text)]
    out: dict[str, dict[int, dict]] = {}
    for m in ANSWER.finditer(text):
        pos = m.start()
        key = m.group(1)
        # nearest anchor before this answer
        cand = [a for a in anchors if a[0] < pos]
        if not cand:
            continue
        _, form, num = cand[-1]
        form_id = f"GR{form}"
        out.setdefault(form_id, {})
        if num not in out[form_id]:  # first answer wins (recommended)
            # capture solution snippet between anchor and answer
            start = cand[-1][0]
            snippet = text[start:pos]
            out[form_id][num] = {"key": key, "solution": snippet.strip()}
    return out


if __name__ == "__main__":
    data = extract()
    for form in sorted(data):
        nums = sorted(data[form])
        missing = [n for n in range(1, 101) if n not in data[form]]
        print(f"{form}: {len(nums)} keys, range {nums[0]}..{nums[-1]}, missing={missing}")
    if len(sys.argv) > 1:  # dump one form's keys for inspection
        form = sys.argv[1]
        for n in sorted(data[form]):
            print(n, data[form][n]["key"])
