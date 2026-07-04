# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Forced card generation for the Library surface (L4.1).

Three paths, per ``feature-forced-generation.md`` and ``ux-foundation.md`` 7.4:

  - ``author_seed``: the learner writes one conceptual card. This is the
    generation-effect act and it always works, AI on or off. It is the only way
    to unlock the AI paths ("pay to play").
  - ``stylize``: AI on. Rewrite the bundle's cards for a subtopic into the
    learner's voice, facts locked. Shown live, evaluated live, never added as
    duplicates and never a batch the gate scores.
  - ``gap_fill``: AI on. The graded path. When the learner authors a technique
    the bundle lacks, generate net-new sibling cards from the corpus only, each
    RAG-grounded with provenance, deduped, and routed to human review below the
    confidence floor.

Everything is AI-off safe: with AI off the module still authors seeds, and the
heavy AI modules are imported lazily so they never load unless AI is on. Generated
cards are new notes (cold-start FSRS); scheduling state is never mutated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from anki.pgrep import ai_config

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.models import NotetypeDict

GENERATED_DECK_NAME = "PGRE::Generated"
SEED_TAG = "pgrep::seed-authored"
GENERATED_TAG = "pgrep::generated"
STYLIZED_TAG = "pgrep::stylized"
TOPIC_PREFIX = "topic::"

# How many corpus chunks to retrieve, and how many siblings to draft per gap-fill.
RETRIEVE_K = 6
DEFAULT_GAPFILL_N = 3
# Stylize keeps facts locked: a rewrite must still share this much of the
# original answer's content, or the original is kept.
_STYLE_FACT_OVERLAP = 0.5

STYLIZE_SYSTEM = (
    "You rephrase a verified flashcard into the learner's voice. Keep every fact "
    "identical, change only phrasing and framing to match the style seed. Never "
    "add or remove facts, never change the answer. Return STRICT JSON: "
    "{\"front\": str, \"back\": str}."
)


def _category(topic: str) -> str:
    return topic.split("::")[1] if topic.startswith(TOPIC_PREFIX) else topic


def _topic_tag(topic: str) -> str:
    return topic if topic.startswith(TOPIC_PREFIX) else f"{TOPIC_PREFIX}{topic}"


def _basic(col: Collection) -> NotetypeDict:
    basic = col.models.by_name("Basic")
    if basic is None:
        raise RuntimeError("default 'Basic' notetype not found in collection")
    return basic


def _existing_front_hashes(col: Collection) -> set[str]:
    from anki.pgrep.ai import verify

    hashes: set[str] = set()
    for nid in col.find_notes('note:Basic'):
        note = col.get_note(nid)
        if "Front" in note:
            hashes.add(verify.normalized_front_hash(note["Front"]))
    return hashes


def _add_card(col: Collection, front: str, back: str, topic: str, *,
              tag: str, source_ref: str | None) -> int:
    """Add one new Basic card (cold-start FSRS). Returns the note id."""
    note = col.new_note(_basic(col))
    note["Front"] = front
    body = f"{back}\n\nSource: {source_ref}" if source_ref else back
    note["Back"] = body
    note.tags = [tag, _topic_tag(topic)]
    deck_id = col.decks.id(GENERATED_DECK_NAME)
    col.add_note(note, deck_id)
    return note.id


def author_seed(col: Collection, front: str, back: str, topic: str) -> dict[str, Any]:
    """Add the learner's own seed card to the pool. Works AI on or off."""
    from anki.collection import AddNoteRequest

    note = col.new_note(_basic(col))
    note["Front"] = front
    note["Back"] = back
    note.tags = [SEED_TAG, _topic_tag(topic)]
    deck_id = col.decks.id(GENERATED_DECK_NAME)
    undo = col.add_custom_undo_entry("pgrep: author seed card")
    col.add_notes([AddNoteRequest(note=note, deck_id=deck_id)])
    col.merge_undo_entries(undo)
    return {"note_id": note.id, "topic": _topic_tag(topic), "added": True}


def _retrieve(col: Collection, query: str) -> Any:
    from anki.pgrep.ai import retrieval

    return retrieval.search(query, k=RETRIEVE_K)


def stylize(col: Collection, topic: str, seed_front: str, seed_back: str) -> dict[str, Any]:
    """AI on. Rephrase the bundle's cards for the topic into the seed's voice.

    Shown live: returns the rephrased cards for display, facts verified locked. It
    adds no duplicates to the pool (the learner's own seed is what enters).
    """
    if not ai_config.ai_enabled(col):
        return {"ai": "off", "cards": [], "message": "AI is off; your seed card was kept as is."}
    from anki.pgrep.ai import llm, verify

    tag = _topic_tag(topic)
    bundle_nids = list(col.find_notes(f'note:Basic tag:{tag}'))[:8]
    client = llm.LLMClient(ai_config.resolve_model(col))
    seed_toks = None
    out = []
    for nid in bundle_nids:
        note = col.get_note(nid)
        if "Front" not in note or "Back" not in note:
            continue
        orig_front, orig_back = note["Front"], note["Back"]
        user = (f"STYLE SEED:\nfront: {seed_front}\nback: {seed_back}\n\n"
                f"CARD TO REPHRASE:\nfront: {orig_front}\nback: {orig_back}")
        try:
            raw = client.complete_json(STYLIZE_SYSTEM, user)
        except Exception as exc:  # noqa: BLE001 - surface a clean status, never crash the app
            return {"ai": "error", "cards": [], "message": f"generation failed: {exc}"}
        new_back = raw.get("back", "")
        facts_locked = verify.normalize(orig_back) == verify.normalize(new_back) or \
            _overlap(orig_back, new_back) >= _STYLE_FACT_OVERLAP
        out.append({
            "front": raw.get("front", orig_front),
            "back": new_back if facts_locked else orig_back,
            "facts_locked": bool(facts_locked),
            "original_front": orig_front,
            "provenance": f"bundle card: {orig_front}",
        })
    return {"ai": "on", "mode": "stylize", "cards": out, "count": len(out)}


def gap_fill(col: Collection, topic: str, seed_front: str, seed_back: str,
             n: int = DEFAULT_GAPFILL_N) -> dict[str, Any]:
    """AI on, the graded path. Generate net-new siblings from the corpus only."""
    if not ai_config.ai_enabled(col):
        return {"ai": "off", "added": [], "review": [], "refused": [],
                "message": "AI is off; author your card and it enters the pool as is."}
    from anki.pgrep.ai import generation_core as gc
    from anki.pgrep.ai import llm

    query = f"{seed_front} {seed_back} {_category(topic)}"
    retrieved = _retrieve(col, query)
    client = llm.LLMClient(ai_config.resolve_model(col))
    seed_card = {"front": seed_front, "back": seed_back}
    existing = _existing_front_hashes(col)

    added, review, refused = [], [], []
    for _ in range(max(1, n)):
        try:
            item = gc.generate_card(topic=_topic_tag(topic), retrieved=retrieved,
                                    llm=client, seed_card=seed_card)
        except Exception as exc:  # noqa: BLE001
            return {"ai": "error", "added": [], "review": [], "refused": [],
                    "message": f"generation failed: {exc}"}
        if item.get("refused"):
            refused.append({"reason": item.get("refusal_reason"), "front": item.get("front")})
            continue
        from anki.pgrep.ai import verify

        h = verify.normalized_front_hash(item.get("front", ""))
        if h in existing:
            continue
        existing.add(h)
        record = {"front": item["front"], "back": item["back"],
                  "source_ref": item.get("source_ref"), "confidence": item.get("confidence"),
                  "card_kind": item.get("card_kind")}
        if item.get("needs_review"):
            record["review_reason"] = item.get("review_reason")
            review.append(record)
            continue
        note_id = _add_card(col, item["front"], item["back"], topic,
                            tag=GENERATED_TAG, source_ref=item.get("source_ref"))
        record["note_id"] = note_id
        added.append(record)
    return {"ai": "on", "mode": "gap_fill", "added": added, "review": review,
            "refused": refused, "n_requested": n}


def generate(col: Collection, *, mode: str, topic: str, seed_front: str,
             seed_back: str, n: int = DEFAULT_GAPFILL_N) -> dict[str, Any]:
    """Library entry: author the seed, then stylize or gap-fill by mode."""
    seed = author_seed(col, seed_front, seed_back, topic)
    if mode == "stylize":
        result = stylize(col, topic, seed_front, seed_back)
    else:
        result = gap_fill(col, topic, seed_front, seed_back, n)
    result["seed"] = seed
    return result


def _overlap(a: str, b: str) -> float:
    from anki.pgrep.ai import verify

    ta = set(verify.normalize(a).split())
    tb = set(verify.normalize(b).split())
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)
