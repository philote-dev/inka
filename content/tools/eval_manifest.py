"""The run manifest for a scored batch (L4.0e).

Every scored run writes a manifest that pins exactly what produced the numbers,
so a result is reproducible and the pre-registration is honored: the dated model
snapshots (never floating aliases), temperature and seed, the prompt version and
hash, the corpus index version, the embedding model and backend with its parity
cosine, the gold-set version, the frozen cutoffs, the seen-versus-held split, and
a timestamp.

The cutoffs are read from the frozen pre-registration block in
``docs_pgrep/ai/cutoffs-and-baselines.md`` so there is one source of truth and no
drift.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
REPO = os.path.dirname(CONTENT)
# The frozen pre-registration lives in the tracked docs tree (docs_pgrep/ai/),
# so the cutoffs are version-controlled and visible, while the private data and
# this harness stay in git-ignored content/.
PREREG_MD = os.path.join(REPO, "docs_pgrep", "ai", "cutoffs-and-baselines.md")

_SECTION = {
    "card gate": "card",
    "problem gate": "problem",
    "beat-baseline": "beat_baseline",
    "raters": "raters",
}


def load_prereg(path: str = PREREG_MD) -> dict:
    """Parse the frozen PRE-REGISTRATION block into a structured dict."""
    text = open(path, encoding="utf-8").read()
    blocks = re.findall(r"```(.*?)```", text, re.S)
    block = next((b for b in blocks if "PRE-REGISTRATION" in b), None)
    if block is None:
        raise ValueError(f"no PRE-REGISTRATION block found in {path}")
    result: dict = {"card": {}, "problem": {}, "beat_baseline": {}, "raters": {}}
    section: str | None = None
    for raw in block.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s in _SECTION:
            section = _SECTION[s]
            continue
        meta = re.match(r"(round|date frozen|frozen by)\s*:\s*(.+)", s)
        if meta and section is None:
            result[meta.group(1).replace(" ", "_")] = meta.group(2).strip()
            continue
        if section is None:
            continue
        m = re.match(r"(.+?)\s*(>=|=|:)\s*(.+)", s)
        if not m:
            continue
        label = m.group(1).strip().lower().replace(" ", "_").replace("-", "_")
        val = m.group(3).strip()
        num = re.match(r"^([\d.]+)$", val.split()[0]) if val.split() else None
        result[section][label] = float(num.group(1)) if num else val
    return result


def corpus_index_version(db_path: str) -> dict:
    """Version fingerprint of the corpus index from its meta table."""
    db = sqlite3.connect(db_path)
    try:
        meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
        total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        db.close()
    model = meta.get("model", "?")
    built_at = meta.get("built_at", "?")
    return {
        "db_path": os.path.relpath(db_path, os.path.dirname(CONTENT)),
        "embed_model": model,
        "dim": meta.get("dim"),
        "total_chunks": total,
        "built_at": built_at,
        "size_bytes": os.path.getsize(db_path),
        "version_id": f"{model}|chunks={total}|{built_at}",
    }


def gold_version(*gold_dirs: str) -> dict:
    """Version fingerprint of the gold sets (file count plus a content hash)."""
    files: list[str] = []
    for d in gold_dirs:
        files += sorted(glob.glob(os.path.join(d, "*.json")))
    h = hashlib.blake2b(digest_size=8)
    for f in files:
        h.update(os.path.basename(f).encode("utf-8"))
        try:
            h.update(open(f, "rb").read())
        except OSError:
            continue
    return {"n_files": len(files), "hash": h.hexdigest(),
            "dirs": [os.path.relpath(d, os.path.dirname(CONTENT)) for d in gold_dirs]}


def prompt_hash(prompt_text: str) -> str:
    return hashlib.blake2b(prompt_text.encode("utf-8"), digest_size=8).hexdigest()


def build_manifest(*, round_id: str, generator_model: str, judge_model: str,
                   temperature: float, seed: int | None, prompt_version: str,
                   prompt_text: str, corpus_index: dict, embedding: dict,
                   gold: dict, cutoffs: dict, seen_vs_held: dict,
                   extra: dict | None = None) -> dict:
    """Assemble the full run manifest."""
    manifest = {
        "round": round_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "models": {
            "generator": generator_model,
            "judge": judge_model,
            "temperature": temperature,
            "seed": seed,
            "vendor_note": (
                "Generator and judge share a vendor (OpenAI). Mitigated by using "
                "different models so the judge never grades its own outputs, and by "
                "Frank as primary rater and adjudicator (C7). The judge is a second "
                "opinion, not the final say."
            ),
            "computational_verifier": "SymPy (independent of any model, all computational items)",
        },
        "prompt": {"version": prompt_version, "hash": prompt_hash(prompt_text)},
        "corpus_index": corpus_index,
        "embedding": embedding,
        "gold_set": gold,
        "cutoffs": cutoffs,
        "seen_vs_held": seen_vs_held,
    }
    if extra:
        manifest["extra"] = extra
    return manifest


def write_manifest(manifest: dict, out_path: str) -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    return out_path
