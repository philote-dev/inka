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

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import judge as ai_judge  # type: ignore[import-not-found]  # noqa: E402
from pgrep.ai import llm  # type: ignore[import-not-found]  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BUNDLE = os.path.join(REPO, "pylib", "anki", "pgrep", "content_bundle.json")
FIG = re.compile(r'<div class="pg-figure">[\s\S]*?</div>')
_lock = threading.Lock()


def _stem(p: dict) -> str:
    return FIG.sub(" ", p.get("stem", "")).strip()


class Judge:
    """Thin compatibility shim over ``ai.judge.Judge``.

    Kept so ``apply_giveaway_review`` / ``fix_decomp_giveaways`` and this CLI are
    unchanged; the giveaway check itself lives in ``pgrep.ai.judge`` now. ``key``
    is accepted positionally for the legacy callers; the key lives in the
    environment (``llm.load_api_key``). Pass ``client`` to inject a fake in tests
    (no network).
    """

    def __init__(self, model: str, key: str | None = None, *, client=None) -> None:
        client = client if client is not None else llm.judge_client(model)
        self._judge = ai_judge.Judge(model, client=client)
        self.client = self._judge.client
        self.model = self._judge.model

    def judge(self, p: dict) -> dict:
        return self._judge.technique_giveaway(p).to_dict()


def load_key(env_file: str | None = None) -> str:
    """Load the API key into the environment and return it.

    Kept for callers that pass a key positionally to ``Judge``. The loading now
    lives in ``llm.load_api_key`` (the one shared implementation); this returns
    the value for callers that build their own client from it.
    """
    llm.load_api_key(env_file)
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("No OPENAI_API_KEY found")
    return key


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

    llm.load_api_key()
    judge = Judge(args.model)
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
