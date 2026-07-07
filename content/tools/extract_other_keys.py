#!/usr/bin/env python3
"""Extract answer keys from the GR0877 solution set and the GR0177 blog md.

- gr0877_solutions.pdf: lines like `1. (B) ...`, `15. (E) ...`.
- GR0177-0.md: `Answer: **X**` blocks tagged `(GR0177 #NN)` (covers #1-20).
"""
from __future__ import annotations

import re

import fitz

GR0877_SOL = "tier3-private/solutions/gr0877_solutions.pdf"
GR0177_MD = "tier3-private/forms/GR0177-0.md"

KEY_LINE = re.compile(r"(?m)^\s*(\d{1,3})\.\s*\(([A-E])\)")


def gr0877_keys(path: str = GR0877_SOL) -> dict[int, str]:
    doc = fitz.open(path)
    text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
    doc.close()
    out: dict[int, str] = {}
    for m in KEY_LINE.finditer(text):
        num = int(m.group(1))
        if 1 <= num <= 100 and num not in out:
            out[num] = m.group(2)
    return out


NUM_TAG = re.compile(r"\(GR0177\s*#(\d{1,3})\)")
ANS = re.compile(r"Answer:[\s\*]*([A-E])\b")


def gr0177_md_keys(path: str = GR0177_MD) -> dict[int, str]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out: dict[int, str] = {}
    # split by the (GR0177 #NN) tags; the Answer after a tag belongs to it
    tags = list(NUM_TAG.finditer(text))
    for i, m in enumerate(tags):
        num = int(m.group(1))
        end = tags[i + 1].start() if i + 1 < len(tags) else len(text)
        seg = text[m.end():end]
        a = ANS.search(seg)
        if a:
            out[num] = a.group(1)
    return out


if __name__ == "__main__":
    k7 = gr0877_keys()
    miss = [n for n in range(1, 101) if n not in k7]
    print(f"GR0877: {len(k7)} keys, missing={miss}")
    k1 = gr0177_md_keys()
    print(f"GR0177 (md): {len(k1)} keys -> {sorted(k1.items())}")
