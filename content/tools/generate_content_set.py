"""Generate the real, corpus-grounded default content set for pgrep (Task P4).

Unlike ``run_batch.py`` (the gold-anchored *gate* batch), this driver builds the
shippable study set: weight-proportional across the 9 blueprint areas and 25
finest units, grounded ONLY in the corpus index, tagged to the locked
``topic::*`` slugs, and verified with the same shared core the app uses
(provenance cite-or-refuse, giveaway verifier, CAS/SymPy, problem key
self-consistency, confidence routing).

The gold set is NEVER read here: targets come from ``blueprint.json`` alone, and
every prompt is fed only the corpus chunks retrieval returns. Generated items are
then run through the section-6 leakage safeguards (within-batch dedup, plus
reject-memorized against every ETS form and every fed example).

A tiny bit of input hygiene sits in front of the shipped verifiers: a model may
write a computational expression with ``^`` for a power, which SymPy's parser
reads as XOR. We normalize ``^`` to ``**`` (and a few unicode math glyphs) on the
``computational.expression`` field only, so the shipped CAS check grades the
expression the model meant. Nothing else about the shipped pipeline is altered.

A bounded top-up pass then generates extra problems for any category short on
clean, key-confirmed items, so the problem bank always fills a full
70-question exam-mode form.

Outputs (default ``content/run/p4/``):
  - content_set.json        every landable-candidate item, metadata + verify flags
  - exam_form.json          a >=70-question exam-mode form (clean, key-confirmed)
  - dropped_duplicates.json within-batch near-duplicates that were dropped
  - rejected_memorized.json items too close to an ETS/fed example (firewall)
  - summary.json            per-area counts, pass/flag tallies, safeguards, spend

Run:
    conda run -n pgrep-ai python content/tools/generate_content_set.py \
        --generator-model gpt-5.5-2026-04-23 --workers 12
    conda run -n pgrep-ai python content/tools/generate_content_set.py --plan-only
    conda run -n pgrep-ai python content/tools/generate_content_set.py --smoke 4
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import _ai_path

_ai_path.add_ai_core()

import eval_splits as splits  # noqa: E402

from pgrep.ai import generation_core as gc  # noqa: E402
from pgrep.ai import llm as llm_mod  # noqa: E402
from pgrep.ai import retrieval  # noqa: E402
from pgrep.ai import verify  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
DEFAULT_DB = os.path.join(CONTENT, "index", "corpus.db")
BLUEPRINT = os.path.join(CONTENT, "blueprint", "blueprint.json")
DEFAULT_OUT = os.path.join(CONTENT, "run", "p4")
REPO = os.path.dirname(CONTENT)
DEFAULT_BUNDLE = os.path.join(REPO, "pylib", "anki", "pgrep", "content_bundle.json")

# Full-bundle tier target (blueprint.json coverage_targets.nominal_example):
# 350 cards / 140 problems, weight-proportional by category.
CATEGORY_TARGETS = {
    "mechanics": {"cards": 70, "problems": 28},
    "electromagnetism": {"cards": 63, "problems": 25},
    "quantum": {"cards": 45, "problems": 18},
    "thermodynamics": {"cards": 35, "problems": 14},
    "atomic": {"cards": 35, "problems": 14},
    "optics_waves": {"cards": 28, "problems": 11},
    "special_relativity": {"cards": 21, "problems": 8},
    "lab": {"cards": 21, "problems": 8},
    "specialized": {"cards": 32, "problems": 14},
}

_print_lock = threading.Lock()


# --- LLM input hygiene (expression only) -----------------------------------

_EXPR_SUBS = {"\u00d7": "*", "\u00b7": "*", "\u2212": "-", "\u221a": "sqrt",
              "\u00b2": "**2", "\u00b3": "**3", "\u2070": "**0", "\u00b9": "**1",
              "\u2074": "**4", "\u2075": "**5", "\u2076": "**6"}


def normalize_expression(expr: str) -> str:
    """Make a model expression parseable by SymPy: ``^`` power, unicode math."""
    for a, b in _EXPR_SUBS.items():
        expr = expr.replace(a, b)
    # ``^`` is XOR in SymPy's parser; a physics expression means exponent.
    expr = expr.replace("^", "**").replace("****", "**")
    return expr


class NormalizingLLM:
    """Wrap the pinned client and normalize any ``computational.expression`` it
    returns, so the shipped CAS check sees a valid power expression. The
    independent-solve response has no such field and passes through untouched."""

    def __init__(self, inner):
        self.inner = inner
        self.model = inner.model

    def complete_json(self, system: str, user: str) -> dict:
        d = self.inner.complete_json(system, user)
        if isinstance(d, dict):
            comp = d.get("computational")
            if isinstance(comp, dict) and isinstance(comp.get("expression"), str):
                comp["expression"] = normalize_expression(comp["expression"])
        return d


def _load_env_key() -> None:
    path = os.path.join(CONTENT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*OPENAI_API_KEY\s*=\s*(.+)", line)
        if m and m.group(1).strip() and not m.group(1).strip().startswith("<"):
            os.environ.setdefault("OPENAI_API_KEY", m.group(1).strip())


def _split_even(total: int, parts: int) -> list[int]:
    base, rem = divmod(total, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


def _aspects(ets_content: str) -> list[str]:
    raw = re.split(r",|;|\band\b|\bor\b", ets_content)
    out = []
    for a in raw:
        a = re.sub(r"\(.*?\)", "", a).strip(" .")
        a = re.sub(r"\s+", " ", a)
        if len(a) >= 3 and a.lower() not in {"minor"}:
            out.append(a)
    return out or [ets_content.strip()]


def _unit_common(cat: dict, unit: dict) -> dict:
    return {
        "category": cat["slug"], "category_name": cat["name"],
        "weight_pct": cat["weight_pct"], "blueprint_tag": unit["tag"],
        "finest_unit": unit["slug"], "unit_name": unit["name"],
        "ets_content": unit["ets_content"], "aspects": _aspects(unit["ets_content"]),
    }


def build_targets(bp: dict, scale: float = 1.0) -> tuple[list[dict], dict]:
    """One target per (finest unit, item index), from the blueprint only."""
    targets: list[dict] = []
    seq = {"card": 0, "problem": 0}
    for cat in bp["categories"]:
        tgt = CATEGORY_TARGETS[cat["slug"]]
        units = cat["finest_units"]
        for kind, key in (("card", "cards"), ("problem", "problems")):
            n = max(len(units), round(tgt[key] * scale))
            split = _split_even(n, len(units))
            for u_i, unit in enumerate(units):
                common = _unit_common(cat, unit)
                offset = len(common["aspects"]) // 2 if kind == "problem" else 0
                for i in range(split[u_i]):
                    seq[kind] += 1
                    pre = "card" if kind == "card" else "prob"
                    targets.append({**common, "kind": kind, "item_index": i + offset,
                                    "id": f"p4-{pre}-{seq[kind]:04d}"})
    return targets, seq


def topup_targets(cat: dict, n: int, start_seq: int) -> tuple[list[dict], int]:
    """Extra problem targets for one category, round-robin over its finest units."""
    units = cat["finest_units"]
    out, seq = [], start_seq
    for i in range(n):
        unit = units[i % len(units)]
        common = _unit_common(cat, unit)
        seq += 1
        # Push aspect/offset deeper so top-ups explore new corpus windows.
        out.append({**common, "kind": "problem",
                    "item_index": (i // len(units)) + len(common["aspects"]) // 2 + 3,
                    "id": f"p4-prob-{seq:04d}"})
    return out, seq


# Diagram-required share per area (topic-aware figure policy). A figure is only
# ever required where a diagram is genuinely natural; abstract areas skew
# text-only. See docs_pgrep/plan/2026-07-06-content-pipeline-triple-pool-design.md.
FIGURE_SHARE = {
    "mechanics": 0.50, "electromagnetism": 0.45, "quantum": 0.15,
    "thermodynamics": 0.40, "atomic": 0.15, "optics_waves": 0.55,
    "special_relativity": 0.10, "lab": 0.40, "specialized": 0.15,
}

# Appended to a problem's generation instruction so figure need is decided up
# front, not guessed later. The setup is always described fully in words; the
# figure only carries symbolic geometry.
FIGURE_INSTR = (
    " PRESENTATION: this problem is shown WITH a labeled diagram. Author a setup "
    "whose geometry or circuit topology is genuinely clarified by a figure. "
    "Describe the setup fully in words and keep ALL numeric values and units in "
    "the text; the figure carries only symbolic labels. Reference the figure "
    "naturally, for example 'in the figure shown'."
)
TEXTONLY_INSTR = (
    " PRESENTATION: this problem is TEXT-ONLY. Make it fully self-contained in "
    "prose and LaTeX. Do not reference any figure, diagram, or 'as shown' image."
)

# Appended to every grow instruction. Corpus-grounded generation otherwise copies
# the textbook's governing formula straight into the stem, which hands the solver
# the method (for example 'using f = c/lambda' or 'the period is T = 2*pi*sqrt(L/g)').
# This forbids that: give data, never the relation being tested.
NO_GIVEAWAY_INSTR = (
    " DO NOT hand the solver the governing relation, formula, or solution technique "
    "the problem is testing. State only the given quantities and the physical setup; "
    "the solver must recall or derive the relation. For example, give a frequency as "
    "a number, never as 'f = c/lambda'; never write 'using E_n = -13.6/n^2', 'recall "
    "that ...', 'apply the ... formula', or otherwise name the method. Standard "
    "constants (c, g, h) as plain values are fine."
)


def assign_figure_required(targets: list[dict]) -> None:
    """Stamp ``figure_required`` on problem targets by the topic-aware policy.

    Per area the first ``round(share * n)`` problems (sorted by id) require a
    figure; the rest are text-only. Deterministic and area-local.
    """
    from collections import defaultdict as _dd

    by_area: dict[str, list[dict]] = _dd(list)
    for t in targets:
        if t.get("kind") == "problem":
            by_area[t.get("category", "")].append(t)
    for _area, items in by_area.items():
        items.sort(key=lambda z: z.get("id", ""))
        k = round(FIGURE_SHARE.get(_area, 0.0) * len(items))
        for i, t in enumerate(items):
            t["figure_required"] = i < k


def build_grow_targets(bp: dict, n: int, start_seq: int) -> tuple[list[dict], int]:
    """``n`` new problem targets, weight-proportional across areas, ids from
    ``start_seq``. Largest-remainder allocation so the areas sum to exactly ``n``.
    """
    total_w = sum(c["weight_pct"] for c in bp["categories"]) or 1
    raw = {c["slug"]: n * c["weight_pct"] / total_w for c in bp["categories"]}
    floor = {k: int(v) for k, v in raw.items()}
    rem = n - sum(floor.values())
    for slug in sorted(raw, key=lambda k: raw[k] - floor[k], reverse=True)[:rem]:
        floor[slug] += 1
    cat_by_slug = {c["slug"]: c for c in bp["categories"]}
    targets: list[dict] = []
    seq = start_seq
    for cat in bp["categories"]:
        more, seq = topup_targets(cat_by_slug[cat["slug"]], floor[cat["slug"]], seq)
        targets.extend(more)
    return targets, seq


def _max_prob_seq(bundle_path: str) -> int:
    """Highest ``p4-prob-NNNN`` sequence in the bundle, so grow ids never collide."""
    b = json.load(open(bundle_path, encoding="utf-8"))
    seqs = [
        int(m.group(1))
        for p in b.get("problems", [])
        if (m := re.match(r"p4-prob-(\d+)$", str(p.get("id", ""))))
    ]
    return max(seqs) if seqs else 0


def bundle_stem_hashes(bundle_path: str) -> set[str]:
    """Normalized, figure-stripped stem hashes of the shipped problems, for dedup."""
    b = json.load(open(bundle_path, encoding="utf-8"))
    fig = re.compile(r'<div class="pg-figure">[\s\S]*?</div>')
    return {
        verify.normalized_front_hash(fig.sub(" ", str(p.get("stem", ""))))
        for p in b.get("problems", [])
    }


def _window(unit_name: str, aspect: str, item_index: int, conn) -> tuple[list, str]:
    """Retrieve a diversified corpus window for one item. Corpus only."""
    query = f"{unit_name}. {aspect}"
    offset = (item_index // 4) * 3
    k = gc.CONTEXT_CHUNKS + offset
    retrieved = retrieval.search(query, k=k, conn=conn)
    window = retrieved[offset:offset + gc.CONTEXT_CHUNKS]
    if len(window) < gc.CONTEXT_CHUNKS:
        window = retrieved[:gc.CONTEXT_CHUNKS]
    return window, query


def enrich(item: dict, t: dict, query: str) -> dict:
    item["id"] = t["id"]
    item["kind"] = t["kind"]
    item["blueprint_area"] = t["category"]
    item["category_name"] = t["category_name"]
    item["weight_pct"] = t["weight_pct"]
    item["blueprint_tag"] = t["blueprint_tag"]
    item["finest_unit"] = t["finest_unit"]
    item["unit_name"] = t["unit_name"]
    item["retrieval_query"] = query
    item["generator_topic"] = item.get("topic")
    item["figure_required"] = bool(t.get("figure_required"))
    flags = []
    if item.get("refused"):
        flags.append("refused:" + str(item.get("refusal_reason", "unspecified"))[:90])
    if item.get("needs_review") and not item.get("refused"):
        flags.append("needs_review:" + str(item.get("review_reason", "low confidence"))[:90])
    comp = item.get("computational")
    if isinstance(comp, dict) and comp.get("expression") and item.get("cas_verified") is False:
        flags.append("cas_failed")
    if item["kind"] == "problem" and not item.get("refused") and item.get("key_self_consistent") is False:
        flags.append("key_unconfirmed")
    item["flags"] = flags
    item["status"] = "flagged" if flags else "clean"
    return item


def _item_text(it: dict) -> str:
    parts = [str(it.get("front", "")), str(it.get("back", "")), str(it.get("stem", ""))]
    parts += [str(c) for c in it.get("choices", []) if c]
    return " ".join(p for p in parts if p)


def generate_for_targets(targets: list[dict], client, db: str, workers: int,
                         t0: float, label: str, ckpt: str | None = None) -> list[dict]:
    """Serial retrieval + threaded generation for a list of targets."""
    conn = retrieval.open_index(db)
    try:
        for t in targets:
            aspect = t["aspects"][t["item_index"] % len(t["aspects"])]
            t["retrieved"], t["query"] = _window(t["unit_name"], aspect, t["item_index"], conn)
    finally:
        conn.close()
    print(f"[serial:{label}] retrieved windows for {len(targets)} targets ({time.time()-t0:.0f}s)")

    done = {"n": 0}
    total = len(targets)
    results: list[dict] = []

    def gen(t: dict) -> dict:
        try:
            if t["kind"] == "card":
                item = gc.generate_card(topic=t["query"], retrieved=t["retrieved"], llm=client)
            else:
                suffix = (FIGURE_INSTR if t.get("figure_required") else TEXTONLY_INSTR)
                suffix += NO_GIVEAWAY_INSTR
                item = gc.generate_problem(topic=t["query"] + suffix, retrieved=t["retrieved"],
                                           llm=client, verify_key=True, attempts=3)
        except Exception as exc:  # noqa: BLE001
            item = {"kind": t["kind"], "refused": True,
                    "refusal_reason": f"generation error: {type(exc).__name__}: {exc}",
                    "confidence": 0.0, "needs_review": True, "source_ref": None}
        item = enrich(item, t, t.get("query", ""))
        with _print_lock:
            done["n"] += 1
            results.append(item)
            if done["n"] % 20 == 0 or done["n"] == total:
                print(f"[gen:{label}] {done['n']}/{total}  ({time.time()-t0:.0f}s)")
                if ckpt:
                    json.dump(results, open(ckpt, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        return item

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(gen, targets))
    return results


def dedup_and_firewall(
    items: list[dict], seen_hashes: set[str] | None = None
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Within-batch near-dup drop, then reject-memorized vs ETS + fed examples.

    ``seen_hashes`` preloads normalized stem hashes (for example the shipped
    bundle) so a new item that clones an existing stem is dropped too.
    """
    seen: set[str] = set(seen_hashes or set())
    kept, dropped = [], []
    for it in items:
        front = it.get("front") or it.get("stem") or ""
        if not front:
            kept.append(it)
            continue
        h = verify.normalized_front_hash(front)
        if h in seen:
            it["dropped_reason"] = "within-batch duplicate"
            dropped.append(it)
        else:
            seen.add(h)
            kept.append(it)
    gen_for_check = [{"id": it["id"], "text": _item_text(it)} for it in kept
                     if not it.get("refused")]
    report = splits.reject_memorized(gen_for_check)
    rejected = {d["id"]: d["similarity"] for d in report.dropped}
    final, memorized = [], []
    for it in kept:
        if it["id"] in rejected:
            it["dropped_reason"] = f"reject-memorized (sim={rejected[it['id']]})"
            it["status"] = "flagged"
            memorized.append(it)
        else:
            final.append(it)
    return final, dropped, memorized, report.as_dict()


def is_clean_problem(it: dict) -> bool:
    return (it["kind"] == "problem" and it["status"] == "clean"
            and not it.get("refused") and bool(it.get("source_ref"))
            and it.get("key") in ("A", "B", "C", "D", "E")
            and it.get("key_self_consistent") is not False)


def clean_problems_by_cat(items: list[dict]) -> dict[str, list[dict]]:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        if is_clean_problem(it):
            by_cat[it["blueprint_area"]].append(it)
    return by_cat


def build_exam_form(items: list[dict], bp: dict) -> dict:
    by_cat = clean_problems_by_cat(items)
    form, per_cat = [], {}
    for cat in bp["categories"]:
        slug = cat["slug"]
        need = cat["readiness_questions"]
        avail = by_cat.get(slug, [])
        take = avail[:need]
        per_cat[slug] = {"need": need, "selected": len(take), "available": len(avail)}
        form.extend(x["id"] for x in take)
    return {"n": len(form), "target": sum(c["readiness_questions"] for c in bp["categories"]),
            "complete": len(form) >= sum(c["readiness_questions"] for c in bp["categories"]),
            "per_category": per_cat, "item_ids": form}


def _run_grow(bp: dict, args) -> None:
    """Grow mode: generate N extra problems (diagram-aware), dedup vs the bundle.

    Problems only (no cards, no exam form). Writes a content_set.json shaped like
    the default driver so the review and landing tools read it unchanged. Never
    applies to the bundle; the orchestrator merges and lands.
    """
    start = _max_prob_seq(args.bundle)
    targets, _ = build_grow_targets(bp, args.grow, start)
    assign_figure_required(targets)
    if args.only_area:
        wanted = {a.strip() for a in args.only_area.split(",") if a.strip()}
        targets = [t for t in targets if t["category"] in wanted]
    if not targets:
        sys.exit(f"no targets (only_area={args.only_area!r} matched nothing?)")

    if args.plan_only:
        from collections import Counter
        cc = Counter(t["category"] for t in targets)
        fig = sum(1 for t in targets if t.get("figure_required"))
        print(f"grow targets: {len(targets)} problems, figure_required={fig}, "
              f"ids p4-prob-{start + 1:04d}..")
        for slug in sorted(cc):
            af = sum(1 for t in targets
                     if t["category"] == slug and t.get("figure_required"))
            print(f"  {slug:20} n={cc[slug]:3}  figure_required={af}")
        return

    _load_env_key()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("no OPENAI_API_KEY (content/.env)")
    client = NormalizingLLM(llm_mod.LLMClient(args.generator_model))
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()

    raw = generate_for_targets(
        targets, client, args.db, args.workers, t0, "grow",
        ckpt=os.path.join(args.out, "content_set.partial.json"),
    )
    seen = bundle_stem_hashes(args.bundle)
    final, dropped, memorized, reject_report = dedup_and_firewall(raw, seen)

    clean = sum(1 for it in final if it["status"] == "clean")
    fig_req = sum(1 for it in final if it.get("figure_required"))
    summary = {
        "mode": "grow",
        "generator_model": args.generator_model,
        "prompt_versions": {"problem": gc.PROBLEM_PROMPT_VERSION},
        "requested": args.grow,
        "only_area": args.only_area or None,
        "generated": len(raw),
        "landable_candidates": len(final),
        "clean": clean,
        "flagged": len(final) - clean,
        "figure_required": fig_req,
        "dropped_duplicates": len(dropped),
        "rejected_memorized": len(memorized),
        "reject_report": reject_report,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    out = args.out
    json.dump(final, open(os.path.join(out, "content_set.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    json.dump(dropped, open(os.path.join(out, "dropped_duplicates.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    json.dump(memorized, open(os.path.join(out, "rejected_memorized.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    json.dump(summary, open(os.path.join(out, "summary.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    partial = os.path.join(out, "content_set.partial.json")
    if os.path.exists(partial):
        os.remove(partial)
    print("=" * 60)
    print(json.dumps(summary, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the pgrep default content set.")
    ap.add_argument("--generator-model", default="gpt-5.5-2026-04-23")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--smoke", type=int, default=0)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--no-topup", dest="topup", action="store_false")
    ap.add_argument("--topup-rounds", type=int, default=4)
    ap.add_argument("--topup-cap", type=int, default=140, help="max extra problems total")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--grow", type=int, default=0,
                    help="grow mode: generate N extra problems (diagram-aware)")
    ap.add_argument("--only-area", default="",
                    help="restrict grow to one blueprint area slug")
    ap.add_argument("--bundle", default=DEFAULT_BUNDLE,
                    help="bundle for grow id continuation and dedup")
    ap.set_defaults(topup=True)
    args = ap.parse_args()

    bp = json.load(open(BLUEPRINT, encoding="utf-8"))
    if args.grow:
        _run_grow(bp, args)
        return
    targets, seq = build_targets(bp, scale=args.scale)
    cards = [t for t in targets if t["kind"] == "card"]
    probs = [t for t in targets if t["kind"] == "problem"]
    if args.smoke:
        cards, probs = cards[:args.smoke], probs[:args.smoke]
        targets = cards + probs

    if args.plan_only:
        from collections import Counter
        cc = Counter((t["category"], t["kind"]) for t in targets)
        print(f"targets: {len(cards)} cards, {len(probs)} problems")
        for cat in bp["categories"]:
            s = cat["slug"]
            print(f"  {s:20} cards={cc[(s,'card')]:3}  problems={cc[(s,'problem')]:3}"
                  f"  readiness_q={cat['readiness_questions']}")
        print(f"exam-form target: {sum(c['readiness_questions'] for c in bp['categories'])}")
        return

    _load_env_key()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("no OPENAI_API_KEY (content/.env)")
    client = NormalizingLLM(llm_mod.LLMClient(args.generator_model))
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()
    cat_by_slug = {c["slug"]: c for c in bp["categories"]}

    raw = generate_for_targets(targets, client, args.db, args.workers, t0, "base",
                               ckpt=os.path.join(args.out, "content_set.partial.json"))
    final, dropped, memorized, reject_report = dedup_and_firewall(raw)

    # Bounded top-up: fill any category short on clean, key-confirmed problems.
    topup_added = 0
    if args.topup and not args.smoke:
        for rnd in range(args.topup_rounds):
            by_cat = clean_problems_by_cat(final)
            shortfall = {c["slug"]: c["readiness_questions"] - len(by_cat.get(c["slug"], []))
                         for c in bp["categories"]}
            shortfall = {k: v for k, v in shortfall.items() if v > 0}
            if not shortfall or topup_added >= args.topup_cap:
                break
            tt: list[dict] = []
            for slug, short in shortfall.items():
                want = min(short * 2 + 1, args.topup_cap - topup_added - len(tt))
                if want <= 0:
                    continue
                more, seq["problem"] = topup_targets(cat_by_slug[slug], want, seq["problem"])
                tt.extend(more)
            if not tt:
                break
            print(f"[topup r{rnd+1}] {len(tt)} problems for short cats: "
                  f"{ {k: v for k, v in shortfall.items()} }")
            more_raw = generate_for_targets(tt, client, args.db, args.workers, t0,
                                            f"topup{rnd+1}")
            topup_added += len(tt)
            raw += more_raw
            final, dropped, memorized, reject_report = dedup_and_firewall(raw)

    exam = build_exam_form(final, bp)

    # Summaries.
    per_area = defaultdict(lambda: {"cards": 0, "problems": 0, "cards_clean": 0,
                                    "problems_clean": 0, "cards_flagged": 0, "problems_flagged": 0})
    flag_reasons = defaultdict(int)
    for it in final:
        a = per_area[it["blueprint_area"]]
        base = "cards" if it["kind"] == "card" else "problems"
        a[base] += 1
        if it["status"] == "clean":
            a[base[:-1] + "s_clean"] += 1
        else:
            a[base[:-1] + "s_flagged"] += 1
            for f in it.get("flags", []):
                flag_reasons[f.split(":", 1)[0]] += 1

    n_cards = sum(1 for it in final if it["kind"] == "card")
    n_probs = sum(1 for it in final if it["kind"] == "problem")
    clean_cards = sum(1 for it in final if it["kind"] == "card" and it["status"] == "clean")
    clean_probs = sum(1 for it in final if it["kind"] == "problem" and it["status"] == "clean")
    summary = {
        "generator_model": args.generator_model,
        "prompt_versions": {"card": gc.CARD_PROMPT_VERSION, "problem": gc.PROBLEM_PROMPT_VERSION},
        "corpus_index": {"db": os.path.relpath(args.db, CONTENT),
                         "embed_model": retrieval.MODEL_NAME},
        "expression_hygiene": "normalized ^ -> ** and unicode math on computational.expression before shipped CAS",
        "totals": {
            "generated": len(raw), "landable_candidates": len(final),
            "cards": n_cards, "cards_clean": clean_cards, "cards_flagged": n_cards - clean_cards,
            "problems": n_probs, "problems_clean": clean_probs, "problems_flagged": n_probs - clean_probs,
            "problems_topup_generated": topup_added,
            "dropped_duplicates": len(dropped), "rejected_memorized": len(memorized),
        },
        "flag_reasons": dict(flag_reasons),
        "per_area": {k: dict(v) for k, v in per_area.items()},
        "exam_form": {k: exam[k] for k in ("n", "target", "complete", "per_category")},
        "safeguards": {
            "name_split": splits.name_split(),
            "seen_vs_held": splits.seen_vs_held_report(dedup_applied=True),
            "reject_memorized": reject_report,
            "corpus_only": "every prompt fed corpus chunks only; gold/heldout/tier3 never read",
        },
        "elapsed_sec": round(time.time() - t0, 1),
    }

    out = args.out
    json.dump(final, open(os.path.join(out, "content_set.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(exam, open(os.path.join(out, "exam_form.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(dropped, open(os.path.join(out, "dropped_duplicates.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(memorized, open(os.path.join(out, "rejected_memorized.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(summary, open(os.path.join(out, "summary.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    partial = os.path.join(out, "content_set.partial.json")
    if os.path.exists(partial):
        os.remove(partial)

    print("=" * 66)
    print(f"content set: {len(final)} landable ({clean_cards+clean_probs} clean, "
          f"{len(final)-clean_cards-clean_probs} flagged)")
    print(f"  cards: {n_cards} ({clean_cards} clean)   problems: {n_probs} ({clean_probs} clean, "
          f"{topup_added} top-up generated)")
    print(f"  dropped dups: {len(dropped)}   rejected-memorized: {len(memorized)}")
    print(f"  exam form: {exam['n']}/{exam['target']} (complete={exam['complete']})")
    print(f"  flag reasons: {dict(flag_reasons)}")
    print(f"out: {out}   elapsed: {summary['elapsed_sec']}s")


if __name__ == "__main__":
    main()
