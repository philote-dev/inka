"""Author the card gold set from the open corpus (RAG-grounded).

The card gold is the ruler for card generation. The locked spec calls for about
50 corpus-verified cards spread across the nine blueprint areas by weight, NOT
the empty topic anchors make_gold.py wrote. This builds them:

  - allocate ~50 slots weight-proportionally per area, covering every finest unit;
  - for each slot, retrieve the top corpus passages for that finest unit (and a
    rotating sub-aspect for variety) from the open index;
  - have gpt-4o write ONE exam-relevant card grounded in those passages: a front,
    a correct back, 1-4 atomic fact_assertions, and a verbatim quote_anchor, plus
    a SymPy form and decomposition for computational cards;
  - anchor provenance to the corpus passage the fact came from (tier 1, open).

The author model is gpt-4o, different from the run generator (gpt-5.5), so the
ruler is not written by the system it grades. Computational answers get a SymPy
cross-check in the rating step.

Cards are corpus-grounded but they are GOLD: they live under content/gold/, are
never added to the index, and are never fed to generation (nothing is both fed
and graded; the corpus is a named source, the gold card is a private reference).

Idempotent and incremental: each slot is cached, so a crash or rate-limit resumes
cleanly. Run:
    conda run -n pgrep-ai --no-capture-output python content/tools/author_card_gold.py
    conda run -n pgrep-ai --no-capture-output python content/tools/author_card_gold.py --total 50
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
CARDS_DIR = os.path.join(CONTENT, "gold", "cards")
CACHE_DIR = os.path.join(CONTENT, "gold", "candidates", "_card_cache")
BLUEPRINT = os.path.join(CONTENT, "blueprint", "blueprint.json")
ENV = os.path.join(CONTENT, ".env")
DB_PATH = os.path.join(CONTENT, "index", "corpus.db")

MODEL = "gpt-4o"
MAX_RETRY = 4
CONTEXT_K = 5

PRICE_IN = 2.50 / 1_000_000
PRICE_OUT = 10.00 / 1_000_000
_cost = {"in": 0, "out": 0}

# blueprint category slug -> gold-schema blueprint_area enum
AREA_SLUG = {
    "mechanics": "mechanics", "electromagnetism": "electromagnetism", "quantum": "quantum",
    "thermodynamics": "thermo-stat-mech", "atomic": "atomic", "optics_waves": "optics-waves",
    "special_relativity": "special-relativity", "lab": "lab-methods", "specialized": "specialized",
}

SYS = (
    "You are writing ONE Physics GRE flashcard, grounded strictly in the provided "
    "open-textbook passages. Write a card that tests a single core, exam-relevant "
    "fact that appears IN the passages for the given topic and sub-aspect. The "
    "answer must be correct and supported by a passage. Avoid anything that needs "
    "a figure. Prefer a crisp, testable fact over trivia.\n\n"
    "Return STRICT JSON:\n"
    "  front: the prompt (LaTeX with \\( \\) allowed)\n"
    "  back: the correct answer, concise\n"
    "  card_kind: \"conceptual\" or \"computational\"\n"
    "  fact_assertions: array of 1-4 objects {claim, must_hold:true}, each an "
    "atomic checkable fact the answer asserts\n"
    "  quote_anchor: a short verbatim quote (<= 160 chars) copied from one passage "
    "that supports the answer\n"
    "  source_index: the [n] number of the passage the fact comes from\n"
    "  (computational only) computational: {sympy_form, expected, units, tolerance}\n"
    "  (computational only) solution_decomposition: array of {step:int, subgoal, rubric}\n"
    "Ground the quote_anchor in a real passage; do not invent it."
)


def log(m: str) -> None:
    print(m, flush=True)


def load_key() -> str | None:
    if not os.path.exists(ENV):
        return None
    for line in open(ENV, encoding="utf-8"):
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip() or None
    return None


def track(resp) -> None:
    u = getattr(resp, "usage", None)
    if u:
        _cost["in"] += getattr(u, "prompt_tokens", 0) or 0
        _cost["out"] += getattr(u, "completion_tokens", 0) or 0


def cost_usd() -> float:
    return _cost["in"] * PRICE_IN + _cost["out"] * PRICE_OUT


def largest_remainder(weights: dict[str, int], total: int) -> dict[str, int]:
    raw = {k: total * w / sum(weights.values()) for k, w in weights.items()}
    floor = {k: int(v) for k, v in raw.items()}
    rem = total - sum(floor.values())
    order = sorted(raw, key=lambda k: raw[k] - floor[k], reverse=True)
    for k in order[:rem]:
        floor[k] += 1
    return floor


def build_slots(total: int) -> list[dict]:
    """Ordered (area, finest-unit, aspect) slots, weight-proportional, all units."""
    bp = json.load(open(BLUEPRINT, encoding="utf-8"))
    cats = bp["categories"]
    weights = {c["slug"]: c["weight_pct"] for c in cats}
    per_area = largest_remainder(weights, total)
    slots: list[dict] = []
    for c in cats:
        units = c["finest_units"]
        n = per_area[c["slug"]]
        # round-robin the area's card budget across its finest units
        counts = {u["slug"]: 0 for u in units}
        for i in range(n):
            counts[units[i % len(units)]["slug"]] += 1
        for u in units:
            aspects = [a.strip() for a in u.get("ets_content", "").split(",") if a.strip()] or [u["name"]]
            for j in range(counts[u["slug"]]):
                slots.append({
                    "area": AREA_SLUG[c["slug"]],
                    "category_slug": c["slug"],
                    "unit_slug": u["slug"],
                    "unit_name": u["name"],
                    "unit_tag": u["tag"],
                    "ets_content": u.get("ets_content", ""),
                    "aspect": aspects[j % len(aspects)],
                })
    return slots


def retrieval_context(db, model, query: str):
    import query_index as qi

    hits = qi.search(db, model, query, k=CONTEXT_K)
    lines, refs = [], []
    for i, h in enumerate(hits, start=1):
        snip = " ".join(h["text"].split())[:500]
        lines.append(f"[{i}] ({h['source_ref']}) {snip}")
        refs.append({"n": i, "title": h["source_title"], "section": h.get("section") or "",
                     "page": h.get("page"), "source_ref": h["source_ref"]})
    return "\n\n".join(lines), refs


def author(client, slot: dict, context: str, avoid: list[str]) -> dict:
    payload = {
        "topic": slot["unit_name"],
        "sub_aspect": slot["aspect"],
        "blueprint_area": slot["area"],
        "passages": context,
        "avoid_fronts": avoid,
    }
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                temperature=0.3,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": SYS},
                          {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            )
            track(resp)
            return json.loads(resp.choices[0].message.content)
        except Exception as exc:  # noqa: BLE001
            last = exc
            wait = 2 * attempt
            log(f"    [retry {attempt}/{MAX_RETRY}] {slot['unit_slug']}: {exc} (wait {wait}s)")
            time.sleep(wait)
    raise RuntimeError(f"{slot['unit_slug']} failed after {MAX_RETRY} tries: {last}")


def build_card(cid: str, slot: dict, data: dict, refs: list) -> dict:
    kind = data.get("card_kind") if data.get("card_kind") in ("conceptual", "computational") else "conceptual"
    facts = []
    for fa in (data.get("fact_assertions") or [])[:4]:
        claim = str(fa.get("claim", "")).strip() if isinstance(fa, dict) else str(fa).strip()
        if claim:
            facts.append({"claim": claim, "must_hold": True})
    if not facts:
        facts = [{"claim": str(data.get("back", "")).strip() or "pending", "must_hold": True}]

    idx = data.get("source_index")
    ref = None
    if isinstance(idx, int) and 1 <= idx <= len(refs):
        ref = refs[idx - 1]
    elif refs:
        ref = refs[0]
    section = (ref.get("section") if ref else "") or (f"p.{ref.get('page')}" if ref and ref.get("page") else "corpus")
    source_ref = {
        "title": (ref.get("title") if ref else "open corpus") or "open corpus",
        "section": section or "corpus",
    }
    qa = str(data.get("quote_anchor", "")).strip()
    if qa:
        source_ref["quote_anchor"] = qa[:180]

    card = {
        "id": cid,
        "schema_version": "1.0.0",
        "type": "card",
        "card_kind": kind,
        "topic": {"category": slot["category_slug"], "subtopic": slot["unit_slug"]},
        "blueprint_area": slot["area"],
        "front": str(data.get("front", "")).strip() or "pending",
        "back": str(data.get("back", "")).strip() or "pending",
        "fact_assertions": facts,
        "provenance": {"tier": 1, "source_ref": source_ref},
        "verification": {
            "status": "pending-frank",
            "method_draft": (["source-checked", "cas-checked"] if kind == "computational" else ["source-checked"]),
            "grounding_refs": [r["source_ref"] for r in refs],
            "note": "gpt-4o drafted from the open corpus, grounded in the quoted passage. "
                    "Frank verifies the fact against the source before promotion to verified.",
        },
        "leakage_class": "gold",
        "notes": f"unit={slot['unit_tag']}; aspect={slot['aspect']}",
    }
    decomp = data.get("solution_decomposition") or []
    norm = [{"step": int(s.get("step", i)), "subgoal": str(s["subgoal"]), "rubric": str(s["rubric"])}
            for i, s in enumerate(decomp, start=1)
            if isinstance(s, dict) and s.get("subgoal") and s.get("rubric")]
    if norm:
        card["solution_decomposition"] = norm
    comp = data.get("computational")
    if kind == "computational" and isinstance(comp, dict) and comp.get("expected"):
        block = {"expected": str(comp["expected"])}
        for k in ("sympy_form", "units"):
            if comp.get(k):
                block[k] = str(comp[k])
        if isinstance(comp.get("tolerance"), (int, float)):
            block["tolerance"] = comp["tolerance"]
        card["computational"] = block
    return card


def main() -> None:
    ap = argparse.ArgumentParser(description="Author the corpus-grounded card gold set.")
    ap.add_argument("--total", type=int, default=50)
    ap.add_argument("--limit", type=int, default=0, help="author at most N slots this run (0 = all)")
    args = ap.parse_args()

    key = load_key()
    if not key:
        log("[stop] OPENAI_API_KEY missing or empty in content/.env. Nothing changed.")
        sys.exit(0)

    slots = build_slots(args.total)
    log(f"[plan] {len(slots)} card slots across areas:")
    by_area: dict[str, int] = {}
    for s in slots:
        by_area[s["area"]] = by_area.get(s["area"], 0) + 1
    for a, n in sorted(by_area.items()):
        log(f"   {a:18} {n}")

    from openai import OpenAI
    import query_index as qi
    from sentence_transformers import SentenceTransformer

    client = OpenAI(api_key=key)
    db = qi.connect(DB_PATH)
    embed = SentenceTransformer(qi.MODEL_NAME)
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(CARDS_DIR, exist_ok=True)

    # Replace the placeholder anchors; keep real cards for resumable overwrite.
    for old in os.listdir(CARDS_DIR):
        if old.startswith("gold-card-anchor") and old.endswith(".json"):
            os.remove(os.path.join(CARDS_DIR, old))

    seen_fronts_by_unit: dict[str, list[str]] = {}
    done, failures = 0, []
    run_slots = slots[: args.limit] if args.limit else slots
    for i, slot in enumerate(run_slots, start=1):
        cid = f"gold-card-{i:04d}"
        cache = os.path.join(CACHE_DIR, f"{cid}.json")
        try:
            if os.path.exists(cache):
                data = json.load(open(cache, encoding="utf-8"))
                refs = data.get("_refs", [])
            else:
                query = f"{slot['unit_name']}: {slot['aspect']}"
                context, refs = retrieval_context(db, embed, query)
                avoid = seen_fronts_by_unit.get(slot["unit_slug"], [])
                data = author(client, slot, context, avoid)
                data["_refs"] = refs
                json.dump(data, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            card = build_card(cid, slot, data, refs)
            json.dump(card, open(os.path.join(CARDS_DIR, f"{cid}.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            seen_fronts_by_unit.setdefault(slot["unit_slug"], []).append(card["front"])
            done += 1
            log(f"[{i}/{len(run_slots)}] {cid} {slot['area']:16} {slot['unit_slug']:22} "
                f"{card['card_kind']:13} ${cost_usd():.2f}")
        except Exception as exc:  # noqa: BLE001
            failures.append({"id": cid, "slot": slot["unit_slug"], "error": str(exc)})
            log(f"[{i}/{len(run_slots)}] FAIL {cid} ({slot['unit_slug']}): {exc}")

    db.close()
    log("\n[summary]")
    log(f"  authored: {done}/{len(run_slots)}")
    log(f"  failures: {len(failures)}")
    log(f"  approx cost: ${cost_usd():.2f}  ({_cost['in']} in + {_cost['out']} out tokens)")
    log(f"  wrote {CARDS_DIR}")


if __name__ == "__main__":
    main()
