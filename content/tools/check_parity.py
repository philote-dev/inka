"""Parity gate for the runtime ONNX embedder (L4.0c).

Confirms two things before the ONNX retrieval backend is trusted:

  1. The shared AI core imports the offline way, as ``pgrep.ai.*`` with
     ``pylib/anki`` on the path (no compiled Anki backend needed).
  2. The ``fastembed`` ONNX build of ``bge-small-en-v1.5`` matches the
     ``sentence-transformers`` build the index was made with, cosine ~1.0 on the
     same text, so query vectors live in the index's space.

It also runs one sample search to show retrieval end to end. Exit code is 0 when
parity clears the bar, 1 otherwise. The reported cosine belongs in the run
manifest.

Run:
    conda run -n pgrep-ai python content/tools/check_parity.py
    conda run -n pgrep-ai python content/tools/check_parity.py --min-cosine 0.99
"""

from __future__ import annotations

import argparse
import json
import sys

import _ai_path

_ai_path.add_ai_core()

from pgrep.ai import retrieval  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="ONNX vs sentence-transformers parity gate.")
    ap.add_argument("--min-cosine", type=float, default=retrieval.PARITY_MIN_COSINE)
    ap.add_argument("-n", "--samples", type=int, default=24)
    ap.add_argument("--query", default="conservation of angular momentum with no external torque")
    args = ap.parse_args()

    texts = retrieval.sample_index_texts(n=args.samples)
    result = retrieval.parity_check(texts, min_cosine=args.min_cosine)
    print("parity check (ONNX bge vs sentence-transformers bge)")
    print(json.dumps(result, indent=2))

    if not result.get("ok"):
        print("\nFAILED: ONNX embedder does not match the index model")
        sys.exit(1)

    print("\nsample search (ONNX query embedding over the sqlite-vec index)")
    for rank, r in enumerate(retrieval.search(args.query, k=3), start=1):
        print(f"[{rank}] score={r.score:.3f}  {r.source_ref}")
        print(f"    {' '.join(r.text.split())[:140]} ...")

    print("\nOK: ONNX retrieval backend matches the index and returns results")


if __name__ == "__main__":
    main()
