"""The two retrieval baselines the AI must beat side by side (L4.0d).

The spec requires generation to beat a simple baseline, scored blind against the
same gold set (``docs_pgrep/ai/cutoffs-and-baselines.md`` section 4). Two named
baselines, both over the same chunked corpus the RAG index is built from:

  - Keyword (baseline A): FTS5 BM25 term-frequency retrieval.
  - Vector (baseline B): dense retrieval with the local ONNX bge model over the
    sqlite-vec index, the same embeddings the toolchain smoke test exercises.

A baseline's "generated item" for scoring is its top retrieved passage: the
honest "you did not need AI, search would do" comparison. Each baseline exposes
``top(query, k)`` and ``candidate(target)``, which shapes a passage into the same
candidate dict the scorer consumes, so baseline and AI items are graded the same
way.

This reads the corpus index only. It never touches gold, held-out, or Tier-3
material.

Run (smoke test both baselines on a query):
    conda run -n pgrep-ai python content/tools/baselines.py "angular momentum conservation"
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3

import _ai_path

_ai_path.add_ai_core()

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)

from pgrep.ai import retrieval  # noqa: E402

DEFAULT_DB = os.path.join(CONTENT, "index", "corpus.db")

# FTS5 MATCH is a query language, so a raw natural-language string with quotes or
# punctuation can break it. Reduce a query to bag-of-words OR over its terms.
_WORD = re.compile(r"[A-Za-z0-9]+")
_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with",
         "is", "are", "be", "at", "as", "by", "from", "that", "this", "it",
         "what", "which", "how", "when", "where", "why", "does"}


def _fts_query(text: str, max_terms: int = 24) -> str:
    terms = [w.lower() for w in _WORD.findall(text)]
    terms = [t for t in terms if t not in _STOP and len(t) > 1]
    seen: list[str] = []
    for t in terms:
        if t not in seen:
            seen.append(t)
        if len(seen) >= max_terms:
            break
    return " OR ".join(f'"{t}"' for t in seen)


def _passage(rank: int, chunk_id: str, source_ref: str, source_title: str,
             text: str, score: float) -> dict:
    return {
        "rank": rank,
        "chunk_id": chunk_id,
        "source_ref": source_ref,
        "source_title": source_title,
        "text": text,
        "score": score,
    }


class KeywordBaseline:
    """FTS5 BM25 over the corpus chunks, rebuilt in memory from the index."""

    name = "keyword"

    def __init__(self, corpus_db: str = DEFAULT_DB):
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE VIRTUAL TABLE fts USING fts5("
            "text, chunk_id UNINDEXED, source_ref UNINDEXED, source_title UNINDEXED)"
        )
        src = sqlite3.connect(corpus_db)
        try:
            rows = src.execute(
                "SELECT text, chunk_id, source_ref, source_title FROM chunks"
            ).fetchall()
        finally:
            src.close()
        self.db.executemany(
            "INSERT INTO fts(text, chunk_id, source_ref, source_title) VALUES (?,?,?,?)",
            rows,
        )
        self.db.commit()

    def top(self, query: str, k: int = 5) -> list[dict]:
        fts_q = _fts_query(query)
        if not fts_q:
            return []
        # bm25() is smaller for a better match, so ascending gives best first.
        rows = self.db.execute(
            "SELECT chunk_id, source_ref, source_title, text, bm25(fts) AS score "
            "FROM fts WHERE fts MATCH ? ORDER BY score LIMIT ?",
            (fts_q, k),
        ).fetchall()
        out = []
        for rank, (chunk_id, source_ref, source_title, text, score) in enumerate(rows, start=1):
            # Report a higher-is-better relevance so systems read consistently.
            out.append(_passage(rank, chunk_id, source_ref, source_title, text, -float(score)))
        return out

    def close(self) -> None:
        self.db.close()


class VectorBaseline:
    """Dense retrieval with the local ONNX bge model over the sqlite-vec index."""

    name = "vector"

    def __init__(self, corpus_db: str = DEFAULT_DB):
        self.conn = retrieval.open_index(corpus_db)

    def top(self, query: str, k: int = 5) -> list[dict]:
        out = []
        for rank, r in enumerate(retrieval.search(query, k=k, conn=self.conn), start=1):
            out.append(_passage(rank, r.chunk_id, r.source_ref, r.source_title,
                                r.text, r.score))
        return out

    def close(self) -> None:
        self.conn.close()


def candidate(baseline, target: dict) -> dict:
    """Shape a baseline's top passage into a scorer candidate for a target.

    ``target`` carries at least ``id`` and ``query`` (the topic or the gold
    item's prompt), and ``kind`` (card or problem). The candidate mirrors an AI
    item: its answer text is the retrieved passage, with the passage's source_ref
    as provenance. A miss yields a refusal-shaped candidate.
    """
    hits = baseline.top(target["query"], k=1)
    kind = target.get("kind", "card")
    base = {
        "system": baseline.name,
        "target_id": target.get("id"),
        "kind": kind,
        "blueprint_area": target.get("blueprint_area"),
        "topic": target.get("topic"),
    }
    if not hits:
        base.update({"refused": True, "text": "", "source_ref": None})
        return base
    top = hits[0]
    base.update({
        "refused": False,
        "text": top["text"],
        "source_ref": top["source_ref"],
        "retrieval_score": top["score"],
    })
    return base


def make_baselines(corpus_db: str = DEFAULT_DB) -> dict[str, object]:
    return {"keyword": KeywordBaseline(corpus_db), "vector": VectorBaseline(corpus_db)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Smoke-test the keyword and vector baselines.")
    ap.add_argument("query", nargs="?", default="angular momentum conservation")
    ap.add_argument("-k", "--top-k", type=int, default=3)
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()

    baselines = make_baselines(args.db)
    try:
        for name, bl in baselines.items():
            print(f"\n=== {name} baseline ===  query: {args.query!r}")
            hits = bl.top(args.query, args.top_k)
            if not hits:
                print("   (no results)")
            for h in hits:
                print(f"[{h['rank']}] score={h['score']:.3f}  {h['source_ref']}")
                print(f"    {' '.join(h['text'].split())[:140]} ...")
    finally:
        for bl in baselines.values():
            bl.close()


if __name__ == "__main__":
    main()
