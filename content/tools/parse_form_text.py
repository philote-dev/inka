#!/usr/bin/env python3
"""Parse a text-layer ETS form PDF (GR0177, GR0877) into structured items.

These two forms carry a real text layer in correct column reading order, so
we slice the concatenated page text on sequential question numbers 1..100.
"""
from __future__ import annotations

import re
import sys

import fitz

from pgre_common import (
    figure_dependent,
    guess_topic,
    math_garbled,
    split_stem_choices,
    strip_furniture,
)


def concat_pages(pdf_path: str, page_start: int, page_end: int) -> str:
    doc = fitz.open(pdf_path)
    parts = []
    for i in range(page_start, min(page_end, doc.page_count)):
        parts.append(doc[i].get_text())
    doc.close()
    return "\n".join(parts)


# number then dot/paren then any whitespace (incl. newline); filters bare page
# numbers (no dot) and decimals like 0.30 (no whitespace after the dot)
QMARK = re.compile(r"(?m)^[ \t]{0,8}(\d{1,3})[.)](?=\s)")


def _longest_increasing(cands):
    """Longest strictly-increasing-by-number chain over position-ordered cands."""
    if not cands:
        return []
    n = len(cands)
    best = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if cands[j][1] < cands[i][1] and best[j] + 1 > best[i]:
                best[i] = best[j] + 1
                prev[i] = j
    end = max(range(n), key=lambda i: best[i])
    chain = []
    while end != -1:
        chain.append(cands[end])
        end = prev[end]
    return chain[::-1]


def find_question_spans(text: str, expected: int = 100):
    """Locate question starts robustly; return (spans, found_numbers).

    Strategy: a longest-increasing-by-number chain forms a trusted backbone,
    then gaps are filled by trusting position order (questions are strictly
    sequential), which recovers numbers whose tens digit the OCR dropped
    (e.g. 35 read as "5."). Gap fill only fires when the count of intervening
    markers exactly matches the count of missing numbers, so it stays safe.
    """
    cands = sorted(
        (m.start(), int(m.group(1)), m.end())
        for m in QMARK.finditer(text)
        if 1 <= int(m.group(1)) <= expected
    )
    if not cands:
        return [], set()
    chain = _longest_increasing(cands)
    backbone_pos = {pos for pos, _n, _e in chain}
    anchors = [(num, pos) for pos, num, _e in chain]  # position order

    def markers_between(p0, p1):
        return sorted(pos for pos, _n, _e in cands if p0 < pos < p1 and pos not in backbone_pos)

    final = [(pos, num) for pos, num, _e in chain]

    # interior gaps between consecutive backbone anchors
    for (num_a, pos_a), (num_c, pos_c) in zip(anchors, anchors[1:]):
        gap = num_c - num_a - 1
        if gap <= 0:
            continue
        mk = markers_between(pos_a, pos_c)
        if len(mk) == gap:
            for k, pos in enumerate(mk):
                final.append((pos, num_a + 1 + k))

    # leading gap (numbers before the first backbone anchor)
    first_num, first_pos = anchors[0]
    lead_needed = first_num - 1
    lead_mk = markers_between(-1, first_pos)
    if lead_needed > 0 and len(lead_mk) == lead_needed:
        for k, pos in enumerate(lead_mk):
            final.append((pos, 1 + k))
    elif first_num == 2 and lead_needed == 1:  # #1 merged into the directions header
        final.append((0, 1))

    # trailing gap (numbers after the last backbone anchor, up to `expected`)
    last_num, last_pos = anchors[-1]
    trail_needed = expected - last_num
    trail_mk = markers_between(last_pos, len(text))
    if trail_needed > 0 and len(trail_mk) == trail_needed:
        for k, pos in enumerate(trail_mk):
            final.append((pos, last_num + 1 + k))

    # dedupe by number (first position wins), order by position, build spans
    final.sort()
    seen = set()
    clean = []
    for pos, num in final:
        if num in seen:
            continue
        seen.add(num)
        clean.append((pos, num))
    spans = []
    for i, (pos, num) in enumerate(clean):
        nxt = clean[i + 1][0] if i + 1 < len(clean) else len(text)
        spans.append((num, pos, nxt))
    return spans, seen


def build_item(num: int, block: str, form_id: str, stem_source: str) -> dict:
    block = re.sub(r"^[ \t]*\d{1,3}[.)]\s", " ", block, count=1)
    block = strip_furniture(block)
    stem, choices, found_all = split_stem_choices(block)
    if not stem.strip() and not any(c.strip() for c in choices.values()):
        # number detected but body detached in OCR (margin-clustered numbers)
        return placeholder_item(num, form_id, stem_source, "stem detached from number in OCR")
    fig = figure_dependent(stem, choices)
    math = math_garbled(stem, choices, fig)
    topic = guess_topic(stem + " " + " ".join(choices.values()))
    ocr = stem_source == "ocr"
    return {
        "id": f"{form_id}-{num:03d}",
        "form": form_id,
        "number": num,
        "stem": stem,
        "choices": [choices[c] for c in ["A", "B", "C", "D", "E"]],
        "key": None,
        "topic_guess": topic,
        "figure_dependent": fig,
        "math_garbled": math,
        "stem_source": stem_source,
        "needs_review": (not found_all) or fig or math or ocr,
        "leakage_class": "heldout",
    }


def placeholder_item(num: int, form_id: str, stem_source: str,
                     note: str = "question number not located during extraction") -> dict:
    return {
        "id": f"{form_id}-{num:03d}",
        "form": form_id,
        "number": num,
        "stem": "",
        "choices": ["", "", "", "", ""],
        "key": None,
        "topic_guess": "Unclassified",
        "figure_dependent": False,
        "math_garbled": False,
        "stem_source": f"{stem_source}_missing",
        "needs_review": True,
        "notes": note,
        "leakage_class": "heldout",
    }


def parse_blocks(raw: str, form_id: str, stem_source: str, expected: int = 100) -> list[dict]:
    spans, found = find_question_spans(raw, expected)
    by_num = {num: build_item(num, raw[start:end], form_id, stem_source) for num, start, end in spans}
    items = []
    for n in range(1, expected + 1):
        items.append(by_num.get(n) or placeholder_item(n, form_id, stem_source))
    return items


def parse_form(pdf_path: str, form_id: str, page_start: int, page_end: int) -> list[dict]:
    raw = concat_pages(pdf_path, page_start, page_end)
    return parse_blocks(raw, form_id, "form_text_layer")


if __name__ == "__main__":
    pdf = sys.argv[1]
    form = sys.argv[2]
    ps, pe = int(sys.argv[3]), int(sys.argv[4])
    items = parse_form(pdf, form, ps, pe)
    print(f"{form}: parsed {len(items)} items")
    figs = [it["number"] for it in items if it["figure_dependent"]]
    print(f"figure-dependent: {len(figs)} -> {figs}")
    # show a few
    for it in items[:3]:
        print("---", it["id"], "| topic:", it["topic_guess"])
        print("stem:", it["stem"][:200])
        print("choices:", it["choices"])
