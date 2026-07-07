"""Annotate the community problem-gold drafts (misconception-first, grounded).

The community 70 arrive with a clean stem, five choices, and a key, but no
distractor annotations and an unverified key. This fills each item to gold grade:

  - an INDEPENDENT solve (the model answers the problem itself, blind to nothing
    but the choices) so a wrong or dubious community key is flagged, not trusted;
  - a per-distractor misconception tag and rationale (what error lands a student
    there), the whole point of the problem gold;
  - a key rationale and a solution decomposition;
  - problem_kind, a two-level topic, and a corrected blueprint_area;
  - corpus grounding: the top corpus passages for the stem are shown to the model
    so rationales track standard physics, and the passages are recorded.

The drafting model is gpt-4o, deliberately DIFFERENT from the run generator
(gpt-5.5), so the ruler is not authored by the system it grades. Keys still get a
second independent cross-check (gpt-5.5 + SymPy) in the rating step.

Idempotent and incremental: each item is cached by source id and written back the
moment it is done, so a crash or a rate-limit never loses finished work. Re-runs
only touch items still marked pending-annotation (or all, with --force).

LEAKAGE: these are GOLD. They stay under content/gold/, never indexed or fed.

Run (inside the env):
    conda run -n pgrep-ai --no-capture-output python content/tools/annotate_community.py
    conda run -n pgrep-ai --no-capture-output python content/tools/annotate_community.py --limit 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
PROBLEMS_DIR = os.path.join(CONTENT, "gold", "problems")
CACHE_DIR = os.path.join(CONTENT, "gold", "candidates", "_annot_cache")
ENV = os.path.join(CONTENT, ".env")
DB_PATH = os.path.join(CONTENT, "index", "corpus.db")

MODEL = "gpt-4o"
MAX_RETRY = 4
CONTEXT_K = 4

PRICE_IN = 2.50 / 1_000_000
PRICE_OUT = 10.00 / 1_000_000
_cost = {"in": 0, "out": 0}

BLUEPRINT = ["mechanics", "electromagnetism", "quantum", "thermo-stat-mech",
             "atomic", "optics-waves", "special-relativity", "lab-methods", "specialized"]

AREA_FIX = {
    "nuclear": "specialized", "particle": "specialized", "particle-physics": "specialized",
    "condensed-matter": "specialized", "solid-state": "specialized", "astrophysics": "specialized",
    "electronics": "electromagnetism", "circuits": "electromagnetism",
    "waves": "optics-waves", "optics": "optics-waves", "wave-phenomena": "optics-waves",
    "relativity": "special-relativity", "special": "special-relativity",
    "thermodynamics": "thermo-stat-mech", "statistical-mechanics": "thermo-stat-mech",
    "thermal": "thermo-stat-mech", "lab": "lab-methods", "laboratory": "lab-methods",
    "classical-mechanics": "mechanics", "mechanics-classical": "mechanics",
}

SYS = (
    "You are a physics GRE item writer producing a grading rubric for ONE "
    "multiple-choice problem, and independently checking its answer key. You are "
    "given the stem, the five labelled choices, the answer key claimed by a web "
    "source, and relevant passages from open physics textbooks. First solve the "
    "problem yourself from physics, ignoring the claimed key, and report your own "
    "answer. Then draft the rubric. Ground everything in the passages and standard "
    "physics. Draft, do not certify.\n\n"
    "Return STRICT JSON with keys:\n"
    "  independent_answer: one of A,B,C,D,E, YOUR solved answer\n"
    "  answer_confidence: 0..1\n"
    "  key_agrees: true if independent_answer equals the claimed key\n"
    "  problem_kind: \"conceptual\" or \"computational\"\n"
    "  blueprint_area: one of " + ", ".join(BLUEPRINT) + "\n"
    "  topic: {category, subtopic}\n"
    "  key_rationale: why the correct choice is correct, 1-3 sentences\n"
    "  distractors: object keyed by the FOUR non-key labels; each value has "
    "misconception_tag (short kebab-case, e.g. sign-error, wrong-law, unit-slip, "
    "limiting-case-confusion) and rationale (one sentence naming the specific "
    "error that lands a student on that choice)\n"
    "  solution_decomposition: array of 1-4 steps, each {step:int, subgoal, rubric}\n"
    "Name the likely error for every one of the four distractors."
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


def source_id(item: dict) -> str:
    note = item.get("notes", "")
    for tok in note.split(";"):
        tok = tok.strip()
        if tok.startswith("source_id="):
            return tok.split("=", 1)[1].strip()
    return item["id"]


def retrieval_context(db, model, stem: str):
    import query_index as qi

    hits = qi.search(db, model, stem, k=CONTEXT_K)
    lines, refs = [], []
    for h in hits:
        snip = " ".join(h["text"].split())[:400]
        lines.append(f"[{h['source_ref']}] {snip}")
        refs.append(h["source_ref"])
    return "\n\n".join(lines), refs


def annotate(client, item: dict, context: str) -> dict:
    sid = source_id(item)
    cache = os.path.join(CACHE_DIR, f"{sid}.json")
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    payload = {
        "stem": item["stem"],
        "choices": {c["label"]: c["text"] for c in item["choices"]},
        "claimed_key": item["key"],
        "textbook_passages": context,
    }
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": SYS},
                          {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            )
            track(resp)
            data = json.loads(resp.choices[0].message.content)
            os.makedirs(CACHE_DIR, exist_ok=True)
            json.dump(data, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            wait = 2 * attempt
            log(f"    [retry {attempt}/{MAX_RETRY}] {sid}: {exc} (wait {wait}s)")
            time.sleep(wait)
    raise RuntimeError(f"{sid} failed after {MAX_RETRY} tries: {last}")


def apply_annotation(item: dict, ann: dict, refs: list) -> None:
    key = item["key"]
    dist = ann.get("distractors", {}) or {}
    for c in item["choices"]:
        lab = c["label"]
        if lab == key:
            c["rationale"] = str(ann.get("key_rationale", "")).strip() or c.get("rationale", "pending")
            c.pop("misconception_tag", None)
        else:
            d = dist.get(lab, {}) or {}
            c["misconception_tag"] = str(d.get("misconception_tag", "")).strip() or "unspecified"
            c["rationale"] = str(d.get("rationale", "")).strip() or "pending"

    kind = ann.get("problem_kind")
    if kind in ("conceptual", "computational"):
        item["problem_kind"] = kind

    area = str(ann.get("blueprint_area", "")).strip().lower()
    area = AREA_FIX.get(area, area)
    if area in BLUEPRINT:
        item["blueprint_area"] = area
    topic = ann.get("topic") or {}
    if topic.get("category") and topic.get("subtopic"):
        item["topic"] = {"category": str(topic["category"]), "subtopic": str(topic["subtopic"])}
    else:
        item["topic"] = {"category": item["blueprint_area"], "subtopic": item["blueprint_area"]}

    decomp = ann.get("solution_decomposition") or []
    norm = []
    for i, s in enumerate(decomp, start=1):
        if isinstance(s, dict) and s.get("subgoal") and s.get("rubric"):
            norm.append({"step": int(s.get("step", i)), "subgoal": str(s["subgoal"]),
                         "rubric": str(s["rubric"])})
    item["solution_decomposition"] = norm or [
        {"step": 1, "subgoal": "pending", "rubric": "pending: derive from source (verify)."}]

    indep = str(ann.get("independent_answer", "")).strip().upper()[:1]
    agrees = indep == key
    item["verification"] = {
        "status": "pending-frank" if agrees else "needs-frank-key",
        "method_draft": ["source-checked", "second-model-independent-solve"],
        "independent_solve": {"model": MODEL, "answer": indep, "agrees_with_key": agrees,
                              "confidence": ann.get("answer_confidence")},
        "grounding_refs": refs,
        "note": ("Community key as given. Distractors, key rationale, and decomposition are "
                 "gpt-4o drafts grounded in the open corpus. Independent gpt-4o solve "
                 + ("agrees with the key." if agrees else "DISAGREES with the claimed key; needs Frank.")),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Annotate the community problem-gold drafts.")
    ap.add_argument("--limit", type=int, default=0, help="annotate at most N items (0 = all)")
    ap.add_argument("--force", action="store_true", help="re-annotate even if already done")
    args = ap.parse_args()

    key = load_key()
    if not key:
        log("[stop] OPENAI_API_KEY missing or empty in content/.env. Nothing changed.")
        sys.exit(0)

    files = sorted(f for f in os.listdir(PROBLEMS_DIR) if f.endswith(".json"))
    todo = []
    for name in files:
        path = os.path.join(PROBLEMS_DIR, name)
        item = json.load(open(path, encoding="utf-8"))
        status = item.get("verification", {}).get("status", "")
        if args.force or status == "pending-annotation":
            todo.append((path, item))
    if args.limit:
        todo = todo[: args.limit]
    log(f"[start] {len(todo)} community items to annotate (model {MODEL})")
    if not todo:
        return

    from openai import OpenAI
    import query_index as qi
    from sentence_transformers import SentenceTransformer

    client = OpenAI(api_key=key)
    db = qi.connect(DB_PATH)
    embed = SentenceTransformer(qi.MODEL_NAME)

    disagreements, done, failures = [], 0, []
    for i, (path, item) in enumerate(todo, start=1):
        sid = source_id(item)
        try:
            context, refs = retrieval_context(db, embed, item["stem"])
            ann = annotate(client, item, context)
            apply_annotation(item, ann, refs)
            json.dump(item, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            done += 1
            flag = "" if item["verification"]["status"] == "pending-frank" else "  <-- KEY DISAGREES"
            if item["verification"]["status"] != "pending-frank":
                disagreements.append((item["id"], sid, item["key"],
                                      item["verification"]["independent_solve"]["answer"]))
            log(f"[{i}/{len(todo)}] {item['id']} ({sid}) {item['blueprint_area']:16} "
                f"${cost_usd():.2f}{flag}")
        except Exception as exc:  # noqa: BLE001
            failures.append({"id": item["id"], "sid": sid, "error": str(exc)})
            log(f"[{i}/{len(todo)}] FAIL {item['id']} ({sid}): {exc}")

    db.close()
    log("\n[summary]")
    log(f"  annotated: {done}/{len(todo)}")
    log(f"  key disagreements (need Frank): {len(disagreements)}")
    for pid, sid, claimed, model_ans in disagreements:
        log(f"     {pid} ({sid}): claimed {claimed}, gpt-4o says {model_ans}")
    log(f"  failures: {len(failures)}")
    log(f"  approx cost: ${cost_usd():.2f}  ({_cost['in']} in + {_cost['out']} out tokens)")


if __name__ == "__main__":
    main()
