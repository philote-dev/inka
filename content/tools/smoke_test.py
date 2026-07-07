"""Toolchain smoke test for the pgrep AI parallel track.

Proves the three offline pieces work: the math checker (SymPy), the meaning
model (BGE via sentence-transformers), and the one-file search store
(sqlite-vec). Also confirms the LLM clients import. No network key needed.

Run inside the isolated env:
    conda run -n pgrep-ai python content/tools/smoke_test.py
"""

from __future__ import annotations

import sqlite3

import sqlite_vec
import sympy
from sentence_transformers import SentenceTransformer


def check_math() -> None:
    # A stand-in for verifying a computational physics answer symbolically.
    x = sympy.symbols("x")
    integral = sympy.integrate(2 * x, (x, 0, 3))
    assert integral == 9, integral
    print(f"[math]   SymPy integral of 2x from 0 to 3 = {integral}  ok")


def check_search() -> None:
    model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    dim = model.get_sentence_embedding_dimension()

    passages = [
        "Angular momentum is conserved when no external torque acts.",
        "The photoelectric effect shows light behaving as particles.",
        "Entropy of an isolated system never decreases over time.",
    ]
    vectors = model.encode(passages, normalize_embeddings=True)

    db = sqlite3.connect(":memory:")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    db.execute(f"CREATE VIRTUAL TABLE chunks USING vec0(embedding float[{dim}])")
    for i, vec in enumerate(vectors):
        db.execute(
            "INSERT INTO chunks(rowid, embedding) VALUES (?, ?)",
            (i, vec.astype("float32").tobytes()),
        )

    query = "what stays the same when there is no twisting force"
    qvec = model.encode([query], normalize_embeddings=True)[0].astype("float32")
    (best_id,) = db.execute(
        "SELECT rowid FROM chunks ORDER BY vec_distance_cosine(embedding, ?) LIMIT 1",
        (qvec.tobytes(),),
    ).fetchone()

    print(f"[search] model dim = {dim}")
    print(f"[search] query: {query!r}")
    print(f"[search] best match: {passages[best_id]!r}")
    assert best_id == 0, "expected the angular-momentum passage to match"
    print("[search] retrieval picked the right passage  ok")


def check_clients() -> None:
    import anthropic  # noqa: F401
    import openai  # noqa: F401

    print("[llm]    anthropic + openai clients import  ok (no key needed to import)")


if __name__ == "__main__":
    check_math()
    check_clients()
    check_search()
    print("\nAll toolchain pieces are working.")
