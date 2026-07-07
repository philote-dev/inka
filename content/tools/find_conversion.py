"""Locate the raw-to-scaled conversion / percentile tables in the ETS PDFs.

Numbers only: we extract the score-conversion constants, never the items. Prints
each PDF page that looks like a conversion or percentile table so we can see
where it lives and how it is laid out, before parsing.

Run:
    conda run -n pgrep-ai --no-capture-output python content/tools/find_conversion.py
"""

from __future__ import annotations

import os

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)

PDFS = [
    os.path.join(CONTENT, "tier3-private", "forms", f)
    for f in ("exam-gr0177.pdf", "exam-gr0877.pdf", "exam-gr8677.pdf",
              "exam-gr9277.pdf", "exam-gr9677.pdf")
] + [
    os.path.join(CONTENT, "reference", "physics-gre-prep-book.pdf"),
]

KEYS = ("score conversion", "scaled score", "raw score", "conversion table",
        "% below", "percent below", "percentile", "total score")


def main() -> None:
    for path in PDFS:
        if not os.path.exists(path):
            print(f"[missing] {path}")
            continue
        doc = fitz.open(path)
        hits = []
        for i in range(len(doc)):
            text = doc[i].get_text()
            low = text.lower()
            score = sum(low.count(k) for k in KEYS)
            if score >= 3:
                hits.append((i, score, text))
        name = os.path.basename(path)
        print(f"\n===== {name}: {len(doc)} pages, {len(hits)} candidate pages =====")
        for i, score, text in hits[:3]:
            print(f"\n--- page {i} (keyword hits {score}) ---")
            print(" ".join(text.split())[:1200])
        doc.close()


if __name__ == "__main__":
    main()
