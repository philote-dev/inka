# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Provenance binding: cite a named corpus source, or refuse (L4.0f).

Spec constraint 6 says every AI output traces to a named source or is refused.
This module binds a generated item to the retrieved corpus chunk that best
supports it, exposing the source_ref, chunk_id, and a short verbatim quote
anchor. If nothing in the retrieved context supports the item above a floor, the
item is refused rather than shipped ungrounded.

The ETS forms shape style only and are never a cited source; only corpus chunks
(the sole thing retrieval returns) are ever bound here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD = re.compile(r"[a-z0-9]+")
# A retrieved chunk must clear this cosine to count as support for grounding.
MIN_SUPPORT_SCORE = 0.60


@dataclass
class Provenance:
    source_ref: str
    chunk_id: str
    source_title: str
    quote_anchor: str
    support_score: float

    def as_dict(self) -> dict:
        return {
            "source_ref": self.source_ref,
            "chunk_id": self.chunk_id,
            "source_title": self.source_title,
            "quote_anchor": self.quote_anchor,
            "support_score": self.support_score,
        }


def _first_sentence(text: str, max_len: int = 200) -> str:
    text = " ".join(text.split())
    for end in (". ", "? ", "! "):
        i = text.find(end)
        if 20 <= i <= max_len:
            return text[: i + 1].strip()
    return text[:max_len].strip()


def _overlap(a: str, b: str) -> float:
    ta = set(_WORD.findall(a.lower()))
    tb = set(_WORD.findall(b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta)


def best_support(claim_text: str, retrieved: list, *, min_score: float = MIN_SUPPORT_SCORE
                 ) -> Provenance | None:
    """The retrieved chunk that best supports the claim, or None to refuse.

    ``retrieved`` is a list of ``RetrievedChunk`` (or dicts). A chunk qualifies
    when its retrieval score clears ``min_score``; among those, the one with the
    most lexical overlap with the claim anchors the citation.
    """
    if not retrieved:
        return None
    best: Provenance | None = None
    best_rank = -1.0
    for r in retrieved:
        score = getattr(r, "score", None)
        if score is None and isinstance(r, dict):
            score = r.get("score", 0.0)
        if score is None or score < min_score:
            continue
        text = getattr(r, "text", None) or (r.get("text", "") if isinstance(r, dict) else "")
        source_ref = getattr(r, "source_ref", None) or (r.get("source_ref", "") if isinstance(r, dict) else "")
        chunk_id = getattr(r, "chunk_id", None) or (r.get("chunk_id", "") if isinstance(r, dict) else "")
        title = getattr(r, "source_title", None) or (r.get("source_title", "") if isinstance(r, dict) else "")
        rank = float(score) + _overlap(claim_text, text)
        if rank > best_rank:
            best_rank = rank
            best = Provenance(source_ref=source_ref, chunk_id=chunk_id, source_title=title,
                              quote_anchor=_first_sentence(text), support_score=float(score))
    return best


def cite_or_refuse(item: dict, retrieved: list, *, claim_key: str = "back",
                   min_score: float = MIN_SUPPORT_SCORE) -> dict:
    """Attach provenance to ``item`` or mark it refused.

    ``claim_key`` names the field carrying the item's core claim (``back`` for a
    card, ``stem`` for a problem). On success the item gains ``source_ref`` and
    ``provenance``; on failure it is flagged ``refused`` with a reason, so the
    caller ships nothing ungrounded.
    """
    claim = item.get(claim_key) or item.get("stem") or item.get("front") or ""
    prov = best_support(claim, retrieved, min_score=min_score)
    if prov is None:
        item["refused"] = True
        item["refusal_reason"] = "no corpus source supports this item above the grounding floor"
        item["source_ref"] = None
        return item
    item["refused"] = False
    item["source_ref"] = prov.source_ref
    item["provenance"] = prov.as_dict()
    return item
