"""Query the pgrep corpus RAG index.

Embeds a query with BAAI/bge-small-en-v1.5 (the same model used to build the
index, with the recommended retrieval instruction on the query side only),
runs a k nearest neighbor search over the sqlite-vec vec0 table, and prints
the top matches with their source_ref (title, page, section) and a snippet.

Run:
    conda run -n pgrep-ai python content/tools/query_index.py "angular momentum conservation"
    conda run -n pgrep-ai python content/tools/query_index.py -k 3 "partition function"
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import textwrap

import sqlite_vec
from sentence_transformers import SentenceTransformer

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
DB_PATH = os.path.join(CONTENT, "index", "corpus.db")

MODEL_NAME = "BAAI/bge-small-en-v1.5"
# bge-small-en-v1.5 recommends this instruction on the query side only.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def connect(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        raise SystemExit(f"[error] no index at {db_path}; run build_index.py first")
    db = sqlite3.connect(db_path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def search(db: sqlite3.Connection, model: SentenceTransformer, query: str,
           k: int = 5) -> list[dict]:
    qvec = model.encode([QUERY_INSTRUCTION + query], normalize_embeddings=True,
                        convert_to_numpy=True)[0].astype("float32")
    rows = db.execute(
        """
        SELECT c.chunk_id, c.source_title, c.source_file, c.page, c.page_end,
               c.section, c.source_ref, c.text, v.distance
        FROM vec_chunks v
        JOIN chunks c ON c.rowid = v.rowid
        WHERE v.embedding MATCH ? AND k = ?
        ORDER BY v.distance
        """,
        (qvec.tobytes(), k),
    ).fetchall()
    results = []
    for (chunk_id, title, file, page, page_end, section, source_ref, text,
         distance) in rows:
        # Vectors are normalized, so cosine similarity = 1 - L2^2 / 2.
        cosine = 1.0 - (distance * distance) / 2.0
        results.append({
            "chunk_id": chunk_id, "source_title": title, "source_file": file,
            "page": page, "page_end": page_end, "section": section,
            "source_ref": source_ref, "text": text, "score": cosine,
        })
    return results


def snippet(text: str, width: int = 240) -> str:
    text = " ".join(text.split())
    if len(text) > width:
        text = text[:width].rsplit(" ", 1)[0] + " ..."
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="Query the pgrep corpus RAG index.")
    ap.add_argument("query", help="natural language query")
    ap.add_argument("-k", "--top-k", type=int, default=5)
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    db = connect(args.db)
    model = SentenceTransformer(MODEL_NAME)

    results = search(db, model, args.query, args.top_k)
    print(f'query: "{args.query}"  (top {args.top_k})\n')
    for rank, r in enumerate(results, start=1):
        print(f"[{rank}] score={r['score']:.3f}  {r['source_ref']}")
        print(f"    chunk_id: {r['chunk_id']}")
        for line in textwrap.wrap(snippet(r["text"]), width=96):
            print(f"    {line}")
        print()
    db.close()


if __name__ == "__main__":
    main()
