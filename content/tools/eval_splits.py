"""Generation safeguards for the airtight beats-baseline claim (L4.0e).

Implements the four data-integrity safeguards from ``docs_pgrep/ai/ai-layer.md``
section 6, so the eval is honest by construction:

  1. Name the split first. The locked ETS form allocation (fed / held-out / gold
     / sealed) is written down here and stamped into the manifest before any run.
  2. Cross-form dedup. PGRE forms repeat concepts across years, so drop any
     held-out or gold item too close to a fed example item.
  3. Reject memorized outputs. Dedup generated items against every ETS item, so
     the AI cannot pass a near-copy of a real question off as generated.
  4. Report seen versus held. Summarize exactly which forms were seen, which were
     held, and that dedup ran.

Near-duplicate detection is Jaccard over word 5-grams, which is fast, needs no
model, and is stable across paraphrase-free copies. The threshold is tunable.
"""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
ITEMS_DIR = os.path.join(CONTENT, "tier3-private", "items")

# The locked ETS form allocation, v3 (docs_pgrep/ai/ai-layer.md section 4,
# docs_pgrep/ai/heldout-and-leakage.md section 2). Named before any run.
# Under v3 NO ETS form is fed to generation. Generation is fed only the non-ETS
# pool (REA, Brainscape, CWRU); the harness grounds every generation on the open
# corpus alone. GR9677 is the problem gold (vision-cleaned, never fed). GR0177 and
# GR0877 are the clean in-app forms that also anchor the held-out Performance bank;
# GR8677 and GR9277 are reserve held-out; GR1777 stays sealed.
FORM_ALLOCATION = {
    "GR8677": "heldout",
    "GR9277": "heldout",
    "GR9677": "gold",
    "GR0177": "heldout",
    "GR0877": "heldout",
    "GR1777": "sealed",
}

# Non-ETS example pools fed to generation as few-shot style references (never
# graded, never the cited source). Used by reject_memorized so a generated item
# cannot pass off a near-copy of a fed example as its own.
FED_EXAMPLE_GLOBS = [
    os.path.join(CONTENT, "examples", "reference-questions", "*.json"),
    os.path.join(CONTENT, "examples", "brainscape", "*.json"),
    os.path.join(CONTENT, "examples", "cwru", "cards.json"),
]

DEFAULT_SIM_THRESHOLD = 0.5
_SHINGLE_N = 5
_WORD = re.compile(r"[a-z0-9]+")


def _shingles(text: str, n: int = _SHINGLE_N) -> set[str]:
    words = _WORD.findall(text.lower())
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: str, b: str) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def max_similarity(text: str, pool_shingles: list[set[str]]) -> float:
    target = _shingles(text)
    if not target:
        return 0.0
    best = 0.0
    for sh in pool_shingles:
        if not sh:
            continue
        union = len(target | sh)
        if union == 0:
            continue
        sim = len(target & sh) / union
        if sim > best:
            best = sim
    return best


# --- item loading (ETS items by role) --------------------------------------


def _item_text(it: dict) -> str:
    parts = [str(it.get("stem", ""))]
    parts += [str(c) for c in it.get("choices", []) if c]
    return " ".join(p for p in parts if p.strip())


def load_ets_items(roles: set[str] | None = None) -> list[dict]:
    """Parsed ETS items, optionally filtered to given roles (fed/heldout/gold)."""
    out: list[dict] = []
    for path in sorted(glob.glob(os.path.join(ITEMS_DIR, "*.json"))):
        form = os.path.splitext(os.path.basename(path))[0]
        role = FORM_ALLOCATION.get(form)
        if roles is not None and role not in roles:
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        for it in data:
            text = _item_text(it)
            if text.strip():
                out.append({"id": it.get("id"), "form": form, "role": role, "text": text})
    return out


# --- the safeguards --------------------------------------------------------


def name_split() -> dict:
    """Safeguard 1: the seen-versus-held split, named before any run."""
    fed = sorted(f for f, r in FORM_ALLOCATION.items() if r == "fed")
    heldout = sorted(f for f, r in FORM_ALLOCATION.items() if r == "heldout")
    gold = sorted(f for f, r in FORM_ALLOCATION.items() if r == "gold")
    sealed = sorted(f for f, r in FORM_ALLOCATION.items() if r == "sealed")
    return {"fed": fed, "heldout": heldout, "gold": gold, "sealed": sealed}


@dataclass
class DedupReport:
    threshold: float
    total: int
    dropped: list[dict] = field(default_factory=list)
    kept: int = 0

    def as_dict(self) -> dict:
        return {"threshold": self.threshold, "total": self.total,
                "kept": self.kept, "dropped": self.dropped}


def cross_form_dedup(candidate_items: list[dict], threshold: float = DEFAULT_SIM_THRESHOLD
                     ) -> DedupReport:
    """Safeguard 2: drop held-out or gold items too close to a fed example.

    ``candidate_items`` are held-out or gold items ({id, text, ...}); each is
    compared against the fed forms. Anything at or above the similarity threshold
    is dropped and reported, since a fed example that resembles a held item would
    inflate the beats-baseline claim.
    """
    fed_shingles = [_shingles(it["text"]) for it in load_ets_items({"fed"})]
    report = DedupReport(threshold=threshold, total=len(candidate_items))
    for it in candidate_items:
        sim = max_similarity(it.get("text", ""), fed_shingles)
        if sim >= threshold:
            report.dropped.append({"id": it.get("id"), "similarity": round(sim, 3)})
        else:
            report.kept += 1
    return report


def _fed_example_texts() -> list[str]:
    """Text of every non-ETS fed example (REA, Brainscape, CWRU)."""
    texts: list[str] = []
    for pattern in FED_EXAMPLE_GLOBS:
        for path in sorted(glob.glob(pattern)):
            try:
                data = json.load(open(path, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rows = data if isinstance(data, list) else data.get("cards", data.get("items", []))
            for it in rows if isinstance(rows, list) else []:
                if not isinstance(it, dict):
                    continue
                parts = [str(it.get(k, "")) for k in
                         ("stem", "question", "question_text", "front", "back", "answer", "answer_text")]
                parts += [str(c) for c in it.get("choices", []) if c]
                text = " ".join(p for p in parts if p.strip())
                if text.strip():
                    texts.append(text)
    return texts


def reject_memorized(generated_items: list[dict], threshold: float = DEFAULT_SIM_THRESHOLD
                     ) -> DedupReport:
    """Safeguard 3: reject generated items too close to any fed example.

    ``generated_items`` are {id, text, ...}. Each is compared against every ETS
    item (all roles, including the GR9677 gold) AND every non-ETS fed example
    (REA, Brainscape, CWRU), so a near-copy of a real question or a fed example
    cannot be scored as a genuine generation.
    """
    ets_shingles = [_shingles(it["text"]) for it in load_ets_items()]
    ets_shingles += [_shingles(t) for t in _fed_example_texts()]
    report = DedupReport(threshold=threshold, total=len(generated_items))
    for it in generated_items:
        sim = max_similarity(it.get("text", ""), ets_shingles)
        if sim >= threshold:
            report.dropped.append({"id": it.get("id"), "similarity": round(sim, 3)})
        else:
            report.kept += 1
    return report


def seen_vs_held_report(dedup_applied: bool) -> dict:
    """Safeguard 4: the seen-versus-held statement for the manifest and report."""
    split = name_split()
    fed_ets = ", ".join(split["fed"]) if split["fed"] else "no ETS form"
    return {
        "fed_forms": split["fed"],
        "fed_examples": "non-ETS only: REA (200 MCQs), Brainscape (747), CWRU (292)",
        "held_out_forms": split["heldout"],
        "gold_forms": split["gold"],
        "sealed_forms": split["sealed"],
        "dedup_applied": dedup_applied,
        "statement": (
            f"Fed ETS to the AI: {fed_ets}. Generation is fed only the non-ETS pool "
            f"(REA, Brainscape, CWRU) and grounds every output on the open corpus. "
            f"Held out, never fed: {', '.join(split['heldout'])}. "
            f"Gold, never fed: {', '.join(split['gold'])}. "
            f"Sealed: {', '.join(split['sealed'])}. "
            f"Cross-form dedup and reject-memorized {'applied' if dedup_applied else 'NOT applied'}."
        ),
    }
