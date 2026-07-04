# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Local RAG retrieval over the pgrep corpus index (L4.0c).

Runtime retrieval embeds a query with an ONNX ``BAAI/bge-small-en-v1.5`` backend
through ``fastembed`` (no torch, no sentence-transformers), then runs a k nearest
neighbor search over the ``sqlite-vec`` index that ``build_index.py`` produced.
Only the corpus is ever read. The single network dependency of the whole AI path
is the LLM API elsewhere; retrieval is fully local.

The index vectors were written by ``build_index.py`` using the
``sentence-transformers`` build of the same model, so this module must produce
vectors in the same space. :func:`parity_check` verifies that (cosine ~1.0 for
the same text) and is the gate that must pass before this backend is trusted.
The app never calls the parity gate at runtime (it needs no torch); the offline
harness runs it and records the cosine in the run manifest.

Design: no heavy import at module load. ``fastembed``, ``sqlite_vec`` and
``sentence_transformers`` are imported inside the functions that need them, so an
AI-off app never loads them, and importing this module stays cheap.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Any

MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
# bge-small-en-v1.5 recommends this instruction on the query side only. The
# index (passages) is built without it, matching query_index.py.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

# Parity gate: the ONNX and sentence-transformers builds of the same model must
# agree to within this cosine for retrieval to be trustworthy.
PARITY_MIN_COSINE = 0.99


def default_index_path() -> str:
    """Best-effort path to ``content/index/corpus.db``.

    Resolves ``content/index/corpus.db`` under the repo root inferred from this
    file, then under the current working directory. The app passes an explicit
    path once the index is bundled; this default keeps the harness ergonomic.
    """
    here = os.path.abspath(__file__)
    repo = here
    for _ in range(5):  # ai -> pgrep -> anki -> pylib -> repo root
        repo = os.path.dirname(repo)
    for root in (repo, os.getcwd()):
        candidate = os.path.join(root, "content", "index", "corpus.db")
        if os.path.exists(candidate):
            return candidate
    return os.path.join(repo, "content", "index", "corpus.db")


# --- embedding (ONNX bge via fastembed) ------------------------------------

_EMBEDDER = None


def _embedder() -> Any:
    """The cached fastembed ONNX embedder (loaded once, on first use)."""
    global _EMBEDDER
    if _EMBEDDER is None:
        from fastembed import TextEmbedding  # type: ignore[import-not-found]

        _EMBEDDER = TextEmbedding(model_name=MODEL_NAME)
    return _EMBEDDER


def _l2_normalize(vec: Any) -> Any:
    import numpy as np  # type: ignore[import-not-found]

    vec = np.asarray(vec, dtype="float32")
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec.astype("float32")


def embed_text(text: str) -> Any:
    """Embed a passage-style string (no instruction), L2-normalized float32."""
    vec = next(iter(_embedder().embed([text])))
    return _l2_normalize(vec)


def embed_query(query: str) -> Any:
    """Embed a query, prepending the bge query instruction, L2-normalized."""
    return embed_text(QUERY_INSTRUCTION + query)


# --- index access ----------------------------------------------------------


def open_index(db_path: str | None = None) -> sqlite3.Connection:
    """Open the corpus index with the sqlite-vec extension loaded (read path)."""
    import sqlite_vec  # type: ignore[import-not-found]

    path = db_path or default_index_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"no corpus index at {path}; run build_index.py first")
    db = sqlite3.connect(path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


@dataclass
class RetrievedChunk:
    chunk_id: str
    source_title: str
    source_file: str
    page: int
    page_end: int
    section: str | None
    source_ref: str
    text: str
    score: float

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source_title": self.source_title,
            "source_file": self.source_file,
            "page": self.page,
            "page_end": self.page_end,
            "section": self.section,
            "source_ref": self.source_ref,
            "text": self.text,
            "score": self.score,
        }


# sqlite-vec wants the neighbor count as an explicit ``k = ?`` constraint on the
# vec0 scan; a plain LIMIT is not reliably recognized through a JOIN.
_SEARCH_SQL = """
    SELECT c.chunk_id, c.source_title, c.source_file, c.page, c.page_end,
           c.section, c.source_ref, c.text, v.distance
    FROM vec_chunks v
    JOIN chunks c ON c.rowid = v.rowid
    WHERE v.embedding MATCH ? AND k = ?
    ORDER BY v.distance
"""


def search(query: str, k: int = 5, *, db_path: str | None = None,
           conn: sqlite3.Connection | None = None) -> list[RetrievedChunk]:
    """Top-k corpus chunks for a natural language query, best first.

    Pass an open ``conn`` to reuse a connection across calls, or a ``db_path``
    (or neither, to use the default index). Vectors are normalized, so cosine
    similarity is ``1 - distance**2 / 2``.
    """
    own = conn is None
    db = conn or open_index(db_path)
    try:
        qvec = embed_query(query)
        rows = db.execute(_SEARCH_SQL, (qvec.tobytes(), k)).fetchall()
    finally:
        if own:
            db.close()
    out: list[RetrievedChunk] = []
    for (chunk_id, title, file, page, page_end, section, source_ref, text,
         distance) in rows:
        cosine = 1.0 - (distance * distance) / 2.0
        out.append(RetrievedChunk(chunk_id, title, file, page, page_end, section,
                                  source_ref, text, cosine))
    return out


# --- parity gate (offline only, needs sentence-transformers) ---------------


def sample_index_texts(db_path: str | None = None, n: int = 24) -> list[str]:
    """A spread of chunk texts from the index, for the parity check."""
    db = sqlite3.connect(db_path or default_index_path())
    try:
        total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if total == 0:
            return []
        step = max(1, total // n)
        rows = db.execute(
            "SELECT text FROM chunks WHERE rowid % ? = 0 LIMIT ?", (step, n)
        ).fetchall()
    finally:
        db.close()
    return [t for (t,) in rows]


def parity_check(texts: list[str] | None = None, *, db_path: str | None = None,
                 min_cosine: float = PARITY_MIN_COSINE) -> dict:
    """Verify the ONNX embedder matches the sentence-transformers build.

    Embeds each text with both backends (passage style, no instruction) and
    reports the per-text cosine. ``ok`` is true when the minimum cosine clears
    ``min_cosine``. This imports ``sentence_transformers`` lazily, so only the
    offline env (which built the index) needs it.
    """
    import numpy as np  # type: ignore[import-not-found]
    from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

    if texts is None:
        texts = sample_index_texts(db_path)
    if not texts:
        return {"ok": False, "n": 0, "reason": "no index texts to compare"}

    st_model = SentenceTransformer(MODEL_NAME)
    st_vecs = st_model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    onnx_vecs = np.vstack([embed_text(t) for t in texts])

    cosines = [float(np.dot(a, b)) for a, b in zip(st_vecs, onnx_vecs)]
    result = {
        "ok": min(cosines) >= min_cosine,
        "n": len(texts),
        "min_cosine": min(cosines),
        "mean_cosine": float(sum(cosines) / len(cosines)),
        "min_required": min_cosine,
        "model": MODEL_NAME,
        "backend": "fastembed-onnx",
    }
    return result
