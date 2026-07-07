"""Scrape the Brainscape "GRE Physics" class into the examples pool.

The deck pages are public and fully server rendered, so a plain HTTP GET plus
an HTML parse captures every card. No login, no JavaScript, no browser.

Each card is a ``div.flashcard-row`` with ``id="card-<id>"`` and a ``.header``
number, in one of two layouts that both appear in the raw HTML:

  * full cards: ``.flashcard-contents.question-contents`` and
    ``.answer-contents``, with the real content under ``.preview-html`` (the
    leading Q/A label lives in ``.flashcard-type-indicator`` and is skipped).
  * compact cards: ``.flashcard-row.thin-card`` with ``.question-content`` and
    ``.answer-content`` (light markdown carried over from the source).

Text handling keeps math intact: LaTeX-style ``\\( ... \\)`` delimiters and
unicode symbols are preserved, and only the markdown-escaped underscore
``\\_`` (fill-in-the-blank) is unescaped for readability.

Output, written under ``content/examples/brainscape/``:
  * ``<deck-slug>.json``  array of ``{id, question, answer}``
  * ``index.json``        deck -> card count summary

Role: examples pool (few-shot style and quality reference) and deck-candidate.
Non-ETS, not corpus. An ETS-dedup scan is required before any card enters a
shipped deck or a gold set.

Stdlib fetch (urllib) plus BeautifulSoup for parsing. Polite delay between the
ten requests. Re-running overwrites deck files; ``--deck`` re-runs one deck and
keeps the rest of the index intact.

Run:
    conda run -n pgrep-ai python content/tools/scrape_brainscape.py
    conda run -n pgrep-ai python content/tools/scrape_brainscape.py --deck electromagnetism
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from urllib.parse import urlparse

from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # content/
OUT_DIR = os.path.join(ROOT, "examples", "brainscape")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DELAY_S = 1.5
TIMEOUT_S = 30

# (name, url, expected card count). Order matches the class.
DECKS = [
    (
        "Classical Mechanics I",
        "https://www.brainscape.com/flashcards/classical-mechanics-i-18959662/packs/23065388",
        107,
    ),
    (
        "Classical Mechanics II",
        "https://www.brainscape.com/flashcards/classical-mechanics-ii-19046742/packs/23065388",
        65,
    ),
    (
        "Electromagnetism",
        "https://www.brainscape.com/flashcards/electromagnetism-18959664/packs/23065388",
        114,
    ),
    (
        "Optics and Wave Phenomena",
        "https://www.brainscape.com/flashcards/optics-and-wave-phenomena-18959666/packs/23065388",
        64,
    ),
    (
        "Thermodynamics and Statistical Mechanics",
        "https://www.brainscape.com/flashcards/thermodynamics-and-statistical-mechanics-18959668/packs/23065388",
        76,
    ),
    (
        "Quantum Mechanics",
        "https://www.brainscape.com/flashcards/quantum-mechanics-18959672/packs/23065388",
        69,
    ),
    (
        "Atomic Physics",
        "https://www.brainscape.com/flashcards/atomic-physics-18959675/packs/23065388",
        62,
    ),
    (
        "Special Relativity",
        "https://www.brainscape.com/flashcards/special-relativity-18959676/packs/23065388",
        48,
    ),
    (
        "Laboratory Methods",
        "https://www.brainscape.com/flashcards/laboratory-methods-18959678/packs/23065388",
        56,
    ),
    (
        "Specialized Topics",
        "https://www.brainscape.com/flashcards/specialized-topics-18959681/packs/23065388",
        86,
    ),
]

BLOCK_TAGS = [
    "p",
    "div",
    "section",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "table",
    "tr",
]


def deck_slug(url: str) -> str:
    """`.../flashcards/classical-mechanics-i-18959662/...` -> `classical-mechanics-i`."""
    seg = urlparse(url).path.split("/")[2]
    return re.sub(r"-\d+$", "", seg)


def clean_text(s: str) -> str:
    """Normalize whitespace, keep math. Only unescape the markdown ``\\_``."""
    s = s.replace("\xa0", " ")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\\_", "_")  # fill-in-the-blank; leave \( \) and other math alone
    lines = [re.sub(r"[ \t]{2,}", " ", ln).rstrip() for ln in s.split("\n")]
    s = "\n".join(lines)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def strip_qa_label(s: str) -> str:
    """Drop a lone leading ``Q`` or ``A`` label line if one slipped through."""
    return re.sub(r"^\s*[QA]\s*\n+", "", s)


def html_to_text(el) -> str:
    """Block-aware text: sentences stay intact, block elements become breaks."""
    if el is None:
        return ""
    frag = BeautifulSoup(str(el), "html.parser")
    for br in frag.find_all("br"):
        br.replace_with("\n")
    for li in frag.find_all("li"):
        li.insert(0, "\u2022 ")
        li.insert_before("\n")
    for blk in frag.find_all(BLOCK_TAGS):
        blk.insert_before("\n\n")
    return strip_qa_label(clean_text(frag.get_text()))


def face_images(container) -> list[str]:
    if container is None:
        return []
    urls = []
    for img in container.find_all("img"):
        src = (img.get("src") or img.get("data-src") or "").strip()
        if src:
            urls.append(src)
    return urls


def append_images(text: str, images: list[str]) -> str:
    if not images:
        return text
    marks = "\n".join(f"[image: {u}]" for u in images)
    return f"{text}\n\n{marks}" if text else marks


def extract_side(row, kind: str, side: str) -> str:
    """kind is 'full' or 'thin'; side is 'question' or 'answer'."""
    if kind == "thin":
        face = row.select_one(f".card-face.{side}")
        src = face.select_one(f".{side}-content") if face else None
    else:
        face = row.select_one(f".{side}-contents")
        src = None
        if face is not None:
            src = face.select_one(".preview-html") or face.select_one(".main-fields-container")
    text = html_to_text(src if src is not None else face)
    return append_images(text, face_images(face))


def parse_cards(html: str, slug: str) -> tuple[list[dict], int | None, int]:
    """Return (cards, declared_count, duplicate_rows)."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.flashcard-row[id^=card-]")

    declared = None
    cc = soup.select_one(".card-count")
    if cc is not None:
        m = re.search(r"(\d+)", cc.get_text())
        declared = int(m.group(1)) if m else None

    cards: list[dict] = []
    seen: set[str] = set()
    dupes = 0
    for row in rows:
        rid = row.get("id", "")
        if rid in seen:
            dupes += 1
            continue
        seen.add(rid)
        kind = "thin" if "thin-card" in row.get("class", []) else "full"
        num = len(cards) + 1
        cards.append(
            {
                "id": f"{slug}-{num:03d}",
                "question": extract_side(row, kind, "question"),
                "answer": extract_side(row, kind, "answer"),
            }
        )
    return cards, declared, dupes


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", "replace")


def load_index() -> dict:
    path = os.path.join(OUT_DIR, "index.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


def write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deck", help="only scrape decks whose slug contains this substring")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    index = load_index()
    rows_out = []

    for name, url, expected in DECKS:
        slug = deck_slug(url)
        if args.deck and args.deck not in slug:
            continue

        try:
            html = fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"[fail] {slug}: fetch error: {e}")
            rows_out.append((name, 0, expected, None, 0, "FETCH FAILED"))
            time.sleep(DELAY_S)
            continue

        cards, declared, dupes = parse_cards(html, slug)
        got = len(cards)
        empty = sum(1 for c in cards if not c["question"] or not c["answer"])

        write_json(os.path.join(OUT_DIR, f"{slug}.json"), cards)
        index[slug] = {
            "name": name,
            "url": url,
            "cards": got,
            "expected": expected,
        }

        if got == expected:
            status = "ok"
        elif got < expected:
            status = f"SHORT by {expected - got}"
        else:
            status = f"over by {got - expected}"
        note = status
        if dupes:
            note += f", {dupes} dup rows"
        if empty:
            note += f", {empty} empty side(s)"
        if declared is not None and declared != got:
            note += f", page says {declared}"

        rows_out.append((name, got, expected, declared, empty, note))
        print(f"[deck] {slug}: got={got} expected={expected} declared={declared} -> {note}")
        time.sleep(DELAY_S)

    write_json(os.path.join(OUT_DIR, "index.json"), index)

    print("\n=== Brainscape GRE Physics: capture report ===")
    print(f"{'Deck':40} {'Got':>4} {'Exp':>4} {'Web':>4}  Notes")
    print("-" * 78)
    tot_got = tot_exp = 0
    short = []
    for name, got, expected, declared, _empty, note in rows_out:
        tot_got += got
        tot_exp += expected
        web = "-" if declared is None else str(declared)
        print(f"{name[:40]:40} {got:>4} {expected:>4} {web:>4}  {note}")
        if got < expected:
            short.append(deck_slug(next(u for n, u, _ in DECKS if n == name)))
    print("-" * 78)
    print(f"{'TOTAL':40} {tot_got:>4} {tot_exp:>4}")
    if short:
        print("\nDecks needing a re-run:")
        for s in short:
            print(f"  conda run -n pgrep-ai python content/tools/scrape_brainscape.py --deck {s}")
    else:
        print("\nAll decks captured at or above expected counts.")


if __name__ == "__main__":
    main()
