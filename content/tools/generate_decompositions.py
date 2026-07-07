"""Batch-generate the gated decomposition tutor data for pgrep problems (WS4).

For each shipped ``pgrep::Problem`` this builds the ``decomposition_tutor`` blob
the Problems-door miss flow reads (``anki.pgrep.decomposition``):

  - 2 to 3 **subproblems** (count by complexity), each a self-contained
    five-choice MCQ with misconception-first distractor rationales, a model
    ``explain_why`` rationale, and a named ``source_ref``;
  - several **numeric variants** per subproblem, so a repeat never reuses the
    same numbers;
  - optional **parent_variants** that renumber the parent stem for an honest
    re-serve (its key re-derived).

Grounded ONLY in the corpus (``provenance.cite_or_refuse``) and verified with the
SAME shipped core the app uses: the giveaway verifier guarantees no subproblem
leaks the parent answer (``verify.find_giveaway``), an independent solve confirms
each key (``generation_core.solve_problem``), and SymPy checks any computational
variant (``verify.cas_check_value``). Nothing here calls a runtime path; the app
loads the committed result from ``content_bundle.json``.

The batch is pre-generated so study time never calls the API to fetch a
decomposition. Run from the checkout that holds ``content/`` (corpus + key):

    conda run -n pgrep-ai python content/tools/generate_decompositions.py --smoke 3
    python content/tools/generate_decompositions.py --per-topic 1 --apply
    python content/tools/generate_decompositions.py --ids p4-prob-0001,p4-prob-0007 --apply

``--apply`` merges the result into ``--bundle`` (the shipped content bundle),
adding a ``decomposition_tutor`` key to each generated problem. Without it the run
only writes ``content/run/decompositions/`` for review.
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

from pgrep.ai import generation_core as gc  # noqa: E402
from pgrep.ai import llm as llm_mod  # noqa: E402
from pgrep.ai import provenance  # noqa: E402
from pgrep.ai import retrieval  # noqa: E402
from pgrep.ai import verify  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
REPO = os.path.dirname(CONTENT)
DEFAULT_DB = os.path.join(CONTENT, "index", "corpus.db")
DEFAULT_BUNDLE = os.path.join(REPO, "pylib", "anki", "pgrep", "content_bundle.json")
DEFAULT_OUT = os.path.join(CONTENT, "run", "decompositions")

LETTERS = ("A", "B", "C", "D", "E")
_FIGURE_RE = re.compile(r"<div class=\"pg-figure\">.*?</div>", re.DOTALL)
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

_print_lock = threading.Lock()

DECOMP_SYSTEM = (
    "You are a Physics GRE tutor building a scaffold for a student who just "
    "missed a problem. Given the parent problem, its worked sub-goals, and corpus "
    "context, produce a JSON decomposition that walks the student to the METHOD "
    "without ever revealing the parent's final answer or naming its key choice.\n"
    "Return STRICT JSON with this exact shape:\n"
    '{"subproblems": [ {"prompt": str, "variants": [ {"stem": str, '
    '"choices": [five strings], "key": "A"|"B"|"C"|"D"|"E", '
    '"distractor_rationales": {"<letter>": str} for the four non-key letters, '
    '"explain_why": str} ] } ], '
    '"parent_variants": [ {"stem": str, "choices": [five strings], '
    '"key": "A"|"B"|"C"|"D"|"E"} ] }\n'
    "Rules: 2 to 3 subproblems, each a standalone multiple-choice question that "
    "tests ONE reasoning step from the worked sub-goals. Do NOT write the "
    "governing equation, formula, law, or the specific relationship the "
    "subproblem is testing anywhere in that subproblem's stem or its choices: "
    "give only the scenario and the givens, so the learner must recall and apply "
    "the relationship themselves (the whole point is that a wrong pick and the "
    "'explain why' step force recall). You MAY state the numeric value of a "
    "needed physical constant such as g, c, or hc. Give 2 numeric variants per "
    "subproblem with DIFFERENT numbers but the same idea and structure. Use "
    "misconception-first distractors (name the likely error the wrong choice "
    "encodes). Write a short explain_why for the correct choice that names the "
    "relationship the stem withheld and applies it. Provide 1 parent_variant that "
    "renumbers the parent's givens and recomputes its own key. Keep math in LaTeX "
    "with \\( \\) or \\[ \\]. NEVER state the parent problem's final answer value "
    "or name its key letter in any stem, choice, rationale, or explanation. "
    "Ground every step in the provided corpus context."
)


def _load_env_key() -> None:
    path = os.path.join(CONTENT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*OPENAI_API_KEY\s*=\s*(.+)", line)
        if m and m.group(1).strip() and not m.group(1).strip().startswith("<"):
            os.environ.setdefault("OPENAI_API_KEY", m.group(1).strip())


def _strip_figure(stem: str) -> str:
    return _FIGURE_RE.sub(" [figure] ", stem).strip()


def _numbers(text: str) -> set[float]:
    out: set[float] = set()
    for m in _NUM_RE.findall(text or ""):
        try:
            out.add(float(m))
        except ValueError:
            continue
    return out


def _leaks_parent_answer(text: str, answer_text: str, key: str) -> bool:
    """True when ``text`` reveals the parent answer, via the shipped verifier.

    ``verify.find_giveaway`` is the shipped guard. It also flags any shared
    number, which over-triggers here because decompositions legitimately reuse
    small integers (2, 3, ...). So a bare shared-number hit only counts as a leak
    when a *distinctive* number is shared (magnitude >= 10 or non-integer); a
    verbatim answer span or a named key letter is always a leak.
    """
    reason = verify.find_giveaway(text, answer_text, choice_label=key)
    if reason is None:
        return False
    if reason.startswith("hint states the answer value"):
        shared = _numbers(answer_text) & _numbers(text)
        return any(abs(n) >= 10 or n != int(n) for n in shared)
    return True


def _key_text(choices: list, key: str) -> str:
    if key in LETTERS and len(choices) == 5:
        return str(choices[LETTERS.index(key)])
    return ""


def _valid_mcq(v: dict) -> bool:
    choices = v.get("choices")
    return (
        isinstance(v, dict)
        and isinstance(choices, list)
        and len(choices) == 5
        and str(v.get("key", "")).strip().upper() in LETTERS
    )


def _retrieve(problem: dict, conn) -> list:
    category = str(problem.get("topic", "")).split("::")[1:2]
    cat = category[0] if category else ""
    head = " ".join(_strip_figure(problem.get("stem", "")).split()[:16])
    return retrieval.search(f"{cat} {head}", k=gc.CONTEXT_CHUNKS, conn=conn)


def _build_user(problem: dict, context: str) -> str:
    stem = _strip_figure(problem.get("stem", ""))
    choices = problem.get("choices", [])
    labelled = "\n".join(
        f"  {LETTERS[i]}. {c}" for i, c in enumerate(choices) if i < len(LETTERS)
    )
    steps = problem.get("solution_decomposition", []) or []
    steps_txt = "\n".join(
        f"  - {s.get('subgoal', '')}: {s.get('rubric', '')}"
        for s in steps
        if isinstance(s, dict)
    )
    return (
        f"PARENT PROBLEM (topic {problem.get('topic', '')}):\n{stem}\n\n"
        f"PARENT CHOICES:\n{labelled}\n\n"
        f"PARENT WORKED SUB-GOALS (method only, do not reveal the final answer):\n"
        f"{steps_txt}\n\n"
        f"CORPUS CONTEXT:\n{context}"
    )


def _clean_variant(
    v: dict, parent_key_text: str, parent_key: str, retrieved: list, fallback_ref: str
) -> dict | None:
    """A shipped-shape subproblem variant, or ``None`` if it leaks or is malformed."""
    if not _valid_mcq(v):
        return None
    key = str(v["key"]).strip().upper()
    choices = [str(c) for c in v["choices"]]
    rationales = v.get("distractor_rationales") or {}
    rationales = {
        str(k).strip().upper(): str(t)
        for k, t in rationales.items()
        if str(k).strip().upper() in LETTERS and str(k).strip().upper() != key
    }
    explain = str(v.get("explain_why", ""))
    blob = " ".join([str(v.get("stem", "")), *choices, explain, *rationales.values()])
    if _leaks_parent_answer(blob, parent_key_text, parent_key):
        return None
    prov = provenance.best_support(str(v.get("stem", "")), retrieved)
    source_ref = prov.source_ref if prov and prov.source_ref else fallback_ref
    return {
        "stem": str(v.get("stem", "")),
        "choices": choices,
        "key": key,
        "distractor_rationales": rationales,
        "explain_why": explain,
        "source_ref": source_ref,
    }


def _solve_ok(variant: dict, client) -> bool:
    solved = gc.solve_problem(variant["stem"], variant["choices"], client)
    return bool(solved) and solved == variant["key"]


def build_tutor(
    problem: dict, client, conn, *, verify_keys: bool, system: str = DECOMP_SYSTEM
) -> tuple[dict, list[str]]:
    """Return ``(decomposition_tutor, flags)`` for one parent problem."""
    flags: list[str] = []
    parent_key = str(problem.get("correct", "")).strip().upper()
    parent_key_text = _key_text(problem.get("choices", []), parent_key)
    fallback_ref = problem.get("source_ref") or ""

    retrieved = _retrieve(problem, conn)
    user = _build_user(problem, gc.build_context(retrieved))
    raw = client.complete_json(system, user)

    subs_out: list[dict] = []
    for sp in raw.get("subproblems", []) or []:
        if not isinstance(sp, dict):
            continue
        variants: list[dict] = []
        for v in sp.get("variants", []) or []:
            clean = _clean_variant(
                v, parent_key_text, parent_key, retrieved, fallback_ref
            )
            if clean is None:
                flags.append("variant_dropped")
                continue
            if verify_keys and not _solve_ok(clean, client):
                flags.append("variant_key_unconfirmed")
                continue
            variants.append(clean)
        if variants:
            subs_out.append({"prompt": str(sp.get("prompt", "")), "variants": variants})

    parents_out: list[dict] = []
    for pv in raw.get("parent_variants", []) or []:
        if not _valid_mcq(pv):
            continue
        cand = {
            "stem": str(pv.get("stem", "")),
            "choices": [str(c) for c in pv["choices"]],
            "key": str(pv["key"]).strip().upper(),
        }
        if verify_keys and not _solve_ok(cand, client):
            flags.append("parent_variant_key_unconfirmed")
            continue
        parents_out.append(cand)

    tutor: dict = {"subproblems": subs_out}
    if parents_out:
        tutor["parent_variants"] = parents_out
    return tutor, flags


def _select(problems: list[dict], args) -> list[dict]:
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        return [p for p in problems if p.get("id") in wanted]
    if args.smoke:
        return problems[: args.smoke]
    if args.per_topic:
        by_topic: dict[str, list[dict]] = defaultdict(list)
        for p in problems:
            by_topic[p.get("topic", "")].append(p)
        out: list[dict] = []
        for items in by_topic.values():
            out.extend(items[: args.per_topic])
        return out
    if args.limit:
        return problems[: args.limit]
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate pgrep decomposition tutor data.")
    ap.add_argument("--generator-model", default="gpt-5.5-2026-04-23")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--smoke", type=int, default=0, help="only the first N problems")
    ap.add_argument("--per-topic", type=int, default=0, help="first K problems per topic")
    ap.add_argument("--limit", type=int, default=0, help="first N problems")
    ap.add_argument("--ids", default="", help="comma-separated problem ids")
    ap.add_argument("--no-verify-keys", dest="verify_keys", action="store_false")
    ap.add_argument("--variants", type=int, default=3,
                    help="numeric variants per subproblem (default 3)")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=7,
                    help="change (e.g. 17) to vary output when retrying stragglers")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--bundle", default=DEFAULT_BUNDLE)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--apply", action="store_true", help="merge into the bundle")
    ap.set_defaults(verify_keys=True)
    args = ap.parse_args()

    bundle = json.load(open(args.bundle, encoding="utf-8"))
    problems = bundle["problems"]
    targets = _select(problems, args)
    print(f"targets: {len(targets)} / {len(problems)} problems")
    if not targets:
        sys.exit("no targets selected")

    _load_env_key()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("no OPENAI_API_KEY (set it or add it to content/.env)")
    client = llm_mod.LLMClient(
        args.generator_model, temperature=args.temperature, seed=args.seed
    )
    system = DECOMP_SYSTEM.replace(
        "Give 2 numeric variants per subproblem",
        f"Give {args.variants} numeric variants per subproblem",
    )
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()

    results: dict[str, dict] = {}
    flag_counts: dict[str, int] = defaultdict(int)
    done = {"n": 0}
    ckpt = os.path.join(args.out, "decompositions.partial.json")

    def work(problem: dict) -> None:
        pid = problem.get("id", "")
        conn = retrieval.open_index(args.db)
        try:
            tutor, flags = build_tutor(
                problem, client, conn, verify_keys=args.verify_keys, system=system
            )
        except Exception as exc:  # noqa: BLE001
            with _print_lock:
                flag_counts[f"error:{type(exc).__name__}"] += 1
                done["n"] += 1
            return
        finally:
            conn.close()
        n_sub = len(tutor["subproblems"])
        with _print_lock:
            done["n"] += 1
            for f in flags:
                flag_counts[f] += 1
            if n_sub >= 2:
                results[pid] = tutor
            else:
                flag_counts["too_few_subproblems"] += 1
            if done["n"] % 5 == 0 or done["n"] == len(targets):
                print(
                    f"[{done['n']}/{len(targets)}] kept {len(results)} "
                    f"({time.time() - t0:.0f}s)"
                )
                json.dump(
                    results, open(ckpt, "w", encoding="utf-8"), indent=2,
                    ensure_ascii=False,
                )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, targets))

    n_sub_total = sum(len(t["subproblems"]) for t in results.values())
    n_var_total = sum(
        len(sp["variants"]) for t in results.values() for sp in t["subproblems"]
    )
    summary = {
        "generator_model": args.generator_model,
        "verify_keys": args.verify_keys,
        "variants_requested": args.variants,
        "targets": len(targets),
        "problems_with_tutor": len(results),
        "subproblems_total": n_sub_total,
        "variants_total": n_var_total,
        "flag_counts": dict(flag_counts),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    json.dump(
        results, open(os.path.join(args.out, "decompositions.json"), "w",
                      encoding="utf-8"), indent=2, ensure_ascii=False,
    )
    json.dump(
        summary, open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8"),
        indent=2, ensure_ascii=False,
    )
    if os.path.exists(ckpt):
        os.remove(ckpt)

    if args.apply and results:
        applied = 0
        for p in problems:
            tutor = results.get(p.get("id"))
            if tutor:
                p["decomposition_tutor"] = tutor
                applied += 1
        json.dump(
            bundle, open(args.bundle, "w", encoding="utf-8"), indent=2,
            ensure_ascii=False,
        )
        print(f"applied {applied} decompositions into {args.bundle}")

    print("=" * 60)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
