#!/usr/bin/env python3
"""Profile a PDF: per-page char count, image count, to find text vs scanned pages.

Usage: python pdf_profile.py <pdf>
Reads only, prints to stdout.
"""
import sys

import fitz


def main() -> None:
    path = sys.argv[1]
    doc = fitz.open(path)
    print(f"=== {path} === pages={doc.page_count}")
    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text()
        nchars = len(text.strip())
        nimg = len(page.get_images(full=True))
        # first 40 non-space chars as a hint
        hint = " ".join(text.split())[:60]
        print(f"p{i:03d} chars={nchars:5d} imgs={nimg} | {hint}")
    doc.close()


if __name__ == "__main__":
    main()
