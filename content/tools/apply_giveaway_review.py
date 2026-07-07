"""Fix technique-giveaway problems by rewording the stem, with safety checks.

Two ways to pick what to fix:
  --auto {high,all}  : select flagged problems straight from the verdicts JSON.
  --reviewed <file>  : honor a filled 03-giveaway-reviewed.md (FIX/KEEP/DROP).

For each FIX the model rewords the stem to remove the handed-over relation while
keeping every given number, the setup, and the correct answer identical. Each
reworded stem then passes TWO gates before it is applied:

  1. re-judge (check_technique_giveaway): it must no longer give away the method;
  2. independent re-solve (generation_core.solve_problem): a blind solve of the
     reworded problem must still land on the original key, so the answer did not
     drift.

A reword that fails either gate is NOT applied; the original stem is kept and the
id is logged as unresolved, so nothing silently regresses. Writes the bundle in
place and a change log with before/after for the spot check.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

import check_technique_giveaway as tg  # noqa: E402

from pgrep.ai import generation_core as gc  # noqa: E402
from pgrep.ai import llm as llm_mod  # noqa: E402

FIG = re.compile(r'(<div class="pg-figure">[\s\S]*?</div>)')
LETTERS = "ABCDE"

REWORD_SYSTEM = (
    "You revise a Physics GRE problem stem to remove a spoiler: the stem currently "
    "hands the solver the governing relation or formula the problem is meant to "
    "test. Reword so the solver must recall or derive that relation themselves.\n"
    "STRICT rules:\n"
    "- Keep every given numeric value and unit, the physical setup, and the correct "
    "answer EXACTLY the same. Only remove the handed-over relation or technique.\n"
    "- If a quantity was expressed through the spoiler relation (for example "
    "'frequency f = c/(0.60 m)'), replace it with the equivalent plain given (for "
    "example a numeric frequency) so the problem stays solvable and the answer is "
    "unchanged.\n"
    "- Add no hints, reference no figure, use no em-dashes, keep the voice tight, "
    "and keep any LaTeX delimiters.\n"
    'Return STRICT JSON: {"stem": "<reworded stem, no figure markup>"}.'
)


def reword(client, model: str, what: str, fix: str, stem_text: str) -> str:
    user = f"WHAT IS HANDED OVER: {what}\nSUGGESTED FIX: {fix}\n\nSTEM:\n{stem_text}"
    for extra in (dict(response_format={"type": "json_object"}), dict()):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": REWORD_SYSTEM},
                          {"role": "user", "content": user}],
                **extra,
            )
            raw = (r.choices[0].message.content or "{}").strip()
            m = re.search(r"\{[\s\S]*\}", raw)
            return json.loads(m.group(0)).get("stem", stem_text) if m else stem_text
        except Exception:  # noqa: BLE001
            continue
    return stem_text


def parse_reviewed(md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for b in re.split(r"\n### ", "\n" + md):
        m = re.match(r"(p4-prob-\d+)", b)
        if not m:
            continue
        cm = re.search(r"-> your call:\s*(.+)", b)
        out[m.group(1)] = cm.group(1).strip() if cm else "KEEP"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--auto", choices=["high", "all"], default=None)
    ap.add_argument("--reviewed", default=None)
    ap.add_argument("--verdicts", default="content/run/triple/technique_giveaway.json")
    ap.add_argument("--bundle", default="pylib/anki/pgrep/content_bundle.json")
    ap.add_argument("--model", default="gpt-5.5-2026-04-23")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--log", default="content/run/triple/giveaway_applied.json")
    args = ap.parse_args()
    if not args.auto and not args.reviewed:
        ap.error("pass --auto {high,all} or --reviewed <file>")

    data = json.load(open(args.verdicts, encoding="utf-8"))
    vmap = {v["id"]: v for v in data["verdicts"]}

    if args.auto:
        calls = {v["id"]: "FIX" for v in data["verdicts"]
                 if v.get("gives_away") and (args.auto == "all" or v.get("severity") == "high")}
    else:
        calls = parse_reviewed(open(args.reviewed, encoding="utf-8").read())

    bundle = json.load(open(args.bundle, encoding="utf-8"))
    by_id = {p["id"]: p for p in bundle["problems"]}

    key = tg.load_key()
    os.environ.setdefault("OPENAI_API_KEY", key)  # LLMClient reads it from env
    from openai import OpenAI
    client = OpenAI(api_key=key, max_retries=5)
    judge = tg.Judge(args.model, key)
    solver = llm_mod.LLMClient(args.model)

    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock = threading.Lock()
    fixed: list[dict] = []
    unresolved: list[dict] = []
    dropped: list[str] = []
    kept = {"n": 0}
    done = {"n": 0}

    fix_ids = [pid for pid, c in calls.items()
               if c.upper().startswith("FIX") and pid in by_id and pid in vmap]
    for pid, c in calls.items():
        u = c.upper()
        if u.startswith("KEEP"):
            kept["n"] += 1
        elif u.startswith("DROP") and pid in by_id:
            dropped.append(pid)

    def work(pid: str) -> None:
        p = by_id[pid]
        v = vmap[pid]
        note = re.sub(r"(?i)^fix:?\s*", "", calls[pid]).strip()
        fix = (v.get("fix", "") + (" " + note if note else "")).strip()
        orig = p.get("stem", "")
        fm = FIG.search(orig)
        fig = fm.group(1) if fm else ""
        body = FIG.sub("", orig).strip()
        new_body = reword(client, args.model, v.get("what", ""), fix, body)
        recheck = judge.judge({**p, "stem": new_body})
        solved = gc.solve_problem(new_body, p.get("choices", []), solver)
        ok = (not recheck.get("gives_away")) and solved == str(p.get("correct", "")).strip().upper()
        with lock:
            done["n"] += 1
            if ok:
                p["stem"] = (new_body + ("\n" + fig if fig else "")).strip()
                fixed.append({"id": pid, "before": body, "after": new_body})
            else:
                unresolved.append({"id": pid,
                                   "still_gives_away": bool(recheck.get("gives_away")),
                                   "solve": solved, "key": p.get("correct")})
            if done["n"] % 20 == 0 or done["n"] == len(fix_ids):
                print(f"  processed {done['n']}/{len(fix_ids)} "
                      f"(fixed {len(fixed)}, unresolved {len(unresolved)})", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, fix_ids))

    if dropped:
        bundle["problems"] = [p for p in bundle["problems"] if p["id"] not in set(dropped)]
        n = len(bundle["problems"])
        bundle["counts"] = {"cards": len(bundle.get("cards", [])), "problems": n,
                            "total": len(bundle.get("cards", [])) + n}

    with open(args.bundle, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.makedirs(os.path.dirname(args.log), exist_ok=True)
    json.dump({"fixed": [f["id"] for f in fixed], "kept": kept["n"],
               "dropped": dropped, "unresolved": unresolved, "diffs": fixed},
              open(args.log, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\nfixed {len(fixed)}, kept {kept['n']}, dropped {len(dropped)}, "
          f"unresolved (kept original) {len(unresolved)}")
    print(f"log: {args.log}")


if __name__ == "__main__":
    main()
