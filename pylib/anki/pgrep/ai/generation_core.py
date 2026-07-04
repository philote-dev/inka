# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Collection-free generation orchestration (L4.0f).

The one place card and problem generation are assembled, imported by both the app
(``anki.pgrep.generation`` / ``problem_gen``) and the offline harness. The flow
is the same either way: retrieve corpus context, prompt a pinned model, bind
provenance (cite or refuse), verify (CAS for computational items), then route low
confidence to human review. Nothing here touches a Collection; the caller writes
notes.

The LLM is injected (any object with ``complete_json(system, user) -> dict``), so
tests pass a fake and never call the API. Prompt templates carry a version so the
manifest can pin exactly what produced a batch.
"""

from __future__ import annotations

from typing import Any

from . import provenance, verify

# Route anything below this generated-confidence to human review, per
# feature-forced-generation.md (core-minimum verification).
CONFIDENCE_THRESHOLD = 0.6
CARD_PROMPT_VERSION = "card-v1"
PROBLEM_PROMPT_VERSION = "problem-v1"
CONTEXT_CHUNKS = 6

CARD_SYSTEM = (
    "You write one Physics GRE flashcard grounded ONLY in the provided corpus "
    "context. Every fact must be supported by that context. If the context does "
    "not support a correct, useful card, set \"refuse\": true. Never invent "
    "physics. Return STRICT JSON: {\"front\": str, \"back\": str, \"card_kind\": "
    "\"conceptual\"|\"computational\", \"difficulty\": 0..1, \"confidence\": 0..1, "
    "\"computational\": {\"expression\": str, \"expected\": number, \"tolerance\": "
    "number} | null, \"refuse\": bool}."
)

PROBLEM_SYSTEM = (
    "You write one Physics GRE multiple-choice problem grounded ONLY in the "
    "provided corpus context, with misconception-first distractors: name the "
    "likely error, then derive the wrong answer it produces. Return STRICT JSON: "
    "{\"stem\": str, \"choices\": [5 strings A..E], \"key\": \"A\"|..|\"E\", "
    "\"distractors\": [{\"label\": str, \"misconception_tag\": str, \"rationale\": "
    "str}], \"solution_decomposition\": [{\"subgoal\": str, \"rubric\": str}], "
    "\"problem_kind\": \"conceptual\"|\"computational\", \"difficulty\": 0..1, "
    "\"confidence\": 0..1, \"computational\": {\"expression\": str, \"expected\": "
    "number, \"tolerance\": number} | null, \"refuse\": bool}. No sub-goal or "
    "rationale may state the final answer."
)


def build_context(retrieved: list) -> str:
    """Format retrieved corpus chunks as numbered, cited context for the prompt."""
    lines = []
    for i, r in enumerate(retrieved[:CONTEXT_CHUNKS], start=1):
        ref = getattr(r, "source_ref", None) or (r.get("source_ref") if isinstance(r, dict) else "")
        text = getattr(r, "text", None) or (r.get("text") if isinstance(r, dict) else "")
        lines.append(f"[{i}] ({ref}) {' '.join(text.split())}")
    return "\n\n".join(lines)


def _route_confidence(item: dict) -> dict:
    """Flag human review when refused or below the confidence threshold."""
    conf = float(item.get("confidence", 0.0) or 0.0)
    item["confidence"] = conf
    if item.get("refused"):
        item["needs_review"] = True
    elif conf < CONFIDENCE_THRESHOLD:
        item["needs_review"] = True
        item["review_reason"] = f"confidence {conf:.2f} below {CONFIDENCE_THRESHOLD}"
    else:
        item["needs_review"] = False
    return item


def _cas_verify_card(item: dict) -> dict:
    comp = item.get("computational")
    if item.get("card_kind") == "computational" and isinstance(comp, dict) and comp.get("expression"):
        ok = verify.cas_check_value(comp["expression"], float(comp.get("expected", 0.0)),
                                    tolerance=float(comp.get("tolerance", 1e-3)))
        item["cas_verified"] = bool(ok)
        if not ok:
            item["refused"] = True
            item["refusal_reason"] = "CAS check failed for a computational card"
    return item


def generate_card(*, topic: str, retrieved: list, llm: Any, seed_card: dict | None = None) -> dict:
    """Generate one corpus-grounded card. ``seed_card`` steers style (stylize)."""
    context = build_context(retrieved)
    user = f"TOPIC: {topic}\n\nCORPUS CONTEXT:\n{context}"
    if seed_card:
        user += (f"\n\nSTYLE SEED (match this learner's voice, keep facts from the "
                 f"context):\nfront: {seed_card.get('front','')}\nback: {seed_card.get('back','')}")
    raw = llm.complete_json(CARD_SYSTEM, user)
    item = {
        "kind": "card",
        "topic": topic,
        "front": raw.get("front", ""),
        "back": raw.get("back", ""),
        "card_kind": raw.get("card_kind", "conceptual"),
        "difficulty": raw.get("difficulty", 0.5),
        "confidence": raw.get("confidence", 0.0),
        "computational": raw.get("computational"),
        "prompt_version": CARD_PROMPT_VERSION,
    }
    if raw.get("refuse"):
        item["refused"] = True
        item["refusal_reason"] = "model declined: context did not support a useful card"
        item["source_ref"] = None
        return _route_confidence(item)
    item = provenance.cite_or_refuse(item, retrieved, claim_key="back")
    item = _cas_verify_card(item)
    return _route_confidence(item)


def generate_problem(*, topic: str, retrieved: list, llm: Any) -> dict:
    """Generate one corpus-grounded MCQ with misconception-first distractors."""
    context = build_context(retrieved)
    user = f"TOPIC: {topic}\n\nCORPUS CONTEXT:\n{context}"
    raw = llm.complete_json(PROBLEM_SYSTEM, user)
    choices = raw.get("choices", [])
    distractors = raw.get("distractors", [])
    item = {
        "kind": "problem",
        "topic": topic,
        "stem": raw.get("stem", ""),
        "choices": choices,
        "key": raw.get("key", ""),
        "distractors": distractors,
        "distractor_rationales": {d.get("label"): d.get("rationale") for d in distractors
                                  if isinstance(d, dict) and d.get("label")},
        "solution_decomposition": raw.get("solution_decomposition", []),
        "problem_kind": raw.get("problem_kind", "conceptual"),
        "difficulty": raw.get("difficulty", 0.5),
        "confidence": raw.get("confidence", 0.0),
        "computational": raw.get("computational"),
        "prompt_version": PROBLEM_PROMPT_VERSION,
    }
    if raw.get("refuse") or len(choices) != 5 or item["key"] not in ("A", "B", "C", "D", "E"):
        item["refused"] = True
        item["refusal_reason"] = "model declined or produced a malformed MCQ"
        item["source_ref"] = None
        return _route_confidence(item)
    # No ladder step or rationale may leak the final answer.
    key_text = choices["ABCDE".index(item["key"])] if len(choices) == 5 else ""
    leaks = []
    for step in item["solution_decomposition"]:
        text = f"{step.get('subgoal','')} {step.get('rubric','')}" if isinstance(step, dict) else str(step)
        reason = verify.find_giveaway(text, key_text, choice_label=item["key"])
        if reason:
            leaks.append(reason)
    if leaks:
        item["refused"] = True
        item["refusal_reason"] = f"solution decomposition leaks the answer: {leaks[0]}"
        item["source_ref"] = None
        return _route_confidence(item)
    item = provenance.cite_or_refuse(item, retrieved, claim_key="stem")
    if item.get("problem_kind") == "computational" and isinstance(item.get("computational"), dict):
        comp = item["computational"]
        if comp.get("expression"):
            item["cas_verified"] = bool(verify.cas_check_value(
                comp["expression"], float(comp.get("expected", 0.0)),
                tolerance=float(comp.get("tolerance", 1e-3))))
    return _route_confidence(item)


def dedup_filter(items: list[dict], existing_hashes: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Split items into (kept, dropped) by normalized-front dedup within the batch
    and against any existing hashes."""
    seen = set(existing_hashes or set())
    kept, dropped = [], []
    for it in items:
        front = it.get("front") or it.get("stem") or ""
        h = verify.normalized_front_hash(front)
        if h in seen:
            it["duplicate"] = True
            dropped.append(it)
        else:
            seen.add(h)
            kept.append(it)
    return kept, dropped
