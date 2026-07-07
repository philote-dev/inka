#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Draw, verify, and auto-redraw pgrep figures until they match the problem.

For each figure-required problem this draws an SVG (``pgrep_figure_gen``), checks
the monochrome / currentColor / no-number conventions (``pgrep_content_audit``),
and asks the independent fidelity judge (``pgrep_figure_verify``) whether the
figure matches the stem. On a miss it feeds the judge's specific complaints back
to the generator and redraws, up to ``--attempts`` times. Figures that pass go to
``approved.json`` (ready for ``pgrep_wire_figures``); figures that still fail go
to ``review.json`` for a human call, alongside a light/dark ``preview.html``.

Never touches the bundle. Run from the worktree root:
    python tools/run_figures.py --problems content/run/triple/pool/merged.json \\
        --out content/run/triple/figures --attempts 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pgrep_content_audit as audit  # type: ignore[import-not-found]  # noqa: E402
import pgrep_figure_gen as figgen  # type: ignore[import-not-found]  # noqa: E402
import pgrep_figure_verify as figverify  # type: ignore[import-not-found]  # noqa: E402


def conventions(svg: str) -> list[str]:
    if not svg.strip().startswith("<svg"):
        return ["no svg"]
    return audit.figure_violations(f'<div class="pg-figure">{svg}</div>')


def complaints_text(verdict: dict, conv: list[str]) -> str:
    parts: list[str] = []
    for m in verdict.get("missing", []) or []:
        parts.append(f"- missing: {m}")
    for c in verdict.get("contradictions", []) or []:
        parts.append(f"- contradiction: {c}")
    if verdict.get("has_numbers"):
        parts.append("- remove ALL numeric or unit labels from the figure")
    if verdict.get("notes"):
        parts.append(f"- reviewer note: {verdict['notes']}")
    if conv and conv != ["no svg"]:
        parts.append("- convention fixes: " + "; ".join(conv))
    return "\n".join(parts) or "The figure did not clearly match the stem."


def load_problems(args) -> list[dict]:
    if args.problems:
        data = json.loads(Path(args.problems).read_text(encoding="utf-8"))
        problems = data if isinstance(data, list) else data.get("problems", [])
    else:
        problems = json.loads(Path(args.bundle).read_text(encoding="utf-8")).get(
            "problems", []
        )
    if args.ids:
        idset = set(args.ids)
        return [p for p in problems if p.get("id") in idset]
    return [p for p in problems if p.get("figure_required")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--problems", help="JSON list/obj with figure_required problems")
    ap.add_argument("--bundle", default=str(figverify.DEFAULT_BUNDLE))
    ap.add_argument("--ids", nargs="*", default=None, help="restrict to these ids")
    ap.add_argument("--gen-model", default="gpt-5.5")
    ap.add_argument("--judge-model", default="gpt-5.4-2026-03-05")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--out", default="content/run/triple/figures")
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()

    problems = load_problems(args)
    if not problems:
        print("no figure-required problems selected")
        return 0

    key = figgen.load_key(args.env_file)
    gen = figgen.Gen(args.gen_model, key)
    judge = figverify.Judge(args.judge_model, key)

    os.makedirs(args.out, exist_ok=True)
    approved: list[dict] = []
    review: list[dict] = []
    preview_rows: list[dict] = []
    print(
        f"figures: {len(problems)} problems, up to {args.attempts} attempts each "
        f"(gen={args.gen_model}, judge={args.judge_model})"
    )

    for p in problems:
        pid = p["id"]
        stem = figverify.strip_figure(p.get("stem", ""))
        hint = figgen.category_hint(
            p.get("topic", ""), stem + " " + " ".join(p.get("choices", []))
        )
        svg = gen.refine(gen.svg_for(stem, hint))
        verdict: dict = {}
        ok = False
        for attempt in range(args.attempts):
            conv = conventions(svg)
            has_svg = svg.strip().startswith("<svg")
            verdict = (
                judge.verify(stem, svg)
                if has_svg
                else {"matches": False, "notes": "no svg drawn"}
            )
            if has_svg and not conv and verdict.get("matches"):
                ok = True
                break
            if attempt < args.attempts - 1:
                svg = gen.refine(
                    gen.svg_for_feedback(
                        stem, hint, svg, complaints_text(verdict, conv)
                    )
                )

        preview_rows.append({"id": pid, "hint": hint, "stem": stem, "svg": svg})
        if ok:
            approved.append({"id": pid, "svg": svg})
            print(f"  {pid}  APPROVED")
        else:
            review.append(
                {
                    "id": pid,
                    "stem": stem,
                    "svg": svg,
                    "verdict": verdict,
                    "conventions": conventions(svg),
                }
            )
            reason = (
                verdict.get("missing")
                or verdict.get("contradictions")
                or verdict.get("notes")
            )
            print(f"  {pid}  REVIEW  {reason}")

    Path(os.path.join(args.out, "approved.json")).write_text(
        json.dumps(approved, indent=2, ensure_ascii=False)
    )
    Path(os.path.join(args.out, "review.json")).write_text(
        json.dumps(review, indent=2, ensure_ascii=False)
    )
    Path(os.path.join(args.out, "preview.html")).write_text(
        figgen.build_html(preview_rows)
    )
    print(f"\napproved {len(approved)}, review {len(review)}. out={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
