#!/usr/bin/env python3
"""Assemble structured, private ETS held-out items for all five forms.

Stems/choices come from the form (text layer for GR0177/GR0877; column OCR
for the scanned GR8677/GR9277/GR9677). Answer keys come from the solution
sets (Faucett Omnibus for 8677/9277/9677/0177; gr0877_solutions for 0877),
with the GR0177 blog md used as an independent key cross-check.

LEAKAGE FIREWALL: writes ONLY under tier3-private/items/. These items are
never indexed or fed to generation.
"""
from __future__ import annotations

import json
import os
import re

from extract_omnibus_keys import extract as omnibus_extract
from extract_other_keys import gr0177_md_keys, gr0877_keys
from ocr_form import ocr_pages
from parse_form_text import parse_blocks, parse_form

ITEMS_DIR = "tier3-private/items"
OCR_CACHE = "tier3-private/items/_ocr_cache"


def ocr_pages_cached(form_id: str, pdf: str, pages: list[int]) -> str:
    os.makedirs(OCR_CACHE, exist_ok=True)
    cache = f"{OCR_CACHE}/{form_id}.txt"
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return f.read()
    raw = ocr_pages(pdf, pages)
    with open(cache, "w", encoding="utf-8") as f:
        f.write(raw)
    return raw

# OCR misreads the (C) glyph as the copyright sign; normalize before parsing.
OCR_FIXES = [(r"\(©\)", "(C)"), (r"\(\?\)", "(C)")]


def normalize_ocr(text: str) -> str:
    for pat, rep in OCR_FIXES:
        text = re.sub(pat, rep, text)
    return text


def mark_unscored(items):
    """ETS flags a rare item as not scored; it has no official key."""
    for it in items:
        if "THIS ITEM WAS NO" in it["stem"].upper():
            it["stem"] = "[ETS unscored item; excluded from scoring]"
            it["choices"] = ["", "", "", "", ""]
            it["key"] = None
            it["key_source"] = None
            it["unscored"] = True
            it["needs_review"] = False
            it["notes"] = "ETS unscored item; no official key exists"


def attach_keys(items, keymap, key_source, extra_keymap=None):
    """Fill item['key'] from keymap; record source and any cross-check note."""
    for it in items:
        n = it["number"]
        entry = keymap.get(n)
        if entry is None:
            it["key"] = None
            it["key_source"] = None
            it["needs_review"] = True
            it["notes"] = "no key found in solution set"
            continue
        key = entry["key"] if isinstance(entry, dict) else entry
        it["key"] = key
        it["key_source"] = key_source
        if extra_keymap and n in extra_keymap:
            if extra_keymap[n] != key:
                it["key_crosscheck"] = f"DISAGREE: {key_source}={key} md={extra_keymap[n]}"
                it["needs_review"] = True
            else:
                it["key_crosscheck"] = "agree"


def summarize(form_id, items):
    n = len(items)
    with_key = sum(1 for it in items if it["key"])
    figs = [it["number"] for it in items if it["figure_dependent"]]
    math = [it["number"] for it in items if it["math_garbled"]]
    review = sum(1 for it in items if it["needs_review"])
    topics: dict[str, int] = {}
    for it in items:
        topics[it["topic_guess"]] = topics.get(it["topic_guess"], 0) + 1
    return {
        "form": form_id,
        "items": n,
        "with_key": with_key,
        "figure_dependent": len(figs),
        "math_garbled": len(math),
        "needs_review": review,
        "topics": dict(sorted(topics.items(), key=lambda kv: -kv[1])),
    }


def write_items(form_id, items):
    path = f"{ITEMS_DIR}/{form_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    return path


def main():
    omni = omnibus_extract()
    k0877 = gr0877_keys()
    k0177_md = gr0177_md_keys()

    summaries = []

    # --- text-layer forms ---
    it0177 = parse_form("tier3-private/forms/exam-gr0177.pdf", "GR0177", 11, 69)
    attach_keys(it0177, omni["GR0177"], "omnibus", extra_keymap=k0177_md)
    write_items("GR0177", it0177)
    summaries.append(summarize("GR0177", it0177))

    it0877 = parse_form("tier3-private/forms/exam-gr0877.pdf", "GR0877", 11, 85)
    attach_keys(it0877, k0877, "gr0877_solutions")
    write_items("GR0877", it0877)
    summaries.append(summarize("GR0877", it0877))

    # --- scanned forms (column OCR) ---
    ocr_specs = [
        ("GR9277", "tier3-private/forms/exam-gr9277.pdf", list(range(4, 30)), omni["GR9277"]),
        ("GR8677", "tier3-private/forms/exam-gr8677.pdf", list(range(4, 23)), omni["GR8677"]),
        ("GR9677", "tier3-private/forms/exam-gr9677.pdf", list(range(11, 72, 2)), omni["GR9677"]),
    ]
    for form_id, pdf, pages, keymap in ocr_specs:
        raw = normalize_ocr(ocr_pages_cached(form_id, pdf, pages))
        items = parse_blocks(raw, form_id, "ocr")
        attach_keys(items, keymap, "omnibus")
        mark_unscored(items)
        write_items(form_id, items)
        summaries.append(summarize(form_id, items))

    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
