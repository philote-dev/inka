#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Flag problems whose stem hands the solver the technique or relation to use.

The shipped giveaway guard checks that a decomposition subproblem does not leak
the PARENT's answer. This is a different check: does a problem's own stem (or its
choices) give away the KEY PHYSICAL RELATION or method whose recall/derivation is
the point of the question, turning a physics problem into arithmetic?

An independent judge model reads each problem and decides. The distinction it is
told to make:

  - NOT a giveaway: stating given numeric values or constants (g = 9.8, c, a mass,
    a dimension), defining notation, or describing the physical setup. These are
    the data a solver is supposed to have.
  - IS a giveaway: stating the governing relation, formula, or solution technique
    that the problem is testing, e.g. "using f = c/lambda, find ...", "recall the
    Rydberg formula 1/lambda = R(...)", "apply E = hf to get ...". The solver
    should have to KNOW or DERIVE that relation, not be handed it.

Writes verdicts JSON and (with the flagged ones) feeds the disposable review file
builder. Read-only over the bundle. Run from the worktree root:

    python content/tools/check_technique_giveaway.py --workers 8
    python content/tools/check_technique_giveaway.py --ids p4-prob-0044 --show
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BUNDLE = os.path.join(REPO, "pylib", "anki", "pgrep", "content_bundle.json")
FIG = re.compile(r'<div class="pg-figure">[\s\S]*?</div>')
_lock = threading.Lock()

JUDGE_SYSTEM = (
    "You audit Physics GRE multiple-choice problems for a subtle flaw: a stem that "
    "HANDS THE SOLVER the governing relation, formula, or solution technique the "
    "problem is meant to test. That trivializes a physics problem into plugging in "
    "numbers.\n\n"
    "Draw this line carefully:\n"
    "- NOT a giveaway (allowed): stating given numeric values or standard constants "
    "(for example g = 9.8 m/s^2, the speed of light c, a mass, a length, a moment "
    "of inertia value), defining notation, or describing the physical setup. A "
    "solver is supposed to be given the data.\n"
    "- IS a giveaway (flag it): stating the KEY physical relation, formula, or "
    "method whose recall or derivation is the actual point, for example 'using "
    "f = c/lambda', 'recall that E = hf', 'apply the Rydberg formula "
    "1/lambda = R(1/n1^2 - 1/n2^2)', 'use the fact that the period is "
    "T = 2*pi*sqrt(L/g)', or a stem that walks through the solution steps.\n\n"
    "Judge whether removing the stated relation would still leave the problem "
    "solvable by someone who knows the physics. If the stem states the very "
    "relation that IS the knowledge being tested, flag it.\n\n"
    "Return STRICT JSON: {\"gives_away\": true|false, \"severity\": "
    "\"high\"|\"low\", \"what\": \"the exact relation/technique handed over, or "
    "empty\", \"fix\": \"how to reword so the relation is not given\"}. Use "
    "severity high when the handed-over relation is essentially the answer method; "
    "low when it is a borderline nudge."
)


def _stem(p: dict) -> str:
    return FIG.sub(" ", p.get("stem", "")).strip()


def _payload(p: dict) -> str:
    choices = "\n".join(f"  {c}" for c in p.get("choices", []))
    return (
        f"TOPIC: {p.get('topic','')}\n\nSTEM:\n{_stem(p)}\n\n"
        f"CHOICES:\n{choices}\n\nCORRECT: {p.get('correct','')}"
    )


class Judge:
    def __init__(self, model: str, key: str) -> None:
        from openai import OpenAI  # type: ignore[import-not-found]

        self.model = model
        self.client = OpenAI(api_key=key, max_retries=5)
        self._reasoning = model.startswith(("gpt-5", "o1", "o3", "o4"))

    def judge(self, p: dict) -> dict:
        temp = {} if self._reasoning else {"temperature": 0}
        for extra in (dict(response_format={"type": "json_object"}, **temp), dict(**temp), dict()):
            try:
                r = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": JUDGE_SYSTEM},
                              {"role": "user", "content": _payload(p)}],
                    **extra,
                )
                raw = (r.choices[0].message.content or "{}").strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    m = re.search(r"\{[\s\S]*\}", raw)
                    return json.loads(m.group(0)) if m else {"gives_away": False}
            except Exception:  # noqa: BLE001
                continue
        return {"gives_away": False, "what": "", "note": "judge call failed"}


def load_key() -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    for path in (os.path.join(REPO, "content", ".env"), os.path.join(REPO, ".env")):
        if os.path.isfile(path):
            for line in open(path):
                if line.strip().startswith("OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("No OPENAI_API_KEY found")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default=DEFAULT_BUNDLE)
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--model", default="gpt-5.5-2026-04-23")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="content/run/triple/technique_giveaway.json")
    ap.add_argument("--show", action="store_true", help="print flagged inline")
    args = ap.parse_args()

    bundle = json.load(open(args.bundle, encoding="utf-8"))
    problems = bundle["problems"]
    if args.ids:
        idset = set(args.ids)
        problems = [p for p in problems if p["id"] in idset]

    judge = Judge(args.model, load_key())
    verdicts: list[dict] = []
    done = {"n": 0}

    def work(p: dict) -> None:
        v = judge.judge(p)
        rec = {"id": p["id"], "topic": p.get("topic", ""), "stem": _stem(p), **v}
        with _lock:
            verdicts.append(rec)
            done["n"] += 1
            if done["n"] % 25 == 0 or done["n"] == len(problems):
                flagged = sum(1 for r in verdicts if r.get("gives_away"))
                print(f"  judged {done['n']}/{len(problems)} (flagged {flagged})", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, problems))

    flagged = [r for r in verdicts if r.get("gives_away")]
    flagged.sort(key=lambda r: (r.get("severity") != "high", r["id"]))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump({"model": args.model, "n": len(problems), "flagged": len(flagged),
               "verdicts": verdicts}, open(args.out, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(f"\njudged {len(problems)}; flagged {len(flagged)} "
          f"(high {sum(1 for r in flagged if r.get('severity')=='high')}). wrote {args.out}")
    if args.show:
        for r in flagged:
            print(f"\n{r['id']} [{r.get('severity')}] {r.get('what','')}")
            print(f"  fix: {r.get('fix','')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
