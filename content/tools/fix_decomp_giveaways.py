"""Find and fix technique-giveaways INSIDE decomposition subproblems.

The parent-problem pass never looked inside decompositions, but a subproblem stem
like "Using c = f lambda, what is the wavelength?" hands over that step's method.
This judges each subproblem (regex-prefiltered to save API calls) and, for a
high-severity giveaway, rewords every variant stem. A reworded variant is applied
only when it clears THREE gates:

  1. re-judge: it no longer gives away the relation;
  2. independent solve: a blind solve still lands on that variant's own key;
  3. parent guard: it still does not leak the PARENT problem's answer
     (verify.find_giveaway, with the same distinctive-number relaxation the
     generator uses).

Anything that fails a gate keeps its original stem. Writes the bundle in place
plus a change log. Run from the repo root (needs content/.env and the AI core).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

import check_technique_giveaway as tg  # noqa: E402

from pgrep.ai import generation_core as gc  # noqa: E402
from pgrep.ai import llm as llm_mod  # noqa: E402
from pgrep.ai import verify  # noqa: E402

LETTERS = "ABCDE"
NUM = re.compile(r"-?\d+(?:\.\d+)?")
GIVE = re.compile(
    r"(?i)\b(using|use|apply(?:ing)?|recall that|by the|from the|with the)\b"
    r"[^.]{0,55}"
    r"(relation|formula|equation|law|identity|theorem|principle|"
    r"[A-Za-z_](?:_\{?[A-Za-z0-9]+\}?)?\s*=)"
)

REWORD_SYSTEM = (
    "You revise ONE step of a Physics GRE tutoring decomposition. The step's "
    "multiple-choice stem currently hands the solver the relation or formula the "
    "step is meant to test. Reword so the solver must recall or apply the relation "
    "themselves.\n"
    "STRICT rules:\n"
    "- Keep every given number and unit, the setup, and the correct choice EXACTLY "
    "the same. Only remove the stated relation/technique.\n"
    "- If a quantity was expressed through the relation (for example 'f = c/(0.60 "
    "m)'), give the plain equivalent value instead so the step still solves to the "
    "same answer.\n"
    "- Do not add hints, do not reveal the parent problem's final answer, no "
    "em-dashes, keep LaTeX delimiters.\n"
    'Return STRICT JSON: {"stem": "<reworded stem>"}.'
)


def _nums(t: str) -> set[float]:
    out: set[float] = set()
    for m in NUM.findall(t or ""):
        try:
            out.add(float(m))
        except ValueError:
            pass
    return out


def leaks_parent(text: str, ans_text: str, key: str) -> bool:
    reason = verify.find_giveaway(text, ans_text, choice_label=key)
    if reason is None:
        return False
    if reason.startswith("hint states the answer value"):
        shared = _nums(ans_text) & _nums(text)
        return any(abs(n) >= 10 or n != int(n) for n in shared)
    return True


def key_text(choices: list, key: str) -> str:
    return str(choices[LETTERS.index(key)]) if key in LETTERS and len(choices) == 5 else ""


def reword(client, model: str, what: str, stem_text: str) -> str:
    user = f"WHAT IS HANDED OVER: {what}\n\nSTEM:\n{stem_text}"
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default="pylib/anki/pgrep/content_bundle.json")
    ap.add_argument("--model", default="gpt-5.5-2026-04-23")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--log", default="content/run/triple/decomp_giveaway_applied.json")
    args = ap.parse_args()

    bundle = json.load(open(args.bundle, encoding="utf-8"))
    key = tg.load_key()
    os.environ.setdefault("OPENAI_API_KEY", key)
    from openai import OpenAI
    client = OpenAI(api_key=key, max_retries=5)
    judge = tg.Judge(args.model, key)
    solver = llm_mod.LLMClient(args.model)

    # Collect candidate subproblems: any whose variant stem trips the heuristic.
    cands: list[tuple] = []
    for p in bundle["problems"]:
        t = p.get("decomposition_tutor") or {}
        p_ans = key_text(p.get("choices", []), str(p.get("correct", "")).strip().upper())
        p_key = str(p.get("correct", "")).strip().upper()
        for si, sp in enumerate(t.get("subproblems", [])):
            variants = sp.get("variants", [])
            if any(GIVE.search(v.get("stem", "")) for v in variants):
                cands.append((p, p_ans, p_key, sp, variants))

    lock = threading.Lock()
    fixed_vars = {"n": 0}
    fixed_subs = {"n": 0}
    unresolved: list[str] = []
    skipped_lowsev = {"n": 0}
    done = {"n": 0}

    def work(item: tuple) -> None:
        p, p_ans, p_key, sp, variants = item
        v0 = variants[0]
        verdict = judge.judge({"topic": p.get("topic", ""), "stem": v0.get("stem", ""),
                               "choices": v0.get("choices", []), "correct": v0.get("key", "")})
        with lock:
            done["n"] += 1
            if done["n"] % 25 == 0 or done["n"] == len(cands):
                print(f"  judged {done['n']}/{len(cands)} (fixed subs {fixed_subs['n']}, "
                      f"vars {fixed_vars['n']})", flush=True)
        if not verdict.get("gives_away") or verdict.get("severity") != "high":
            if verdict.get("gives_away"):
                with lock:
                    skipped_lowsev["n"] += 1
            return
        what = verdict.get("what", "")
        any_fixed = False
        for v in variants:
            stem = v.get("stem", "")
            if not GIVE.search(stem):
                continue
            new = reword(client, args.model, what, stem)
            if new == stem:
                continue
            # gate 1: no longer gives away
            rj = judge.judge({"topic": p.get("topic", ""), "stem": new,
                              "choices": v.get("choices", []), "correct": v.get("key", "")})
            if rj.get("gives_away"):
                continue
            # gate 2: still solves to the variant's own key
            if gc.solve_problem(new, v.get("choices", []), solver) != str(v.get("key", "")).strip().upper():
                continue
            # gate 3: does not leak the parent answer
            if leaks_parent(new, p_ans, p_key):
                continue
            v["stem"] = new
            any_fixed = True
            with lock:
                fixed_vars["n"] += 1
        with lock:
            if any_fixed:
                fixed_subs["n"] += 1
            else:
                unresolved.append(f"{p['id']}#sub{sp.get('prompt','')[:20]}")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, cands))

    with open(args.bundle, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.makedirs(os.path.dirname(args.log), exist_ok=True)
    json.dump({"candidates": len(cands), "fixed_subproblems": fixed_subs["n"],
               "fixed_variants": fixed_vars["n"], "skipped_low_severity": skipped_lowsev["n"],
               "unresolved": unresolved},
              open(args.log, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\ncandidates {len(cands)}; fixed {fixed_subs['n']} subproblems "
          f"({fixed_vars['n']} variant stems); low-severity left {skipped_lowsev['n']}; "
          f"high but unresolved {len(unresolved)}")


if __name__ == "__main__":
    main()
