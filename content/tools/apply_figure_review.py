"""Apply figure review verdicts.

  - KEEP: ship the drawn SVG as-is (auto-stripping any stray hardcoded color so the
    strict audit passes).
  - REDRAW: redraw guided by the reviewer's note (fed to the generator), then run
    the fidelity loop; ship the best result and record any that still miss.
  - TEXT-ONLY: rewrite the stem to be fully self-contained (no figure reference),
    so the problem ships without a figure and nothing dangles.

Writes approved_final.json (the existing approved set plus KEEP + REDRAW results,
ready for pgrep_wire_figures) and textonly_edits.json (id -> new stem). Reuses the
figure generator, the fidelity judge, and the audit's convention checks.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pgrep_content_audit as audit  # noqa: E402
import pgrep_figure_gen as figgen  # noqa: E402
import pgrep_figure_verify as figverify  # noqa: E402
import review_sheet  # noqa: E402

HEX = re.compile(r"#[0-9a-fA-F]{3,6}")
FIG_REF = re.compile(r"(?i)\b(as shown|shown (?:above|below)|in the figure|the figure|the diagram|figure (?:above|below))\b")

TEXTONLY_SYSTEM = (
    "Rewrite this Physics GRE problem stem so it is fully self-contained in words "
    "and LaTeX, with NO reference to any figure or diagram. Remove phrases like "
    "'in the figure shown' and any clause that only describes what a diagram "
    "shows; instead state the setup directly in words. Keep ALL physics, every "
    "given number, and the final question identical in meaning. Return STRICT "
    'JSON: {"stem": "<rewritten stem>"}.'
)


def conv_issues(svg: str) -> list[str]:
    if not svg.strip().startswith("<svg"):
        return ["no svg"]
    return audit.figure_violations(f'<div class="pg-figure">{svg}</div>')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reviewed", default="content/run/review/02-figures-reviewed.md")
    ap.add_argument("--review", default="content/run/triple/figures/review_all.json")
    ap.add_argument("--approved-in", default="content/run/triple/figures/approved_all.json")
    ap.add_argument("--out", default="content/run/triple/figures")
    ap.add_argument("--attempts", type=int, default=3)
    args = ap.parse_args()

    verd = review_sheet.parse(open(args.reviewed, encoding="utf-8").read(),
                              review_sheet.PROBLEM_ID_RE)
    review = {r["id"]: r for r in json.load(open(args.review, encoding="utf-8"))}
    approved = json.load(open(args.approved_in, encoding="utf-8"))  # the 67 already OK
    key = figgen.load_key(None)
    gen = figgen.Gen("gpt-5.5", key)
    judge = figverify.Judge("gpt-5.4-2026-03-05", key)

    from openai import OpenAI
    client = OpenAI(api_key=key, max_retries=5)

    textonly: list[str] = []
    edits: dict[str, str] = {}
    still_off: list[str] = []
    n_keep = n_redraw = 0

    for pid, v in verd.items():
        r = review.get(pid)
        if not r:
            continue
        u = v.upper()
        stem = r.get("stem", "")
        if u.startswith("KEEP"):
            svg = r["svg"]
            if conv_issues(svg):
                svg = HEX.sub("currentColor", svg)
            approved.append({"id": pid, "svg": svg})
            n_keep += 1
            continue
        if u.startswith("TEXT-ONLY"):
            textonly.append(pid)
            continue
        if u.startswith("DROP"):
            continue
        # REDRAW guided by the reviewer's note.
        note = re.sub(r"(?i)^redraw:?\s*", "", v).strip() or "Fix the figure to match the stem."
        hint = figgen.category_hint(r.get("topic", ""), stem)
        svg = gen.refine(gen.svg_for_feedback(stem, hint, r["svg"], note))
        for _ in range(max(0, args.attempts - 1)):
            if conv_issues(svg):
                svg = HEX.sub("currentColor", svg)
            vr = judge.verify(stem, svg) if svg.strip().startswith("<svg") else {"matches": False}
            if svg.strip().startswith("<svg") and not conv_issues(svg) and vr.get("matches"):
                break
            comp = note + "\n" + "; ".join((vr.get("missing") or []) + (vr.get("contradictions") or []))
            svg = gen.refine(gen.svg_for_feedback(stem, hint, svg, comp))
        if conv_issues(svg):
            svg = HEX.sub("currentColor", svg)
        final_vr = judge.verify(stem, svg) if svg.strip().startswith("<svg") else {"matches": False}
        if not final_vr.get("matches"):
            still_off.append(pid)
        approved.append({"id": pid, "svg": svg})
        n_redraw += 1
        print(f"  {pid} redrawn (matches={final_vr.get('matches')})", flush=True)

    # TEXT-ONLY stem rewrites.
    if textonly:
        acc = {}
        for f in ("accepted_problems.json", "accepted_from_review.json"):
            for p in json.load(open(f"content/run/triple/pool/merged/{f}", encoding="utf-8")):
                acc[p["id"]] = p
        for pid in textonly:
            stem = acc.get(pid, review[pid]).get("stem", "")
            resp = client.chat.completions.create(
                model="gpt-5.5",
                messages=[{"role": "system", "content": TEXTONLY_SYSTEM},
                          {"role": "user", "content": stem}],
                response_format={"type": "json_object"},
            )
            new = json.loads(resp.choices[0].message.content).get("stem", stem)
            edits[pid] = new
            flag = " STILL-REFERENCES-FIGURE" if FIG_REF.search(new) else ""
            print(f"  {pid} text-only rewrite{flag}", flush=True)

    json.dump(approved, open(os.path.join(args.out, "approved_final.json"), "w",
                             encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump({"textonly": textonly, "edits": edits, "still_off": still_off},
              open(os.path.join(args.out, "textonly_edits.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(f"\napproved_final {len(approved)} figures (kept {n_keep}, redrew {n_redraw}); "
          f"text-only {len(textonly)}; redraws still imperfect: {still_off or 'none'}")


if __name__ == "__main__":
    main()
