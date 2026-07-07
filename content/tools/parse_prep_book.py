#!/usr/bin/env python3
"""Mine the REA "GRE Physics" prep book (physics-gre-prep-book.pdf).

The book has a clean text layer and two full practice exams, each with 100
five-choice questions, an answer key, and detailed explanations. Choices use
a two-column grid (handled by the position-based splitter).

Output: content/examples/reference-questions/rea-gre-physics-prepbook.json.
NON-ETS copyrighted prep material -> example / gold candidate, NOT shipped
verbatim. ETS-lookalikes are flagged later by leakage_check.py.
"""
from __future__ import annotations

import json
import re
import sys

import fitz

sys.path.insert(0, "tools")
from parse_form_text import find_question_spans  # noqa: E402
from pgre_common import (  # noqa: E402
    clean_ws,
    figure_dependent,
    guess_topic,
    split_stem_choices,
    strip_furniture,
)

PDF = "reference/physics-gre-prep-book.pdf"
OUT = "examples/reference-questions/rea-gre-physics-prepbook.json"

# (exam_no, question_pages, answer_key_page, explanation_pages)
EXAMS = [
    (1, range(146, 166), 166, range(168, 214)),
    (2, range(218, 240), 240, range(242, 289)),
]

KEY_LINE = re.compile(r"(?m)^\s*(\d{1,3})\.\s*\(([A-E])\)")
PREP_FURNITURE = re.compile(
    r"(?m)^(GRE PHYSICS|PRACTICE EXAM \d|Practice Exam \d.*|"
    r"DETAILED EXPLANATIONS.*|Detailed Explanations.*|Answer Key|"
    r"TIME:.*|Time:.*|DIRECTIONS:.*|Directions:.*|\d{1,3})\s*$"
)


def page_text(doc, i):
    return doc[i].get_text()


def concat(doc, pages):
    return "\n".join(page_text(doc, i) for i in pages)


def keys_from_page(doc, page):
    text = page_text(doc, page)
    out = {}
    for m in KEY_LINE.finditer(text):
        out[int(m.group(1))] = m.group(2)
    return out


def explanations_from_pages(doc, pages):
    raw = concat(doc, pages)
    raw = PREP_FURNITURE.sub(" ", raw)
    spans, _found = find_question_spans(raw)
    out = {}
    for num, start, end in spans:
        seg = raw[start:end]
        seg = re.sub(r"^\s*\d{1,3}\.\s*", "", seg, count=1)
        seg = re.sub(r"^\s*\([A-E]\)\s*", "", seg, count=1)
        out[num] = clean_ws(seg)[:1500]
    return out


def parse_exam(doc, exam_no, qpages, keypage, exppages):
    raw = concat(doc, qpages)
    raw = PREP_FURNITURE.sub(" ", raw)
    spans, _found = find_question_spans(raw)
    keys = keys_from_page(doc, keypage)
    expls = explanations_from_pages(doc, exppages)
    items = []
    for num, start, end in spans:
        block = re.sub(r"^\s*\d{1,3}\.\s*", " ", raw[start:end], count=1)
        block = strip_furniture(block)
        stem, choices, found_all = split_stem_choices(block)
        fig = figure_dependent(stem, choices)
        topic = guess_topic(stem + " " + " ".join(choices.values()))
        items.append({
            "id": f"rea-prepbook-e{exam_no}-{num:03d}",
            "source": "REA GRE Physics prep book (Fakhruddin & Molitoris)",
            "exam": exam_no,
            "number": num,
            "stem": stem,
            "choices": [choices[c] for c in ["A", "B", "C", "D", "E"]],
            "key": keys.get(num),
            "explanation_if_any": expls.get(num) or None,
            "topic_guess": topic,
            "figure_dependent": fig,
            "ets_lookalike": None,
            "leakage_class": "reference_example",
            "needs_review": (not found_all) or keys.get(num) is None,
        })
    return items


def main():
    doc = fitz.open(PDF)
    all_items = []
    for exam_no, qpages, keypage, exppages in EXAMS:
        items = parse_exam(doc, exam_no, qpages, keypage, exppages)
        withkey = sum(1 for it in items if it["key"])
        withexp = sum(1 for it in items if it["explanation_if_any"])
        print(f"Exam {exam_no}: {len(items)} items, with_key={withkey}, with_expl={withexp}")
        all_items.extend(items)
    doc.close()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=1)
    print(f"wrote {len(all_items)} items -> {OUT}")


if __name__ == "__main__":
    main()
