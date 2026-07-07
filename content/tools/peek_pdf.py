#!/usr/bin/env python3
"""Peek at a PDF's text layout: page count, and text of selected pages.

Usage: python peek_pdf.py <pdf> [page_start] [page_end]
Reads only, prints to stdout. Used to design parsers before extraction.
"""
import sys

import fitz


def main() -> None:
    path = sys.argv[1]
    doc = fitz.open(path)
    n = doc.page_count
    print(f"=== {path} ===")
    print(f"page_count={n}")
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    end = int(sys.argv[3]) if len(sys.argv) > 3 else min(n, start + 3)
    for i in range(start, min(end, n)):
        page = doc[i]
        text = page.get_text()
        print(f"\n----- PAGE {i} (chars={len(text)}) -----")
        print(text)
    doc.close()


if __name__ == "__main__":
    main()
