"""Generate the graded batch for the L4.0 gate (cards, problems, baselines).

For each target topic it produces the systems the gate compares blind:
  - ai: a corpus-grounded card or misconception-first problem via the shared core.
  - naive (problems only): an MCQ asked for four wrong answers with no
    misconception step, the reported naive-distractor comparison.
  - keyword, vector: the retrieval baselines, top passage as the "generated" item.

Local work (embedding, sqlite-vec, FTS) runs serially to stay thread-safe; only
the LLM API calls are threaded. Candidates are written to a JSON file for
``score_batch.py`` to grade. Everything is grounded in the corpus index only.

Run:
    conda run -n pgrep-ai python content/tools/run_batch.py \
        --generator-model gpt-5.5-2026-04-23 --n-cards 50 --n-problems 36
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import _ai_path

_ai_path.add_ai_core()

from baselines import KeywordBaseline, VectorBaseline, candidate  # noqa: E402
from pgrep.ai import generation_core as gc  # noqa: E402
from pgrep.ai import llm as llm_mod  # noqa: E402
from pgrep.ai import retrieval  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
DEFAULT_DB = os.path.join(CONTENT, "index", "corpus.db")
GOLD_PROBLEMS = os.path.join(CONTENT, "gold", "problems")
GOLD_CARDS = os.path.join(CONTENT, "gold", "cards")
RUN_DIR = os.path.join(CONTENT, "run")

NAIVE_SYSTEM = (
    "You write a Physics GRE multiple-choice question grounded in the provided "
    "corpus context. Just give a stem, the correct answer, and four wrong "
    "answers. Do not reason about misconceptions. Return STRICT JSON: {\"stem\": "
    "str, \"choices\": [5 strings A..E], \"key\": \"A\"|..|\"E\"}."
)

_print_lock = threading.Lock()


def _load_gold(directory: str) -> list[dict]:
    out = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            out.append(json.load(open(os.path.join(directory, name), encoding="utf-8")))
    return out


def _load_env_key() -> None:
    import re

    path = os.path.join(CONTENT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*OPENAI_API_KEY\s*=\s*(.+)", line)
        if m and m.group(1).strip() and not m.group(1).strip().startswith("<"):
            os.environ.setdefault("OPENAI_API_KEY", m.group(1).strip())


def _spread(items: list[dict], n: int) -> list[dict]:
    """Round-robin by blueprint area so the batch stays spread across areas."""
    by_area: dict[str, list[dict]] = {}
    for it in items:
        by_area.setdefault(it.get("blueprint_area", "unknown"), []).append(it)
    order = sorted(by_area)
    picked: list[dict] = []
    idx = 0
    while len(picked) < n and any(by_area[a] for a in order):
        area = order[idx % len(order)]
        if by_area[area]:
            picked.append(by_area[area].pop(0))
        idx += 1
    return picked


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the graded L4.0 batch.")
    ap.add_argument("--generator-model", required=True)
    ap.add_argument("--n-cards", type=int, default=50)
    ap.add_argument("--n-problems", type=int, default=36)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--key-attempts", type=int, default=3,
                    help="regenerate a problem up to N times until its key is self-consistent")
    ap.add_argument("--no-verify-key", dest="verify_key", action="store_false",
                    help="disable problem key self-consistency (independent re-solve)")
    ap.set_defaults(verify_key=True)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=os.path.join(RUN_DIR, "candidates.json"))
    args = ap.parse_args()

    _load_env_key()
    client = llm_mod.LLMClient(args.generator_model)

    # Build targets. Cards cycle the finest-unit anchors; problems spread the gold.
    card_anchors = _load_gold(GOLD_CARDS)
    card_targets = []
    for i in range(args.n_cards):
        a = card_anchors[i % len(card_anchors)]
        card_targets.append({"id": f"cardtgt-{i:03d}", "topic": a["topic"],
                             "blueprint_area": a["blueprint_area"],
                             "query": a["front"], "gold": a})
    problem_gold = _spread(_load_gold(GOLD_PROBLEMS), args.n_problems)
    problem_targets = [{"id": g["id"], "topic": g["topic"],
                        "blueprint_area": g["blueprint_area"],
                        "query": f"{g['blueprint_area']} physics problem", "gold": g}
                       for g in problem_gold]

    # Serial phase: retrieval + local baselines (thread-unsafe libs stay single).
    kb, vb = KeywordBaseline(args.db), VectorBaseline(args.db)
    conn = retrieval.open_index(args.db)
    candidates: list[dict] = []
    gold_out: dict[str, dict] = {}
    for t in card_targets + problem_targets:
        kind = "card" if t["id"].startswith("cardtgt") else "problem"
        gold_out[t["id"]] = {**t["gold"], "id": t["id"]}
        t["retrieved"] = retrieval.search(t["query"], k=gc.CONTEXT_CHUNKS, conn=conn)
        base_target = {"id": t["id"], "query": t["query"], "kind": kind,
                       "blueprint_area": t["blueprint_area"], "topic": t["topic"]}
        candidates.append(candidate(kb, base_target))
        candidates.append(candidate(vb, base_target))
    conn.close()
    kb.close()
    vb.close()
    print(f"[serial] retrieved + baselines for {len(card_targets)} cards, "
          f"{len(problem_targets)} problems")

    # Threaded phase: the LLM generation calls.
    done = {"n": 0}
    total = len(card_targets) + 2 * len(problem_targets)

    def gen_card(t: dict) -> dict:
        item = gc.generate_card(topic=t["topic"], retrieved=t["retrieved"], llm=client)
        item.update({"system": "ai", "target_id": t["id"], "blueprint_area": t["blueprint_area"]})
        return item

    def gen_problem(t: dict) -> dict:
        item = gc.generate_problem(topic=t["topic"], retrieved=t["retrieved"], llm=client,
                                   verify_key=args.verify_key, attempts=args.key_attempts)
        item.update({"system": "ai", "target_id": t["id"], "blueprint_area": t["blueprint_area"]})
        return item

    def gen_naive(t: dict) -> dict:
        context = gc.build_context(t["retrieved"])
        try:
            raw = client.complete_json(NAIVE_SYSTEM, f"TOPIC: {t['topic']}\n\nCORPUS CONTEXT:\n{context}")
        except Exception as exc:  # noqa: BLE001
            return {"system": "naive", "target_id": t["id"], "kind": "problem",
                    "blueprint_area": t["blueprint_area"], "topic": t["topic"],
                    "refused": True, "refusal_reason": str(exc)}
        return {"system": "naive", "target_id": t["id"], "kind": "problem",
                "blueprint_area": t["blueprint_area"], "topic": t["topic"], "refused": False,
                "stem": raw.get("stem", ""), "choices": raw.get("choices", []),
                "key": raw.get("key", ""), "distractor_rationales": {},
                "source_ref": t["retrieved"][0].source_ref if t["retrieved"] else None}

    def run(fn, t):
        try:
            res = fn(t)
        except Exception as exc:  # noqa: BLE001
            res = {"system": "ai", "target_id": t["id"], "refused": True, "refusal_reason": str(exc)}
        with _print_lock:
            done["n"] += 1
            if done["n"] % 10 == 0 or done["n"] == total:
                print(f"[gen] {done['n']}/{total}")
        return res

    jobs = [(gen_card, t) for t in card_targets]
    jobs += [(gen_problem, t) for t in problem_targets]
    jobs += [(gen_naive, t) for t in problem_targets]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for res in pool.map(lambda jt: run(jt[0], jt[1]), jobs):
            candidates.append(res)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(candidates, open(args.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(gold_out, open(os.path.join(RUN_DIR, "batch_gold.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    n_ai = sum(1 for c in candidates if c.get("system") == "ai")
    n_refused = sum(1 for c in candidates if c.get("system") == "ai" and c.get("refused"))
    print(f"[done] {len(candidates)} candidates ({n_ai} ai, {n_refused} ai-refused)")
    print(f"[out] {args.out}")


if __name__ == "__main__":
    main()
