"""Necessity and reference checks for pgrep figures (stdlib, no API).

Three contracts, checked against a problem list (a grow ``content_set.json`` or
the shipped bundle):

- A problem stamped ``figure_required`` must end up with a valid ``<svg>``.
- A text-only problem (``figure_required`` false) must not reference a figure and
  must carry no ``<svg>``.
- Any problem whose prose references a figure but has no ``<svg>`` is a dangling
  reference, regardless of the flag.

Emit a JSON report; with ``--strict`` exit non-zero when any contract fails. This
is the guard behind "diagrams only where they are needed, and never faked".

Run:
    python content/tools/check_figure_necessity.py --problems content/run/triple/pool/merged.json
    python content/tools/check_figure_necessity.py --bundle pylib/anki/pgrep/content_bundle.json --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Phrases that promise a figure to the reader.
FIG_REF = re.compile(
    r"\b(as shown|shown (?:above|below)|shown in the (?:figure|diagram)|"
    r"in the (?:figure|diagram)|the (?:figure|diagram) (?:above|below|shows)|"
    r"figure (?:above|below)|diagram (?:above|below)|the adjacent (?:figure|diagram))\b",
    re.IGNORECASE,
)
SVG = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)


def strip_svg(stem: str) -> str:
    return SVG.sub(" ", stem or "")


def _snip(text: str, width: int = 60) -> str:
    m = FIG_REF.search(text)
    if not m:
        return text[:width]
    lo = max(0, m.start() - 20)
    return ("..." if lo else "") + text[lo:m.end() + 30].replace("\n", " ")


def check(problems: list[dict]) -> dict:
    dangling: list[dict] = []
    missing_required: list[dict] = []
    textonly_with_fig: list[dict] = []
    with_svg = 0
    for p in problems:
        pid = p.get("id")
        stem = p.get("stem", "") or ""
        has_svg = bool(SVG.search(stem))
        refs = bool(FIG_REF.search(strip_svg(stem)))
        req = p.get("figure_required")
        if refs and not has_svg:
            dangling.append({"id": pid, "snippet": _snip(strip_svg(stem))})
        if req and not has_svg:
            missing_required.append({"id": pid})
        if req is False and has_svg:
            textonly_with_fig.append({"id": pid})
        if has_svg:
            with_svg += 1
    return {
        "n": len(problems),
        "with_svg": with_svg,
        "text_only": len(problems) - with_svg,
        "dangling_refs": dangling,
        "figure_required_missing": missing_required,
        "textonly_with_figure": textonly_with_fig,
    }


def failures(rep: dict) -> list[str]:
    out: list[str] = []
    if rep["dangling_refs"]:
        out.append(f"{len(rep['dangling_refs'])} dangling figure reference(s)")
    if rep["figure_required_missing"]:
        out.append(f"{len(rep['figure_required_missing'])} figure_required without an svg")
    if rep["textonly_with_figure"]:
        out.append(f"{len(rep['textonly_with_figure'])} text-only problem(s) carry a figure")
    return out


def _load(args) -> list[dict]:
    if args.problems:
        data = json.loads(Path(args.problems).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("problems", [])
    b = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    return b.get("problems", [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--problems", help="a JSON list of problems (grow content_set.json)")
    ap.add_argument("--bundle", help="the content bundle (uses its problems)")
    ap.add_argument("--json", action="store_true", help="emit the JSON report")
    ap.add_argument("--strict", action="store_true", help="exit non-zero on any failure")
    args = ap.parse_args()
    if not args.problems and not args.bundle:
        ap.error("pass --problems or --bundle")

    rep = check(_load(args))
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(f"problems={rep['n']}  with_svg={rep['with_svg']}  text_only={rep['text_only']}")
        for key, label in (
            ("dangling_refs", "DANGLING (references a figure, has none)"),
            ("figure_required_missing", "FIGURE_REQUIRED but no svg"),
            ("textonly_with_figure", "TEXT-ONLY but carries a figure"),
        ):
            items = rep[key]
            print(f"  {label}: {len(items)}")
            for it in items[:20]:
                print(f"    {it['id']}" + (f"  {it.get('snippet','')}" if it.get("snippet") else ""))
        fails = failures(rep)
        print("\nHARD CHECKS: " + ("all clear" if not fails else "; ".join(fails)))

    return 1 if (args.strict and failures(rep)) else 0


if __name__ == "__main__":
    sys.exit(main())
