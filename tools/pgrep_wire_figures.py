#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Embed generated SVG figures into problem stems in the pgrep content bundle.

Each figure is appended to its problem's stem inside a `.pg-figure` wrapper, so
the Study, Exam, and review surfaces (which all render the stem through
renderMath, leaving non-LaTeX HTML untouched) display it below the question text
and above the choices, matching the exam layout. Numeric values stay in the stem
text; the figure carries only symbolic labels.

Idempotent: an existing `.pg-figure` block is replaced, so re-running with an
updated figure set is safe. Backs up the bundle to content_bundle.pre_figures.json
on first run. Never touches non-figure content.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = REPO / "pylib" / "anki" / "pgrep" / "content_bundle.json"

FIGURE_RE = re.compile(r'\s*<div class="pg-figure">[\s\S]*?</div>\s*$')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--figures", required=True, help="JSON list of {id, svg}")
    ap.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    args = ap.parse_args()

    bundle_path = Path(args.bundle)
    bundle = json.loads(bundle_path.read_text())
    figures = json.loads(Path(args.figures).read_text())
    fig_by_id = {
        f["id"]: f.get("svg", "")
        for f in figures
        if f.get("svg", "").strip().startswith("<svg")
    }

    backup = bundle_path.with_name("content_bundle.pre_figures.json")
    if not backup.exists():
        backup.write_text(bundle_path.read_text())
        print(f"backed up bundle to {backup.name}")

    by_id = {p["id"]: p for p in bundle["problems"]}
    wired = 0
    for pid, svg in fig_by_id.items():
        p = by_id.get(pid)
        if p is None:
            print(f"  ! {pid} not in bundle, skipping")
            continue
        stem = FIGURE_RE.sub(
            "", p.get("stem", "")
        )  # drop any prior figure (idempotent)
        p["stem"] = f'{stem}\n<div class="pg-figure">{svg}</div>'
        wired += 1

    bundle_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    print(f"wired {wired} figures into {bundle_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
