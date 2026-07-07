"""Rasterize the CWRU flashcard SVGs to PNG for viewing and vision reading.

The SVGs store text as outlined glyphs (no <text> tags), so plain text
extraction fails. PyMuPDF renders the glyph outlines faithfully (verified on
CM and QM cards, including subscripts, Greek, and inequalities), so it is the
rasterizer here. Runs on the pgrep-ai env's `python` (has PyMuPDF).

Reads examples/cwru/cards.json, writes examples/cwru/png/<id>-q.png and
<id>-a.png. Idempotent: existing non-empty PNGs are skipped. 2x zoom gives a
720x432 image, legible for a vision model.

Run:
    conda run -n pgrep-ai python content/tools/rasterize_cwru.py
"""

from __future__ import annotations

import json
import os

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CWRU = os.path.join(ROOT, "examples", "cwru")
SVG_DIR = os.path.join(CWRU, "svg")
PNG_DIR = os.path.join(CWRU, "png")
ZOOM = 2.0


def render(svg_name: str, png_name: str) -> str:
    src = os.path.join(SVG_DIR, svg_name)
    dst = os.path.join(PNG_DIR, png_name)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return "skip"
    try:
        doc = fitz.open(src)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM))
        pix.save(dst)
        doc.close()
    except Exception as e:  # noqa: BLE001
        print(f"[fail] {svg_name}: {e}")
        return "fail"
    return "ok"


def main() -> None:
    os.makedirs(PNG_DIR, exist_ok=True)
    cards = json.load(open(os.path.join(CWRU, "cards.json")))
    counts = {"ok": 0, "skip": 0, "fail": 0}
    for c in cards:
        counts[render(c["question_svg"], c["question_png"])] += 1
        counts[render(c["answer_svg"], c["answer_png"])] += 1
    print(f"[png] rendered={counts['ok']} skipped={counts['skip']} failed={counts['fail']}")
    have = len([n for n in os.listdir(PNG_DIR) if n.endswith(".png")])
    print(f"[png] {have} png files on disk (expect {2 * len(cards)})")


if __name__ == "__main__":
    main()
