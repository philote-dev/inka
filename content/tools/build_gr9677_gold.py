#!/usr/bin/env python3
"""Build a clean, gold-grade candidate set from GR9677 (private problem gold).

Pipeline (staged, each stage caches so re-runs are cheap and API-thrifty):

  transcribe : render each GR9677 question page and vision-transcribe every
               question to clean text with LaTeX math (OpenAI vision).
  annotate   : for each kept item, draft per-distractor misconception+rationale,
               a key rationale, and a solution decomposition, grounded in the
               Faucett Omnibus worked solution (OpenAI text).
  assemble   : merge, attach keys, filter figure/unscored, write the gold JSON.

LEAKAGE FIREWALL: GR9677 is ETS Tier-3. Everything here is gold (evaluation
ruler only). Outputs live under content/gold/ and content/tier3-private/ and are
never indexed or fed to generation. Rendered page images are held in memory only.

Usage: python build_gr9677_gold.py [transcribe|annotate|assemble|all|test]
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV = os.path.join(ROOT, ".env")
FORM_PDF = os.path.join(ROOT, "tier3-private", "forms", "exam-gr9677.pdf")
ITEMS = os.path.join(ROOT, "tier3-private", "items", "GR9677.json")
CACHE = os.path.join(ROOT, "tier3-private", "items", "_gold_cache")
OUT = os.path.join(ROOT, "gold", "candidates", "gr9677-problem-gold.json")
README = os.path.join(ROOT, "gold", "candidates", "gr9677-gold-readme.md")

QUESTION_PAGES = list(range(11, 72, 2))  # odd PDF indices carry the questions
VISION_MODEL = "gpt-4o"
TEXT_MODEL = "gpt-4o"
DPI = 200

# rough gpt-4o pricing (USD per token) for a cost estimate only
PRICE_IN = 2.50 / 1_000_000
PRICE_OUT = 10.00 / 1_000_000
_cost = {"in": 0, "out": 0}

VISION_PROMPT = (
    "You are transcribing physics GRE questions from a scanned exam page image. "
    "The page may have one or two columns; read the left column fully, then the "
    "right. For EACH multiple-choice question visible, extract its number, the "
    "full stem, and the five choices A-E. Reproduce the wording exactly. Render "
    "every equation, symbol, subscript, superscript, Greek letter, and vector in "
    "LaTeX, inline with \\( \\) and display with \\[ \\]. Do NOT solve or add "
    "commentary. If a question depends on a figure, diagram, graph, table, or "
    "circuit drawing (something not expressible as text), set has_figure true and "
    "still transcribe whatever text is present. If a question is cut off at the "
    "top or bottom of the page (continued from or onto another page), set partial "
    "true. Some choices themselves may be figures; if so leave that choice text "
    "empty and set has_figure true. Return STRICT JSON of the form: "
    '{"questions": [{"number": <int>, "stem": <str>, '
    '"choices": {"A": <str>, "B": <str>, "C": <str>, "D": <str>, "E": <str>}, '
    '"has_figure": <bool>, "partial": <bool>}]}'
)


def load_key() -> str | None:
    if not os.path.exists(ENV):
        return None
    for line in open(ENV):
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            val = line.split("=", 1)[1].strip()
            return val or None
    return None


def client():
    from openai import OpenAI

    key = load_key()
    if not key:
        print("[stop] OPENAI_API_KEY missing or empty in content/.env")
        sys.exit(2)
    return OpenAI(api_key=key)


def page_data_url(doc, idx: int) -> str:
    pix = doc[idx].get_pixmap(dpi=DPI)
    b64 = base64.b64encode(pix.tobytes("png")).decode()
    return f"data:image/png;base64,{b64}"


def track(resp):
    u = resp.usage
    _cost["in"] += u.prompt_tokens
    _cost["out"] += u.completion_tokens


def cost_usd() -> float:
    return _cost["in"] * PRICE_IN + _cost["out"] * PRICE_OUT


# --- stage 1: vision transcription ------------------------------------------

def transcribe_page(cl, doc, idx: int) -> dict:
    os.makedirs(CACHE, exist_ok=True)
    cache = os.path.join(CACHE, f"page_{idx:03d}.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    resp = cl.chat.completions.create(
        model=VISION_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": VISION_PROMPT},
            {"type": "image_url", "image_url": {
                "url": page_data_url(doc, idx), "detail": "high"}},
        ]}],
    )
    track(resp)
    data = json.loads(resp.choices[0].message.content)
    json.dump(data, open(cache, "w"), ensure_ascii=False, indent=1)
    return data


def run_transcribe(cl):
    doc = fitz.open(FORM_PDF)
    for idx in QUESTION_PAGES:
        cached = os.path.exists(os.path.join(CACHE, f"page_{idx:03d}.json"))
        data = transcribe_page(cl, doc, idx)
        n = len(data.get("questions", []))
        print(f"  page {idx:2d}: {n} questions {'(cached)' if cached else ''}")
    doc.close()


def collect_questions() -> dict[int, dict]:
    """Merge per-page transcriptions by question number; prefer the complete one."""
    by_num: dict[int, dict] = {}
    for idx in QUESTION_PAGES:
        cache = os.path.join(CACHE, f"page_{idx:03d}.json")
        if not os.path.exists(cache):
            continue
        for q in json.load(open(cache)).get("questions", []):
            num = q.get("number")
            if not isinstance(num, int) or not (1 <= num <= 100):
                continue
            ch = q.get("choices", {}) or {}
            filled = sum(1 for k in "ABCDE" if (ch.get(k) or "").strip())
            prev = by_num.get(num)
            if prev is None or filled > prev["_filled"] or (
                filled == prev["_filled"] and len(q.get("stem", "")) > len(prev.get("stem", ""))
            ):
                q["_filled"] = filled
                by_num[num] = q
    return by_num


# --- stage 2: rationale annotation ------------------------------------------

BLUEPRINT = ["mechanics", "electromagnetism", "quantum", "thermo-stat-mech",
             "atomic", "optics-waves", "special-relativity", "lab-methods", "specialized"]

ANNOTATE_SYS = (
    "You are a physics GRE item writer producing a grading rubric for one "
    "multiple-choice problem. You are given the stem, the five choices, the "
    "correct key, and a worked solution from a third-party solutions book. "
    "Ground everything in that worked solution and standard physics. Draft, do "
    "not certify. Return STRICT JSON with keys: "
    "problem_kind (\"conceptual\" or \"computational\"), "
    "blueprint_area (one of: " + ", ".join(BLUEPRINT) + "), "
    "topic (object with category and subtopic), "
    "key_rationale (why the correct choice is correct, 1-3 sentences), "
    "distractors (object keyed by the FOUR wrong choice labels; each value has "
    "misconception_tag, a short kebab-case tag like sign-error or wrong-law, and "
    "rationale, one sentence naming the specific error that lands a student on "
    "that choice), and solution_decomposition (array of 1-4 steps, each with "
    "step (int), subgoal, rubric). Name the likely error for every distractor."
)


def annotate_item(cl, num: int, stem: str, choices: dict, key: str, solution: str) -> dict:
    os.makedirs(CACHE, exist_ok=True)
    cache = os.path.join(CACHE, f"annot_{num:03d}.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    user = json.dumps({
        "stem": stem,
        "choices": choices,
        "key": key,
        "worked_solution_from_solutions_book": solution[:2500],
    }, ensure_ascii=False)
    resp = cl.chat.completions.create(
        model=TEXT_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": ANNOTATE_SYS},
                  {"role": "user", "content": user}],
    )
    track(resp)
    data = json.loads(resp.choices[0].message.content)
    json.dump(data, open(cache, "w"), ensure_ascii=False, indent=1)
    return data


# --- stage 3: assemble -------------------------------------------------------

def build_items(cl, do_annotate: bool):
    items_json = json.load(open(ITEMS))
    keys = {it["number"]: it["key"] for it in items_json}
    fig_flag = {it["number"]: it["figure_dependent"] for it in items_json}
    sys.path.insert(0, HERE)
    from extract_omnibus_keys import extract
    omni = extract()["GR9677"]

    trans = collect_questions()
    kept, skipped = [], []
    for num in range(1, 101):
        q = trans.get(num)
        reason = None
        if num == 90:
            reason = "ETS unscored item (#90), no official key"
        elif q is None:
            reason = "not transcribed by vision"
        elif q.get("has_figure") or fig_flag.get(num):
            reason = "figure-dependent"
        elif q.get("partial"):
            reason = "partial transcription (spans page break)"
        elif sum(1 for k in "ABCDE" if (q.get("choices", {}).get(k) or "").strip()) < 5:
            reason = "incomplete choices"
        elif not keys.get(num):
            reason = "no key"
        if reason:
            skipped.append((num, reason))
            continue
        kept.append((num, q))

    gold = []
    for i, (num, q) in enumerate(kept, 1):
        key = keys[num]
        choices = q["choices"]
        sol = omni.get(num, {}).get("solution", "")
        if do_annotate:
            cached = os.path.exists(os.path.join(CACHE, f"annot_{num:03d}.json"))
            ann = annotate_item(cl, num, q["stem"], choices, key, sol)
            print(f"  annotate [{i}/{len(kept)}] #{num} {'(cached)' if cached else ''}")
        else:
            ann = {}
        gold.append(assemble_item(num, q, key, ann))
    return gold, kept, skipped


def assemble_item(num: int, q: dict, key: str, ann: dict) -> dict:
    dist = ann.get("distractors", {}) or {}
    choices = []
    for lab in "ABCDE":
        text = (q["choices"].get(lab) or "").strip()
        is_key = lab == key
        entry = {"label": lab, "text": text, "is_key": is_key}
        if is_key:
            entry["rationale"] = ann.get("key_rationale", "PENDING: key rationale (verify).")
        else:
            d = dist.get(lab, {})
            entry["misconception_tag"] = d.get("misconception_tag", "pending")
            entry["rationale"] = d.get("rationale", "PENDING: distractor rationale (verify).")
        choices.append(entry)
    topic = ann.get("topic") or {}
    area = ann.get("blueprint_area", "specialized")
    if area not in BLUEPRINT:  # map model's out-of-enum guesses to the schema enum
        area = {"nuclear": "specialized", "particle": "specialized",
                "electronics": "electromagnetism", "waves": "optics-waves",
                "optics": "optics-waves", "relativity": "special-relativity",
                "thermodynamics": "thermo-stat-mech", "statistical-mechanics": "thermo-stat-mech"}.get(area, "specialized")
    return {
        "id": f"gr9677-{num:03d}",
        "schema_version": "1.0.0",
        "type": "problem",
        "problem_kind": ann.get("problem_kind") if ann.get("problem_kind") in ("conceptual", "computational") else "conceptual",
        "topic": {"category": topic.get("category", "PENDING"),
                  "subtopic": topic.get("subtopic", "PENDING")},
        "blueprint_area": area,
        "stem": q["stem"].strip(),
        "choices": choices,
        "key": key,
        "solution_decomposition": ann.get("solution_decomposition") or [
            {"step": 1, "subgoal": "PENDING", "rubric": "PENDING: derive from source (verify)."}],
        "provenance": {
            "tier": 3,
            "source_ref": {
                "title": "GRE Physics Test, form GR9677 (ETS)",
                "section": f"Question {num}",
                "edition": "GR9677",
                "quote_anchor": q["stem"].strip()[:80],
            },
        },
        "verification": {"status": "pending-frank", "method_draft": ["source-checked-draft"],
                         "note": "Stem/choices vision-transcribed; key from Omnibus; "
                                 "distractor rationales and decomposition are LLM drafts. "
                                 "Frank to verify before promotion to gold."},
        "leakage_class": "gold",
        "notes": "Candidate pending Frank verification. GR9677 is ETS Tier-3: gold "
                 "eval only, never indexed or fed to generation.",
    }


def write_readme(n_gold, n_skip, skipped):
    from collections import Counter
    reasons = Counter(r for _n, r in skipped)
    lines = [
        "# GR9677 problem gold (candidate, pending verification)",
        "",
        "Candidate problem-gold set built from ETS form GR9677. Stems and choices "
        "were vision-transcribed from the scanned form to clean text with LaTeX "
        "math; keys come from the GR9677 key data and the Faucett Omnibus; "
        "per-distractor misconception rationales and solution decompositions are "
        "LLM drafts grounded in the Omnibus worked solutions.",
        "",
        "## Status: CANDIDATE, pending Frank's verification",
        "",
        "This gold set is PROVISIONAL pending Frank's human spot-check, but the "
        "keys are authoritative (official ETS solutions), so the L4.0 gate can run "
        "provisionally on it now.",
        "",
        "- Every item has `verification.status = pending-frank`. Rationales and "
        "decompositions are drafts and must be checked before promotion.",
        "- Keys are reliable (Omnibus, cross-checked). Stems are clean vision "
        "transcriptions but should be spot-checked against the form.",
        "",
        "## Leakage: this is GOLD",
        "",
        "GR9677 is ETS Tier-3. This set is an evaluation ruler only. It stays "
        "private under `content/gold/` and `content/tier3-private/` and is NEVER "
        "added to the corpus, the RAG index, or any generation or tutor prompt.",
        "",
        f"## Counts",
        "",
        f"- Clean candidate items: {n_gold}",
        f"- Skipped: {n_skip}",
    ]
    for r, c in reasons.most_common():
        lines.append(f"  - {r}: {c}")
    lines += ["", "Schema: fields follow `content/gold/gold-problem.schema.json` "
              "where possible. `verification` uses a `pending-frank` marker instead "
              "of the final verified block, since these are unverified candidates.", ""]
    open(README, "w").write("\n".join(lines))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "test":
        cl = client()
        doc = fitz.open(FORM_PDF)
        data = transcribe_page(cl, doc, 11)
        doc.close()
        print(json.dumps(data, ensure_ascii=False, indent=1)[:2000])
        print(f"\n[cost so far] ${cost_usd():.4f}")
        return
    cl = client()
    if mode in ("transcribe", "all"):
        print("[transcribe] vision pass over GR9677 question pages")
        run_transcribe(cl)
    if mode in ("annotate", "assemble", "all"):
        do_ann = mode in ("annotate", "all")
        gold, kept, skipped = build_items(cl, do_ann)
        json.dump(gold, open(OUT, "w"), ensure_ascii=False, indent=1)
        write_readme(len(gold), len(skipped), skipped)
        print(f"[assemble] wrote {len(gold)} candidate items -> {OUT}")
        print(f"  skipped {len(skipped)}")
        from collections import Counter
        for r, c in Counter(r for _n, r in skipped).most_common():
            print(f"    {r}: {c}")
    print(f"[cost] approx ${cost_usd():.4f} ({_cost['in']} in + {_cost['out']} out tokens)")


if __name__ == "__main__":
    main()

