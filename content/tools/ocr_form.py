#!/usr/bin/env python3
"""Column-aware OCR for scanned ETS forms (GR8677, GR9277, GR9677).

Each printed page is two columns; question numbers sit in a narrow left
margin, so we render each column separately and OCR with Tesseract PSM 4
("single column of text of variable sizes"), which keeps `N.` attached to
its stem. Reads PDFs only; used by parse_ets_items.py.
"""
from __future__ import annotations

import io
import sys

import fitz
import pytesseract
from PIL import Image


def ocr_clip(page, x0f, x1f, dpi=300, psm=4) -> str:
    w, h = page.rect.width, page.rect.height
    clip = fitz.Rect(w * x0f, 0, w * x1f, h)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, config=f"--psm {psm}")


def ocr_page_columns(page, split=0.5, dpi=300, psm=4) -> str:
    left = ocr_clip(page, 0.0, split, dpi, psm)
    right = ocr_clip(page, split, 1.0, dpi, psm)
    return left + "\n" + right


def ocr_pages(pdf_path: str, pages: list[int], split=0.5, dpi=300) -> str:
    doc = fitz.open(pdf_path)
    parts = []
    for i in pages:
        parts.append(f"\n<<<PAGE {i}>>>\n")
        parts.append(ocr_page_columns(doc[i], split=split, dpi=dpi))
    doc.close()
    return "".join(parts)


if __name__ == "__main__":
    # quick scan: OCR left column of a page range to locate the test start
    pdf = sys.argv[1]
    lo, hi = int(sys.argv[2]), int(sys.argv[3])
    doc = fitz.open(pdf)
    for i in range(lo, min(hi, doc.page_count)):
        txt = ocr_clip(doc[i], 0.0, 0.5, dpi=200)
        head = " ".join(txt.split())[:90]
        print(f"p{i:03d} | {head}")
    doc.close()
