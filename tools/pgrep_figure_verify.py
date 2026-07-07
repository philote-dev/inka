#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Independent fidelity check for pgrep problem figures.

Given the figures produced by ``pgrep_figure_gen.py`` (a JSON list of
``{id, stem, svg}``), ask a judge model, deliberately a different snapshot from
the one that drew them, whether each SVG faithfully and sufficiently depicts the
setup the problem stem describes: every named component or object is present, the
geometry or circuit topology is consistent, the symbolic labels match the
variables in the stem, nothing contradicts the text, and no numeric values were
drawn onto the figure (numbers belong in the stem).

This is the gate behind "diagrams are produced for the questions that need them,
and they actually match the problem". It never draws or edits a figure and never
touches the bundle; it only writes a verdict list. Items that do not match are
routed to a human review file by the caller.

Run:
    python tools/pgrep_figure_verify.py --figures content/run/triple/figures/figs.json \\
        --out content/run/triple/figures/verdicts.json
    python tools/pgrep_figure_verify.py --figures figs.json --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = REPO / "pylib" / "anki" / "pgrep" / "content_bundle.json"

SVG_RE = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)
FIGURE_DIV_RE = re.compile(r'<div class="pg-figure">[\s\S]*?</div>', re.IGNORECASE)

JUDGE_SYSTEM = (
    "You verify that an SVG line-art diagram faithfully depicts a Physics GRE "
    "problem. You are given the problem stem (the words the student reads) and "
    "the SVG source. Decide whether the figure correctly and sufficiently shows "
    "the setup the stem describes.\n"
    "Check: every physical object, component, or body named in the stem appears "
    "in the figure; the geometry, arrangement, or circuit topology matches the "
    "text; symbolic labels in the figure correspond to variables in the stem; "
    "nothing in the figure contradicts the text; the figure carries NO numeric "
    "values or units (those belong in the stem); and a student could use the "
    "figure to reason about the problem.\n"
    'Return STRICT JSON only: {"matches": true|false, "missing": [str], '
    '"contradictions": [str], "has_numbers": true|false, "notes": str}. '
    "List concrete gaps in missing/contradictions. Set matches=false if any "
    "named element is missing, anything contradicts the text, or numbers appear."
)


def strip_figure(stem: str) -> str:
    return FIGURE_DIV_RE.sub(" ", stem or "")


class Judge:
    def __init__(self, model: str, key: str) -> None:
        from openai import OpenAI  # type: ignore[import-not-found]

        self.model = model
        self.client = OpenAI(api_key=key, max_retries=5)
        self._reasoning = model.startswith(("gpt-5", "o1", "o3", "o4"))

    def verify(self, stem: str, svg: str) -> dict:
        user = f"PROBLEM STEM:\n{stem}\n\nSVG SOURCE:\n{svg}"
        temp = {} if self._reasoning else {"temperature": 0}
        last = None
        for extra in (
            dict(response_format={"type": "json_object"}, **temp),
            dict(**temp),
            dict(),
        ):
            try:
                r = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": JUDGE_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    **extra,
                )
                raw = (r.choices[0].message.content or "{}").strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    m = re.search(r"\{[\s\S]*\}", raw)
                    return (
                        json.loads(m.group(0))
                        if m
                        else {"matches": False, "notes": "unparseable judge reply"}
                    )
            except Exception as e:  # noqa: BLE001
                last = e
        return {"matches": False, "notes": f"judge call failed: {last}"}


def load_key(env_file: str | None) -> str:
    import os

    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    for path in [
        Path(env_file) if env_file else None,
        REPO / "content" / ".env",
        REPO / ".env",
    ]:
        if path and path.is_file():
            for line in path.read_text().splitlines():
                if line.strip().startswith("OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("No OPENAI_API_KEY found")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--figures", required=True, help="JSON list of {id, stem?, svg}")
    ap.add_argument(
        "--bundle", default=str(DEFAULT_BUNDLE), help="fallback for stems by id"
    )
    ap.add_argument(
        "--model",
        default="gpt-5.4-2026-03-05",
        help="judge snapshot (must differ from the figure generator)",
    )
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--out", default=None, help="write verdicts JSON here")
    ap.add_argument(
        "--strict", action="store_true", help="exit non-zero if any figure fails"
    )
    args = ap.parse_args()

    figures = json.loads(Path(args.figures).read_text(encoding="utf-8"))
    stems_by_id: dict[str, str] = {}
    if Path(args.bundle).is_file():
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        stems_by_id = {
            p["id"]: strip_figure(p.get("stem", "")) for p in bundle.get("problems", [])
        }

    judge = Judge(args.model, load_key(args.env_file))
    verdicts: list[dict] = []
    n_fail = 0
    print(f"judge: {args.model}; verifying {len(figures)} figures...")
    for f in figures:
        svg = f.get("svg", "") or ""
        if not SVG_RE.search(svg):
            verdicts.append(
                {"id": f.get("id"), "matches": False, "notes": "no svg to verify"}
            )
            n_fail += 1
            print(f"  {f.get('id')}  NO-SVG")
            continue
        stem = f.get("stem") or stems_by_id.get(f.get("id"), "")
        v = judge.verify(stem, svg)
        v_out = {"id": f.get("id"), **v}
        verdicts.append(v_out)
        ok = bool(v.get("matches"))
        n_fail += 0 if ok else 1
        detail = (
            ""
            if ok
            else f"  missing={v.get('missing')} contra={v.get('contradictions')} nums={v.get('has_numbers')}"
        )
        print(f"  {f.get('id')}  {'MATCH' if ok else 'FAIL'}{detail}")

    out = args.out or (str(Path(args.figures).with_name("verdicts.json")))
    Path(out).write_text(json.dumps(verdicts, indent=2, ensure_ascii=False))
    print(f"\n{len(figures) - n_fail}/{len(figures)} matched. wrote {out}")
    return 1 if (args.strict and n_fail) else 0


if __name__ == "__main__":
    sys.exit(main())
