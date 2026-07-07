"""Collect the CWRU "Doc Brown" Physics GRE flashcard set.

Public, no login. Base host http://great.cwru.edu. This script:
  1. reads examples/cwru/data.json (the card index),
  2. builds examples/cwru/cards.json (clean per-card records),
  3. downloads every question and answer SVG using the EXACT [q, a] pairs
     from data.json (filenames vary by category, never assume a prefix),
  4. validates each SVG is non-empty and XML/SVG.

Rasterization to PNG is a separate step (rasterize_cwru.py), because it may
need a different tool depending on the machine.

Stdlib only (urllib), so it runs without extra deps. Polite delay between
requests. Idempotent: existing valid files are skipped.

Run:
    python3 content/tools/fetch_cwru.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # content/
CWRU = os.path.join(ROOT, "examples", "cwru")
SVG_DIR = os.path.join(CWRU, "svg")
SVG_URL = "http://great.cwru.edu/pdf2svg/"
DELAY_S = 0.15


def slugify(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def build_cards(data: list) -> list:
    """One flat record per card, text fields left empty for later."""
    cards = []
    seen: dict[str, int] = {}
    for cat in data:
        cslug = slugify(cat["name"])
        for i, (q, a) in enumerate(cat["qa"], start=1):
            stem = os.path.splitext(q)[0]
            cid = f"{cslug}-{i:02d}"
            seen[stem] = seen.get(stem, 0) + 1
            cards.append(
                {
                    "id": cid,
                    "category": cat["name"],
                    "category_slug": cslug,
                    "question_svg": q,
                    "answer_svg": a,
                    "question_png": f"{cid}-q.png",
                    "answer_png": f"{cid}-a.png",
                    "question_text": "",
                    "answer_text": "",
                }
            )
    dupes = {k: v for k, v in seen.items() if v > 1}
    if dupes:
        print(f"[warn] duplicate question filenames across categories: {dupes}")
    return cards


def valid_svg(path: str) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    with open(path, "rb") as f:
        head = f.read(200).lstrip()
    return head.startswith(b"<?xml") or head.startswith(b"<svg")


def download(name: str) -> str:
    """Return one of ok, skip, fail."""
    dest = os.path.join(SVG_DIR, name)
    if valid_svg(dest):
        return "skip"
    try:
        urllib.request.urlretrieve(SVG_URL + name, dest)
    except Exception as e:  # noqa: BLE001
        print(f"[fail] {name}: {e}")
        return "fail"
    if not valid_svg(dest):
        print(f"[fail] {name}: not valid svg")
        return "fail"
    time.sleep(DELAY_S)
    return "ok"


def main() -> None:
    os.makedirs(SVG_DIR, exist_ok=True)
    data = json.load(open(os.path.join(CWRU, "data.json")))
    cards = build_cards(data)
    json.dump(cards, open(os.path.join(CWRU, "cards.json"), "w"), indent=1)
    print(f"[cards] wrote cards.json with {len(cards)} cards")

    counts = {"ok": 0, "skip": 0, "fail": 0}
    fails = []
    for c in cards:
        for name in (c["question_svg"], c["answer_svg"]):
            r = download(name)
            counts[r] += 1
            if r == "fail":
                fails.append(name)
    print(f"[svg] downloaded={counts['ok']} skipped={counts['skip']} failed={counts['fail']}")
    if fails:
        print(f"[svg] failures: {fails}")
    have = len([n for n in os.listdir(SVG_DIR) if n.endswith(".svg")])
    print(f"[svg] {have} svg files on disk (expect {2 * len(cards)})")


if __name__ == "__main__":
    main()
