"""Build the pgrep corpus RAG index over the tier1-open PDFs.

What it does, end to end:
  1. Extracts text page by page with PyMuPDF (fitz).
  2. Resolves a best-effort section heading for every page (TOC bookmarks
     when the PDF has them, otherwise bold numbered-section detection plus a
     running-header fallback, carried forward across pages).
  3. Splits each source into passages of a few hundred tokens with ~15
     percent overlap, biased to break on page boundaries so each passage
     keeps a clean page anchor.
  4. Embeds every passage with BAAI/bge-small-en-v1.5 (normalized).
  5. Stores the vectors in a sqlite-vec vec0 virtual table and the chunk
     text plus a stable source_ref in a companion table.

Provenance is the point: every chunk carries source_title, source_file,
page, and section, and a formatted source_ref, so any downstream generated
item can cite a real location in a real book.

Token budget note. bge-small-en-v1.5 embeds at most 512 tokens, so passages
target ~500 model tokens and are hard-capped there. That sits at the low end
of a 500 to 800 range, chosen so no passage is silently truncated when
embedded. Length is measured with the model's own tokenizer.

Idempotent: the target db is deleted and rebuilt from scratch on every run.

Run:
    conda run -n pgrep-ai python content/tools/build_index.py
    conda run -n pgrep-ai python content/tools/build_index.py --dry-run
    conda run -n pgrep-ai python content/tools/build_index.py --limit-pages 40
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass

import fitz
import numpy as np
import sqlite_vec
from sentence_transformers import SentenceTransformer

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)  # content/
CORPUS_DIR = os.path.join(CONTENT, "corpus", "tier1-open")
INDEX_DIR = os.path.join(CONTENT, "index")
DB_PATH = os.path.join(INDEX_DIR, "corpus.db")

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_MAX_TOKENS = 512
# Kept a little under the 512 model limit so a passage still fits once its
# segments are joined and re-tokenized (token counts are not exactly additive).
CHUNK_MAX_TOKENS = 480
CHUNK_MIN_TOKENS = 320
OVERLAP_TOKENS = 75
MIN_TAIL_WORDS = 12  # a shorter passage is folded into a neighbor, not stored alone

# The tier1-open sources, in reading order. Astronomy is optional: the file
# may not be present, in which case it is skipped rather than failing.
SOURCES = [
    {"file": "openstax-vol1.pdf", "title": "OpenStax University Physics Volume 1", "sid": "openstax-vol1"},
    {"file": "openstax-vol2.pdf", "title": "OpenStax University Physics Volume 2", "sid": "openstax-vol2"},
    {"file": "openstax-vol3.pdf", "title": "OpenStax University Physics Volume 3", "sid": "openstax-vol3"},
    {"file": "fitzpatrick-newtonian-dynamics.pdf", "title": "Fitzpatrick: Newtonian Dynamics", "sid": "fitz-newtonian"},
    {"file": "fitzpatrick-quantum-mechanics.pdf", "title": "Fitzpatrick: Quantum Mechanics", "sid": "fitz-quantum"},
    {"file": "fitzpatrick-thermo-statmech.pdf", "title": "Fitzpatrick: Thermodynamics and Statistical Mechanics", "sid": "fitz-thermo"},
    {"file": "openstax-astronomy.pdf", "title": "OpenStax Astronomy 2e", "sid": "openstax-astronomy", "optional": True},
]

# --- heading detection -----------------------------------------------------

SEC_NUM = re.compile(r"^(\d{1,2})\.(\d{1,2})\s+(.{1,70})$")
NUM_ONLY = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?$")
PAGENUM = re.compile(r"^\d{1,4}$")
TITLEISH = re.compile(r"^[A-Z][A-Za-z].{1,60}$")
BAD_TAIL = (".", ",", ";", ":")
STOP = {"a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with",
        "from", "by", "at", "as", "its", "is", "are", "be", "into", "through"}
LABEL_EXACT = {"here", "solution", "significance", "strategy", "proof", "note",
               "contents", "glossary", "index", "preface", "summary", "abstract"}
LABEL_PREFIX = ("signi", "example ", "check your", "problem-solving")


def _title_case_ok(title: str) -> bool:
    """A section title reads as a title, not a sentence fragment."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", title)
    sig = [w for w in words if len(w) >= 3 and w.lower() not in STOP]
    if not sig:
        return True
    caps = sum(1 for w in sig if w[0].isupper())
    return caps / len(sig) >= 0.6


def _is_label(title: str) -> bool:
    t = title.strip().lower()
    if t in LABEL_EXACT:
        return True
    return t.startswith(LABEL_PREFIX)


def _clean_section(major: str, minor: str, title: str) -> str | None:
    if int(minor) > 15:
        return None
    title = re.sub(r"\s+", " ", title).strip()
    if not title or title[-1] in BAD_TAIL or not title[0].isupper():
        return None
    if len(title) > 60 or len(title.split()) > 8:
        return None
    if _is_label(title) or not _title_case_ok(title):
        return None
    return f"{major}.{minor} {title}"


def _page_lines(page: fitz.Page) -> list[tuple[float, float, bool, str]]:
    """(y, max_font_size, is_bold, text) per layout line, top to bottom."""
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = re.sub(r"\s+", " ", " ".join(s["text"] for s in spans)).strip()
            size = max(s["size"] for s in spans)
            bold = any(int(s["flags"]) & 16 for s in spans)
            lines.append((line["bbox"][1], size, bold, text))
    lines.sort()
    return lines


def _detect_heading(lines: list[tuple[float, float, bool, str]]) -> str | None:
    """Best-effort section heading visible on a page, or None."""
    for i, (_y, _size, bold, text) in enumerate(lines):
        if not bold:
            continue
        m = SEC_NUM.match(text)
        if m:
            sec = _clean_section(m.group(1), m.group(2), m.group(3))
            if sec:
                return sec
        mo = NUM_ONLY.match(text)
        if mo and i + 1 < len(lines):
            sec = _clean_section(mo.group(1), mo.group(2), lines[i + 1][3])
            if sec:
                return sec
    # Running-header chapter title: a title line paired with a bare page number.
    top = [t for _y, _s, _b, t in lines[:3]]
    for a, b in ((0, 1), (1, 0)):
        if len(top) > max(a, b) and TITLEISH.match(top[a]) and PAGENUM.match(top[b]):
            if top[a][-1] not in BAD_TAIL and not _is_label(top[a]):
                return top[a]
    return None


def _toc_sections(doc: fitz.Document) -> dict[int, str] | None:
    """Map each 0-based page to its section from TOC bookmarks, if usable."""
    toc = doc.get_toc()
    if len(toc) < 5:
        return None
    entries = sorted(((p, title.strip()) for _lvl, title, p in toc if p >= 1))
    if not entries:
        return None
    mapping: dict[int, str] = {}
    idx = 0
    cur = None
    for page0 in range(len(doc)):
        page1 = page0 + 1
        while idx < len(entries) and entries[idx][0] <= page1:
            cur = entries[idx][1]
            idx += 1
        if cur:
            mapping[page0] = cur
    return mapping


def page_headings(doc: fitz.Document) -> list[str | None]:
    """Resolve a heading for every page, carried forward across gaps."""
    toc_map = _toc_sections(doc)
    headings: list[str | None] = []
    prev: str | None = None
    for page0 in range(len(doc)):
        if toc_map is not None:
            prev = toc_map.get(page0, prev)
        else:
            found = _detect_heading(_page_lines(doc[page0]))
            if found:
                prev = found
        headings.append(prev)
    return headings


# --- text extraction and chunking ------------------------------------------

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'\[])")


def clean_text(raw: str) -> str:
    """Join soft-hyphenated line breaks and collapse layout whitespace."""
    raw = raw.replace("\u00ad", "")
    raw = re.sub(r"-\n(?=[a-z])", "", raw)
    raw = re.sub(r"\s*\n\s*", " ", raw)
    return re.sub(r"[ \t]+", " ", raw).strip()


def split_sentences(text: str) -> list[str]:
    out = []
    for part in SENT_SPLIT.split(text):
        part = part.strip()
        if part:
            out.append(part)
    return out


@dataclass
class Segment:
    page: int  # 0-based page index
    section: str | None
    text: str
    tokens: int


@dataclass
class Chunk:
    sid: str
    title: str
    file: str
    page_start: int  # 1-based
    page_end: int  # 1-based
    section: str | None
    text: str

    def chunk_id(self, seq: int) -> str:
        return f"{self.sid}#p{self.page_start:04d}#c{seq:03d}"

    def source_ref(self) -> str:
        if self.page_end > self.page_start:
            loc = f"pp. {self.page_start}-{self.page_end}"
        else:
            loc = f"p. {self.page_start}"
        ref = f"{self.title}, {loc}"
        if self.section:
            ref += f", \u00a7{self.section}"
        return ref


def count_tokens(tokenizer, text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))


def build_segments(doc: fitz.Document, headings: list[str | None], tokenizer,
                   limit_pages: int | None) -> list[Segment]:
    segments: list[Segment] = []
    n_pages = len(doc) if limit_pages is None else min(limit_pages, len(doc))
    for page0 in range(n_pages):
        text = clean_text(doc[page0].get_text("text"))
        if len(text) < 40:
            continue
        section = headings[page0]
        for sent in split_sentences(text):
            tok = count_tokens(tokenizer, sent)
            if tok == 0:
                continue
            if tok <= CHUNK_MAX_TOKENS:
                segments.append(Segment(page0, section, sent, tok))
            else:
                # A single over-long sentence (long equation run). Hard-split
                # it on words so no segment exceeds the model window.
                words = sent.split()
                step = max(1, int(len(words) * CHUNK_MAX_TOKENS / tok))
                for i in range(0, len(words), step):
                    piece = " ".join(words[i:i + step])
                    segments.append(Segment(page0, section, piece,
                                            count_tokens(tokenizer, piece)))
    return segments


def chunk_segments(segments: list[Segment], src: dict) -> list[Chunk]:
    """Sliding window over page-tagged segments with page-boundary bias."""
    chunks: list[Chunk] = []
    i = 0
    n = len(segments)
    while i < n:
        window: list[Segment] = []
        tokens = 0
        j = i
        while j < n:
            seg = segments[j]
            if window and tokens + seg.tokens > CHUNK_MAX_TOKENS:
                break
            window.append(seg)
            tokens += seg.tokens
            j += 1
            at_page_break = j < n and segments[j].page != seg.page
            if tokens >= CHUNK_MIN_TOKENS and at_page_break:
                break
            if tokens >= CHUNK_MAX_TOKENS:
                break
        if not window:
            break
        first = window[0]
        chunks.append(Chunk(
            sid=src["sid"], title=src["title"], file=src["file"],
            page_start=first.page + 1, page_end=window[-1].page + 1,
            section=first.section, text=" ".join(s.text for s in window),
        ))
        if j >= n:
            break
        # Step back over trailing segments to create ~15 percent overlap,
        # but always make forward progress past the window start.
        back = 0
        overlap = 0
        while back < len(window) - 1 and overlap < OVERLAP_TOKENS:
            overlap += window[-1 - back].tokens
            back += 1
        i = max(i + 1, j - back)
    return _absorb_tiny(chunks)


def _absorb_tiny(chunks: list[Chunk]) -> list[Chunk]:
    """Fold stray fragments (a page number, a lone label) into a neighbor so
    every passage is substantial. Tiny chunks only appear at page edges."""
    merged: list[Chunk] = []
    for ch in chunks:
        if merged and len(ch.text.split()) < MIN_TAIL_WORDS:
            prev = merged[-1]
            prev.text = f"{prev.text} {ch.text}"
            prev.page_end = max(prev.page_end, ch.page_end)
        else:
            merged.append(ch)
    if len(merged) >= 2 and len(merged[0].text.split()) < MIN_TAIL_WORDS:
        head, nxt = merged[0], merged[1]
        nxt.text = f"{head.text} {nxt.text}"
        nxt.page_start = min(head.page_start, nxt.page_start)
        nxt.section = head.section or nxt.section
        merged.pop(0)
    return merged


# --- storage ---------------------------------------------------------------

def open_db(path: str, dim: int) -> sqlite3.Connection:
    if os.path.exists(path):
        os.remove(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.execute("""
        CREATE TABLE chunks (
            rowid        INTEGER PRIMARY KEY,
            chunk_id     TEXT UNIQUE,
            source_title TEXT NOT NULL,
            source_file  TEXT NOT NULL,
            page         INTEGER NOT NULL,
            page_end     INTEGER NOT NULL,
            section      TEXT,
            source_ref   TEXT NOT NULL,
            text         TEXT NOT NULL
        )
    """)
    db.execute("CREATE INDEX chunks_source ON chunks(source_file)")
    db.execute(f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{dim}])")
    db.execute("""
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    return db


def store(db: sqlite3.Connection, chunks: list[Chunk], vectors: np.ndarray) -> None:
    seq_by_page: Counter = Counter()
    rows = []
    vrows = []
    for rowid, (ch, vec) in enumerate(zip(chunks, vectors), start=1):
        key = (ch.sid, ch.page_start)
        seq = seq_by_page[key]
        seq_by_page[key] += 1
        rows.append((rowid, ch.chunk_id(seq), ch.title, ch.file, ch.page_start,
                     ch.page_end, ch.section, ch.source_ref(), ch.text))
        vrows.append((rowid, vec.astype("float32").tobytes()))
    db.executemany(
        "INSERT INTO chunks(rowid, chunk_id, source_title, source_file, page, "
        "page_end, section, source_ref, text) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    db.executemany("INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)", vrows)
    db.commit()


# --- driver ----------------------------------------------------------------

def resolve_sources() -> list[dict]:
    present = []
    for src in SOURCES:
        path = os.path.join(CORPUS_DIR, src["file"])
        if os.path.exists(path):
            present.append(src)
        elif not src.get("optional"):
            raise SystemExit(f"[error] required source missing: {src['file']}")
        else:
            print(f"[skip] optional source not present: {src['file']}")
    return present


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the pgrep corpus RAG index.")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--dry-run", action="store_true",
                    help="extract and chunk only; no embedding, no db write")
    ap.add_argument("--limit-pages", type=int, default=None,
                    help="cap pages per source (smoke testing)")
    ap.add_argument("--skip-leakage-check", action="store_true",
                    help="skip the post-build firewall guard (not recommended)")
    args = ap.parse_args()

    sources = resolve_sources()
    t0 = time.time()

    model = None
    tokenizer = None
    dim = 384
    if args.dry_run:
        # A tokenizer is still needed to size chunks. Load the model's only.
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    else:
        print(f"[model] loading {MODEL_NAME}")
        model = SentenceTransformer(MODEL_NAME)
        model.max_seq_length = MODEL_MAX_TOKENS
        tokenizer = model.tokenizer
        get_dim = getattr(model, "get_embedding_dimension", None) or \
            model.get_sentence_embedding_dimension
        dim = get_dim()
    # Sizing calls count tokens directly; lift the tokenizer's own length cap so
    # it does not warn. Embedding truncation stays governed by max_seq_length.
    tokenizer.model_max_length = 1_000_000

    all_chunks: list[Chunk] = []
    per_source: list[tuple[str, int, int]] = []  # title, pages, chunks
    for src in sources:
        path = os.path.join(CORPUS_DIR, src["file"])
        doc = fitz.open(path)
        headings = page_headings(doc)
        segments = build_segments(doc, headings, tokenizer, args.limit_pages)
        chunks = chunk_segments(segments, src)
        used_pages = len(doc) if args.limit_pages is None else min(args.limit_pages, len(doc))
        per_source.append((src["title"], used_pages, len(chunks)))
        all_chunks.extend(chunks)
        print(f"[extract] {src['sid']:>18}: pages={used_pages:<4} chunks={len(chunks)}")
        doc.close()

    total = len(all_chunks)
    toks = [count_tokens(tokenizer, c.text) for c in all_chunks]
    tok_stats = (min(toks), int(sum(toks) / len(toks)), max(toks)) if toks else (0, 0, 0)
    print(f"[chunks] total={total} tokens(min/avg/max)={tok_stats}")

    if args.dry_run:
        print("[dry-run] sample source_refs:")
        for c in all_chunks[:: max(1, total // 8)][:8]:
            print("   ", c.source_ref())
        print(f"[done] dry run in {time.time() - t0:.1f}s")
        return

    print(f"[embed] encoding {total} chunks with normalized bge-small")
    vectors = model.encode(
        [c.text for c in all_chunks],
        batch_size=64,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    db = open_db(args.db, dim)
    store(db, all_chunks, vectors)
    db.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", [
        ("model", MODEL_NAME),
        ("dim", str(dim)),
        ("chunk_max_tokens", str(CHUNK_MAX_TOKENS)),
        ("chunk_min_tokens", str(CHUNK_MIN_TOKENS)),
        ("overlap_tokens", str(OVERLAP_TOKENS)),
        ("total_chunks", str(total)),
        ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
    ])
    db.commit()

    size_mb = os.path.getsize(args.db) / 1e6
    print("\n[report] chunks per source")
    for title, pages, nch in per_source:
        print(f"   {nch:>5}  ({pages:>4} pages)  {title}")
    print(f"[report] total chunks: {total}")
    print(f"[report] index file:   {args.db}  ({size_mb:.1f} MB)")
    print(f"[done] built in {time.time() - t0:.1f}s")
    db.close()

    # Firewall backstop. The index must hold corpus text only, so run the
    # leakage guard now: a broken build fails loudly before anything uses it.
    if not args.skip_leakage_check:
        print("\n[leakage] running the firewall guard on the built index")
        from leakage_check import report as leakage_report
        from leakage_check import run_checks as leakage_run
        if not leakage_report(leakage_run(args.db)):
            raise SystemExit("[error] leakage check failed on the freshly built index")


if __name__ == "__main__":
    main()
