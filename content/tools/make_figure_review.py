"""Build the disposable figure review file from the fidelity-judge failures.

The Markdown file stays clean: id, the judge's complaint, a recommendation, and a
machine-parseable `-> your call:` slot, with NO bulky SVG source inline. The
actual figures render in a companion ``02-figures-preview.html`` (light and dark),
labeled by id in the same order, so the doc is easy to fill while the visuals are
one click away.

Recommendation defaults to KEEP (the judge is strict and most misses are cosmetic
label nits on an otherwise-correct figure); a real convention violation defaults
to REDRAW. Tokens the applier understands: KEEP, REDRAW, DROP, TEXT-ONLY.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import review_sheet  # noqa: E402


def recommend(r: dict) -> str:
    conv = [c for c in (r.get("conventions", []) or []) if c != "no svg"]
    return "REDRAW" if conv else "KEEP"


def block(r: dict) -> str:
    v = r.get("verdict", {}) or {}
    pid = r["id"]
    lines = [f"### {pid}", f"recommendation: {recommend(r)}", ""]
    conv = [c for c in (r.get("conventions", []) or []) if c != "no svg"]
    if conv:
        lines.append(f"- convention issue: {', '.join(conv)}")
    for m in v.get("missing", []) or []:
        lines.append(f"- missing: {m}")
    for c in v.get("contradictions", []) or []:
        lines.append(f"- contradiction: {c}")
    if v.get("notes"):
        lines.append(f"- note: {v['notes']}")
    lines += ["", f"**Stem.** {r.get('stem','')}", "",
              f"-> your call: {recommend(r)}", "", "---", ""]
    return "\n".join(lines)


def build_preview(review: list[dict]) -> str:
    def panel(cls: str, bg: str, fg: str) -> str:
        cards = "".join(
            f'<div class="fig"><div class="id">{r["id"]} &mdash; rec {recommend(r)}</div>'
            f'<div class="stem">{(r.get("stem") or "")[:200]}</div>'
            f'<div class="svg">{r.get("svg") or "<em>(no svg)</em>"}</div></div>'
            for r in review
        )
        return f'<section style="background:{bg};color:{fg}"><h2>{cls}</h2>{cards}</section>'

    return (
        "<!doctype html><meta charset=utf-8><title>Figure review</title>"
        "<style>body{font-family:-apple-system,system-ui,sans-serif;margin:0}"
        "section{padding:24px}h2{opacity:.6;text-transform:uppercase;font-size:12px;letter-spacing:.08em}"
        ".fig{border:1px solid currentColor;border-radius:12px;padding:16px;margin:0 0 16px;max-width:520px}"
        ".id{font-size:12px;opacity:.7;margin-bottom:4px}"
        ".stem{font-size:13px;opacity:.85;margin-bottom:12px;line-height:1.4}"
        ".svg svg{max-width:100%;height:auto}</style>"
        + panel("light", "#f4f1ec", "#1c1a17")
        + panel("dark", "#17150f", "#efe9df")
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--review", default="content/run/triple/figures/review_all.json")
    ap.add_argument("--out", default="content/run/review")
    args = ap.parse_args()

    review = json.load(open(args.review, encoding="utf-8"))
    review.sort(key=lambda r: r.get("id", ""))
    recs = review_sheet.manifest(review, recommend=recommend, id_of=lambda r: r["id"])
    from collections import Counter
    c = Counter(recs.values())

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "02-figures-preview.html"), "w", encoding="utf-8") as fh:
        fh.write(build_preview(review))

    head = [
        "# Figure review (disposable)",
        "",
        f"**Open `02-figures-preview.html` in this folder to see the {len(review)} "
        "figures** (light and dark, in the same order as below). This doc stays "
        "text-only so it is easy to fill.",
        "",
        f"Recommendations: KEEP {c.get('KEEP', 0)}, REDRAW {c.get('REDRAW', 0)}.",
        "",
        "Fill each `-> your call:` line. Tokens: `KEEP` (ship as drawn), "
        "`REDRAW: <note>` (redraw, optionally with a hint), `TEXT-ONLY` (drop the "
        "figure; I strip the figure reference from the stem), `DROP` (remove the "
        "problem). Reply 'accept figure recommendations' to take the defaults.",
        "",
        "Note: `p4-prob-0283`, `0285`, `0289` are abstract statistical-mechanics "
        "setups where a faithful figure is impractical; `TEXT-ONLY` is a good call "
        "for those.",
        "",
        "---",
        "",
    ]
    with open(os.path.join(args.out, "02-figures.md"), "w", encoding="utf-8") as fh:
        fh.write(review_sheet.build(review, header=head, recommend=recommend,
                                    block=block, id_of=lambda r: r["id"]))
    json.dump({"review": recs}, open(os.path.join(args.out, "02-figures.manifest.json"),
                                     "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"figure review: {len(review)}  recs={dict(c)}")
    print("wrote 02-figures.md (clean) and 02-figures-preview.html (renders the SVGs)")


if __name__ == "__main__":
    main()
