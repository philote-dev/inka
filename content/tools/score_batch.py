"""Score a generated batch against the gold set, one command (L4.0e).

Ties the harness together: load the gold set and the candidate items from every
system (ai, keyword, vector, naive), apply the section-6 safeguards, blind-shuffle
the candidates, score them with two raters (Frank plus the LLM judge; the smoke
mode stands both in offline), then emit the gate metrics with bootstrap CIs, the
per-area breakdown, the beat-baseline comparison, inter-rater kappa, and a pinned
run manifest.

This is the ruler. It reads gold and candidates only, never the corpus index for
generation, and it holds the real scored batch until the gold sets land.

Run the offline smoke (proves the pipeline end to end, not graded):
    conda run -n pgrep-ai python content/tools/score_batch.py --smoke
Score a real batch once gold and a generated batch exist:
    conda run -n pgrep-ai python content/tools/score_batch.py \
        --gold content/gold/cards content/gold/problems \
        --candidates run/batch.json --judge openai \
        --generator-model <snapshot> --judge-model <other-snapshot> \
        --rater1-csv run/frank.csv
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
from collections import defaultdict

import eval_manifest as manifest
import eval_metrics as metrics
import eval_splits as splits
from eval_judge import make_judge

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
DEFAULT_DB = os.path.join(CONTENT, "index", "corpus.db")
RUN_DIR = os.path.join(CONTENT, "run")

BASELINE_SYSTEMS = ("keyword", "vector")


def _load_env_key() -> None:
    """Load OPENAI_API_KEY from content/.env so the judge can run."""
    import re

    path = os.path.join(CONTENT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*OPENAI_API_KEY\s*=\s*(.+)", line)
        if m and m.group(1).strip() and not m.group(1).strip().startswith("<"):
            os.environ.setdefault("OPENAI_API_KEY", m.group(1).strip())


def load_gold(paths: list[str]) -> dict[str, dict]:
    """Load gold from directories of *.json, or a single JSON file (dict or list)."""
    gold: dict[str, dict] = {}
    for p in paths:
        if os.path.isfile(p) and p.endswith(".json"):
            try:
                data = json.load(open(p, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rows = data.values() if isinstance(data, dict) else data
            for it in rows:
                if isinstance(it, dict) and it.get("id"):
                    gold[it["id"]] = it
        elif os.path.isdir(p):
            for path in sorted(glob.glob(os.path.join(p, "*.json"))):
                try:
                    it = json.load(open(path, encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if isinstance(it, dict) and it.get("id"):
                    gold[it["id"]] = it
    return gold


def candidate_text(cand: dict) -> str:
    parts = [str(cand.get(k, "")) for k in ("front", "back", "stem", "text")]
    parts += [str(c) for c in cand.get("choices", [])]
    return " ".join(p for p in parts if p)


def synth_rater1(rater2: list[dict], seed: int = 7) -> list[dict]:
    """Smoke only: perturb the judge's labels to stand in for a human rater."""
    rng = random.Random(seed)
    out = []
    for j in rater2:
        jj = json.loads(json.dumps(j))
        if rng.random() < 0.15:
            jj["useful"] = not jj.get("useful")
        if rng.random() < 0.08:
            jj["fact_precision"] = not jj.get("fact_precision")
        out.append(jj)
    return out


def attach_meta(judgment: dict, cand: dict) -> dict:
    judgment.update({
        "target_id": cand.get("target_id"),
        "system": cand.get("system"),
        "kind": cand.get("kind"),
        "blueprint_area": cand.get("blueprint_area"),
        "topic": cand.get("topic"),
    })
    return judgment


def gate_check_card(summary: dict, beat: dict, cut: dict) -> dict:
    checks = {
        "fact_precision": summary["fact_precision"]["point"] >= cut.get("fact_precision", 0.95),
        "useful_yield": summary["useful_yield"]["point"] >= cut.get("useful_yield", 0.80),
        "batch_size": summary["n"] >= cut.get("batch_size", 50),
        "beats_baseline": beat["passes"],
    }
    return {"checks": checks, "passes": all(checks.values())}


def gate_check_problem(summary: dict, beat: dict, cut: dict) -> dict:
    checks = {
        "key_correctness": summary["key_correctness"]["point"] >= cut.get("key_correctness", 0.95),
        "distractor_quality_per_problem":
            summary["distractor_quality_per_problem"]["point"] >= cut.get("distractor_quality", 0.70),
        "useful_yield": summary["useful_yield"]["point"] >= cut.get("useful_yield", 0.75),
        "batch_size": summary["n"] >= cut.get("batch_size", 30),
        "beats_baseline": beat["passes"],
    }
    return {"checks": checks, "passes": all(checks.values())}


def main() -> None:
    ap = argparse.ArgumentParser(description="Score a generated batch against the gold set.")
    ap.add_argument("--smoke", action="store_true", help="run the offline self-generated smoke batch")
    ap.add_argument("--gold", nargs="*", default=[], help="gold directories")
    ap.add_argument("--candidates", help="JSON list of candidate items")
    ap.add_argument("--judge", default="fake", choices=["fake", "heuristic", "openai", "none"])
    ap.add_argument("--generator-model", default="(unset)")
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rater1-csv", default=None, help="human rater (Frank) labels")
    ap.add_argument("--provisional", action="store_true",
                    help="LLM judge only; Frank rating + adjudication deferred (E4)")
    ap.add_argument("--workers", type=int, default=1, help="parallel judge calls")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=os.path.join(RUN_DIR, "score_report.json"))
    args = ap.parse_args()

    if args.judge == "openai":
        _load_env_key()

    # Load or build the batch.
    if args.smoke:
        import smoke_batch
        gold, candidates = smoke_batch.build(args.db)
        generator_model = "smoke-generator"
        judge_mode = "fake"
    else:
        gold = load_gold(args.gold)
        if not gold:
            print("no gold items found. The gate is held until the gold sets land under "
                  "content/gold/cards and content/gold/problems.")
            raise SystemExit(2)
        if not args.candidates:
            raise SystemExit("provide --candidates or use --smoke")
        candidates = json.load(open(args.candidates, encoding="utf-8"))
        generator_model = args.generator_model
        judge_mode = args.judge

    cut = manifest.load_prereg()

    # Safeguard 1 + 4: name the split, report seen vs held.
    split = splits.name_split()
    # Safeguard 3: reject memorized AI outputs (near-copies of any ETS item).
    ai_items = [{"id": c.get("target_id"), "text": candidate_text(c)}
                for c in candidates if c.get("system") == "ai"]
    reject = splits.reject_memorized(ai_items)
    # Safeguard 2: cross-form dedup of the gold items against fed forms.
    gold_items = [{"id": gid, "text": candidate_text(g)} for gid, g in gold.items()]
    xdedup = splits.cross_form_dedup(gold_items)
    seen_held = splits.seen_vs_held_report(dedup_applied=True)

    # Blind shuffle, then score with rater 2 (the judge).
    order = list(candidates)
    random.Random(args.seed).shuffle(order)
    judge = make_judge(judge_mode, args.judge_model)

    def _judge_one(cand: dict) -> dict:
        g = gold.get(cand.get("target_id"), {})
        return attach_meta(judge.judge(cand, g, cand.get("kind", "card")), cand)

    if args.workers > 1 and judge_mode == "openai":
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rater2 = list(pool.map(_judge_one, order))
    else:
        rater2 = [_judge_one(cand) for cand in order]

    # Rater 1 (Frank). Synthesized in smoke; a CSV would supply real labels.
    if args.rater1_csv and os.path.exists(args.rater1_csv):
        rater1 = _load_rater1_csv(args.rater1_csv, rater2)
        adjudicated = rater1
        rater_note = "rater1=Frank (csv), rater2=judge, adjudicated=Frank"
    elif args.smoke:
        rater1 = synth_rater1(rater2)
        adjudicated = rater1
        rater_note = "smoke: both raters stood in offline; adjudicated=synthetic rater1"
    elif args.provisional:
        rater1 = rater2
        adjudicated = rater2
        rater_note = ("PROVISIONAL: LLM judge only (rater 2); Frank rating and "
                      "adjudication deferred (E4). Keys are authoritative.")
    else:
        rater1 = rater2
        adjudicated = rater2
        rater_note = "PREVIEW: rater2 (judge) only; the gate needs Frank as rater1 and adjudicator"

    # Group adjudicated judgments by system and kind.
    by_sk: dict[tuple, list] = defaultdict(list)
    for j in adjudicated:
        by_sk[(j["system"], j["kind"])].append(j)

    kinds = sorted({j["kind"] for j in adjudicated})
    report: dict = {"rater_note": rater_note, "systems": {}, "gate": {}, "beat_baseline": {},
                    "per_area": {}, "naive_comparison": {}}

    for kind in kinds:
        ai_j = by_sk.get(("ai", kind), [])
        report["systems"][kind] = {
            sys_name: metrics.summarize(by_sk.get((sys_name, kind), []), kind, seed=args.seed)
            for sys_name in ("ai", *BASELINE_SYSTEMS, "naive")
            if by_sk.get((sys_name, kind))
        }
        report["per_area"][kind] = metrics.per_area_breakdown(ai_j, kind, seed=args.seed)
        base_j = {s: by_sk.get((s, kind), []) for s in BASELINE_SYSTEMS if by_sk.get((s, kind))}
        margin = cut.get("beat_baseline", {}).get("headline_margin", 0.10)
        beat = metrics.beat_baseline(ai_j, base_j, kind, margin=margin, seed=args.seed)
        report["beat_baseline"][kind] = beat
        ai_summary = report["systems"][kind].get("ai", {"n": 0})
        if kind == "card" and ai_summary.get("n"):
            report["gate"][kind] = gate_check_card(ai_summary, beat, cut.get("card", {}))
        elif kind == "problem" and ai_summary.get("n"):
            report["gate"][kind] = gate_check_problem(ai_summary, beat, cut.get("problem", {}))
            naive_j = by_sk.get(("naive", kind), [])
            if naive_j:
                ai_by = {j["target_id"]: metrics.headline_value(j, kind) for j in ai_j}
                nv_by = {j["target_id"]: metrics.headline_value(j, kind) for j in naive_j}
                common = [t for t in ai_by if t in nv_by]
                adv = metrics.paired_advantage_ci([ai_by[t] for t in common],
                                                  [nv_by[t] for t in common], seed=args.seed)
                report["naive_comparison"][kind] = {
                    "note": "reported comparison only, not a gate",
                    "ai_minus_naive": adv.as_dict()}

    # Inter-rater agreement, over the AI items Frank actually rated (blind).
    if rater1 is rater2:
        report["inter_rater"] = {"note": "single rater (LLM judge); kappa pending Frank (E4)"}
    else:
        paired = [(a, b) for a, b in zip(rater1, rater2) if a.get("_rated")]
        ku = metrics.cohens_kappa([bool(a.get("useful")) for a, _ in paired],
                                  [bool(b.get("useful")) for _, b in paired]) if paired else None
        card_pairs = [(a, b) for a, b in paired if a.get("kind") == "card"]
        kf = (metrics.cohens_kappa([bool(a.get("fact_precision")) for a, _ in card_pairs],
                                   [bool(b.get("fact_precision")) for _, b in card_pairs])
              if card_pairs else None)
        report["inter_rater"] = {
            "n_rated": len(paired), "kappa_useful": ku, "kappa_fact_precision": kf,
            "note": "kappa over the AI items Frank rated blind; rater1=Frank, rater2=LLM judge"}
    report["safeguards"] = {
        "name_split": split,
        "seen_vs_held": seen_held,
        "reject_memorized": reject.as_dict(),
        "cross_form_dedup_gold": xdedup.as_dict(),
    }

    # The pinned run manifest.
    embedding = {"model": "BAAI/bge-small-en-v1.5", "backend": "fastembed-onnx",
                 "parity_gate": "content/tools/check_parity.py (min_cosine 0.99)"}
    mani = manifest.build_manifest(
        round_id=cut.get("round", "L4.0-round-1"),
        generator_model=generator_model,
        judge_model=(judge.model),
        temperature=args.temperature,
        seed=args.seed,
        prompt_version=("smoke-0" if args.smoke else "unset"),
        prompt_text=("(smoke: no generation prompt)" if args.smoke else "(unset)"),
        corpus_index=manifest.corpus_index_version(args.db),
        embedding=embedding,
        gold=manifest.gold_version(os.path.join(CONTENT, "gold", "cards"),
                                   os.path.join(CONTENT, "gold", "problems")),
        cutoffs={k: cut[k] for k in ("card", "problem", "beat_baseline", "raters") if k in cut},
        seen_vs_held=seen_held,
        extra={"rater_note": rater_note, "smoke": bool(args.smoke)},
    )
    report["manifest"] = mani

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    manifest.write_manifest(mani, os.path.join(os.path.dirname(args.out), "run_manifest.json"))

    _print_report(report, args.out)


def _load_rater1_csv(path: str, rater2: list[dict]) -> list[dict]:
    """Overlay Frank's CSV labels onto the judged records, matched by target+system.

    Only non-empty cells overlay, so a field Frank did not rate keeps the judge's
    label. A matched record is marked ``_rated`` so kappa is computed over the
    items Frank saw, not the baseline items he never rated. ``distractors_ok``
    rewrites the four per-distractor flags so the per-problem distractor metric
    reflects his verdict.
    """
    import csv

    def truthy(v: str) -> bool:
        return v.strip().lower() in ("1", "true", "yes", "y")

    by_key: dict[tuple, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            by_key[(row.get("target_id"), row.get("system"))] = row
    out = []
    for j in rater2:
        row = by_key.get((j.get("target_id"), j.get("system")))
        jj = json.loads(json.dumps(j))
        if row:
            jj["_rated"] = True
            if row.get("useful", "").strip():
                jj["useful"] = truthy(row["useful"])
            if row.get("fact_precision", "").strip():
                jj["fact_precision"] = truthy(row["fact_precision"])
            if row.get("key_correct", "").strip():
                jj["key_correct"] = truthy(row["key_correct"])
            if row.get("distractors_ok", "").strip():
                val = truthy(row["distractors_ok"])
                jj["distractors"] = [{"plausible": val, "misconception_grounded": val,
                                      "non_overlapping": val, "source_grounded": val}
                                     for _ in range(4)]
        out.append(jj)
    return out


def _fmt(ci: dict) -> str:
    return f"{ci['point']:.3f} [{ci['low']:.3f}, {ci['high']:.3f}]"


def _print_report(report: dict, out_path: str) -> None:
    print("=" * 70)
    print("pgrep gold-set gate, batch score")
    print("=" * 70)
    print(report["rater_note"])
    for kind, systems in report["systems"].items():
        print(f"\n--- {kind} ---")
        for sysname, s in systems.items():
            if not s.get("n"):
                continue
            line = f"  {sysname:8} n={s['n']:<4} useful_yield={_fmt(s['useful_yield'])}"
            if kind == "problem":
                line += f"  distractor/prob={_fmt(s['distractor_quality_per_problem'])}"
            print(line)
        beat = report["beat_baseline"].get(kind, {})
        if beat:
            print(f"  beat-baseline: best={beat.get('best_baseline')} passes={beat.get('passes')}")
            for bname, b in beat.get("per_baseline", {}).items():
                print(f"     vs {bname:8} advantage={_fmt(b['advantage'])} beats={b['beats']}")
        gate = report["gate"].get(kind)
        if gate:
            print(f"  GATE {kind}: {'PASS' if gate['passes'] else 'FAIL'}  {gate['checks']}")
        nv = report["naive_comparison"].get(kind)
        if nv:
            print(f"  naive comparison (reported): ai-naive={_fmt(nv['ai_minus_naive'])}")
    ir = report["inter_rater"]
    if "note" in ir:
        print(f"\ninter-rater: {ir['note']}")
    else:
        print(f"\ninter-rater kappa: useful={ir['kappa_useful']:.3f} "
              f"fact_precision={ir['kappa_fact_precision']:.3f}")
    print("\nseen vs held:")
    print("  " + report["safeguards"]["seen_vs_held"]["statement"])
    rj = report["safeguards"]["reject_memorized"]
    print(f"  reject-memorized: {rj['kept']}/{rj['total']} kept, {len(rj['dropped'])} dropped")
    print(f"\nreport: {out_path}")
    print(f"manifest: {os.path.join(os.path.dirname(out_path), 'run_manifest.json')}")


if __name__ == "__main__":
    main()
