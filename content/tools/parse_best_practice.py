#!/usr/bin/env python3
"""Mine the scanned REA/Molitoris book (best-practice-material-for-pgre.pdf).

Fully scanned (no text layer), 4 practice tests of ~100 items each. Question
pages are column-OCR'd; keys are taken from the "Detailed Explanations"
sections, where each entry begins `N. (X)`. OCR of this older scan is noisy
(garbled math and choice glyphs), so every item is flagged low-confidence.

Output: content/examples/reference-questions/best-practice-material.json.
NON-ETS copyrighted prep material -> example / gold candidate, not shipped.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, "tools")
from ocr_form import ocr_clip, ocr_pages  # noqa: E402
from parse_form_text import parse_blocks  # noqa: E402

import fitz  # noqa: E402

PDF = "reference/best-practice-material-for-pgre.pdf"
OUT = "examples/reference-questions/best-practice-material.json"
CACHE = "examples/reference-questions/_work"

# (test_no, question_pages, explanation_pages) - question pages start past the
# answer-sheet page (which carries decoy 1..100 bubble markers)
TESTS = [
    (1, range(90, 121), range(121, 161)),
    (2, range(164, 197), range(197, 241)),
    (3, range(244, 275), range(275, 324)),
    (4, range(330, 359), range(359, 406)),
]

KEYLINE = re.compile(r"(?m)^\s*(\d{1,3})\.?\s*\(([A-E])\)")


def cached_q(test_no, pages):
    os.makedirs(CACHE, exist_ok=True)
    path = f"{CACHE}/bpm_q{test_no}.txt"
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    raw = ocr_pages(PDF, list(pages))
    open(path, "w", encoding="utf-8").write(raw)
    return raw


def cached_keys(test_no, pages):
    """OCR explanation pages (single column) and pull `N. (X)` keys."""
    path = f"{CACHE}/bpm_e{test_no}.txt"
    if os.path.exists(path):
        text = open(path, encoding="utf-8").read()
    else:
        doc = fitz.open(PDF)
        parts = []
        for i in pages:
            parts.append(ocr_clip(doc[i], 0.0, 1.0, dpi=200, psm=6))
        doc.close()
        text = "\n".join(parts)
        open(path, "w", encoding="utf-8").write(text)
    keys = {}
    for m in KEYLINE.finditer(text):
        n = int(m.group(1))
        if 1 <= n <= 100 and n not in keys:
            keys[n] = m.group(2)
    return keys


def main():
    all_items = []
    for test_no, qpages, epages in TESTS:
        raw = cached_q(test_no, qpages)
        items = parse_blocks(raw, f"BPM-T{test_no}", "ocr")
        keys = cached_keys(test_no, epages)
        for it in items:
            it["id"] = f"bpm-test{test_no}-{it['number']:03d}"
            it["source"] = "REA GRE Physics (Molitoris), scanned; OCR low-confidence"
            it["test"] = test_no
            it["key"] = keys.get(it["number"])
            it["ets_lookalike"] = None
            it["leakage_class"] = "reference_example"
            it["ocr_low_confidence"] = True
            it.pop("form", None)
            it.pop("leakage_class", None)
            it["leakage_class"] = "reference_example"
        stems = sum(1 for it in items if it["stem"].strip() and "missing" not in it["stem_source"])
        withkey = sum(1 for it in items if it["key"])
        print(f"Test {test_no}: {len(items)} items, real_stems={stems}, with_key={withkey}")
        all_items.extend(items)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=1)
    print(f"wrote {len(all_items)} items -> {OUT}")


if __name__ == "__main__":
    main()
