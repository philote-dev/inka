#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Generate black-and-white line-art SVG figures for pgrep problems that benefit
from a diagram, in the style of ETS Physics GRE practice figures.

Two conventions, matching the real exam:
- The figure carries only SYMBOLIC labels (R, L, C, B, v). Numeric values and
  units stay in the question text, which keeps figures uncluttered and avoids
  labels colliding with the lines.
- Every figure is monochrome and theme-aware (stroke="currentColor",
  fill="none"), so one SVG reads black-on-white in light mode and white-on-dark
  in dark mode.

A generate pass drafts each figure; a refine pass then strips any stray numbers,
repositions labels clear of the geometry, and adds viewBox padding. Output is a
JSON map (id -> svg) plus an HTML preview showing each figure in a light and a
dark panel. Never modifies content_bundle.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = REPO / "pylib" / "anki" / "pgrep" / "content_bundle.json"

# Route every model call through the one pinned client. The offline tools import
# the AI core as ``pgrep.ai.*`` with ``pylib/anki`` on the path (no compiled
# backend needed). Append it, never prepend: pylib/anki holds modules named like
# stdlib ones, so only the unique ``pgrep`` name should resolve from here.
_AI_CORE = REPO / "pylib" / "anki"
if _AI_CORE.is_dir() and str(_AI_CORE) not in sys.path:
    sys.path.append(str(_AI_CORE))

from pgrep.ai import llm  # type: ignore[import-not-found]  # noqa: E402

SYSTEM = r"""You draw a single clean black-and-white line-art SVG diagram for a Physics GRE problem, in the style of ETS practice-test figures.

Hard rules:
- Output ONLY a JSON object of the form {"svg": "<svg ...>...</svg>"} and nothing else.
- The SVG must declare a viewBox and NO fixed pixel width/height above 400. Target about 360 wide, with generous internal padding so nothing is clipped.
- Monochrome and theme-aware: stroke="currentColor" everywhere; fill="none" except small solid dots or arrowheads which may use fill="currentColor". Use NO color and NO background rectangle.
- stroke-width between 1.5 and 2. Rounded line caps.
- Use standard physics symbols: resistor as a plain rectangle, capacitor as two short parallel plates, inductor as a row of small arcs, DC source as long and short parallel lines, generic source or meter as a circle (ammeter labeled A, voltmeter V). Draw force, velocity, and current as arrows with clear arrowheads. Mark a field into the page with x's and out of the page with dots.
- Label components with SYMBOLIC variables ONLY (R, L, C, B, v, theta, and the like). NEVER put numeric values or units on the figure (do not write "0.20 ohm", "3.0 m/s", "40 mH"); those numbers belong in the question text.
- Place every <text> label clear of all lines and components, with a comfortable gap, and never overlapping another label. Use font-style="italic" for single-letter variables. Keep labels minimal.
- Be geometrically correct for the described setup and keep it uncluttered. Do NOT include the question prose in the SVG.
- If the problem genuinely needs no figure, return {"svg": ""}."""

REFINE_SYSTEM = r"""You are given an SVG physics diagram to clean up WITHOUT changing its physical content, components, or topology.

Apply only these fixes:
- Remove any numeric values or units (for example "0.20 ohm", "3.0 m/s", "40 mH", "100 V"); keep only symbolic variable labels (R, L, C, B, v, theta, ...). Numbers belong in the question text, not the figure.
- Ensure NO text overlaps any line, shape, arrowhead, or other text. Reposition each label so it sits clearly outside its component with a small gap.
- Add or widen the viewBox padding so nothing is clipped and labels have room.
- Keep stroke="currentColor", fill="none" (solid only for small dots or arrowheads), monochrome, no background rectangle, and the exact same components and layout.

Return ONLY a JSON object {"svg": "<svg ...>...</svg>"} and nothing else."""


class Gen:
    def __init__(self, model: str, key: str | None = None, *, client=None) -> None:
        # ``key`` is accepted for the existing callers that still pass one
        # positionally; the key now lives in the environment (see
        # ``llm.load_api_key``) and the pinned client reads it there. Pass
        # ``client`` to inject a fake in tests (no network).
        self.client = client if client is not None else llm.generator_client(model)
        self.model = getattr(self.client, "model", model)

    def _call(self, system: str, user: str) -> str:
        try:
            raw = (
                self.client.complete_text(system, user, json_object=True) or "{}"
            ).strip()
        except Exception as e:  # noqa: BLE001
            print(f"  ! call failed: {e}", file=sys.stderr)
            return ""
        try:
            return json.loads(raw).get("svg", "")
        except json.JSONDecodeError:
            m = re.search(r"<svg[\s\S]*?</svg>", raw)
            return m.group(0) if m else ""

    def svg_for(self, stem: str, hint: str) -> str:
        return self._call(
            SYSTEM,
            f"Category: {hint}\n\nProblem stem:\n{stem}\n\nDraw the figure a test would print for this problem.",
        )

    def refine(self, svg: str) -> str:
        if not svg.strip().startswith("<svg"):
            return svg
        out = self._call(REFINE_SYSTEM, svg)
        return out if out.strip().startswith("<svg") else svg

    def svg_for_feedback(
        self, stem: str, hint: str, prior_svg: str, complaints: str
    ) -> str:
        """Redraw a figure, correcting the specific problems a reviewer found."""
        return self._call(
            SYSTEM,
            (
                f"Category: {hint}\n\nProblem stem:\n{stem}\n\n"
                "A previous attempt drew this figure, but a reviewer found "
                f"these problems you MUST fix:\n{complaints}\n\n"
                "Previous SVG (correct its content; keep the line-art style "
                f"and all the conventions):\n{prior_svg}\n\n"
                "Redraw the figure so it faithfully matches the stem and "
                "resolves every listed problem."
            ),
        )


def load_key(env_file: str | None = None) -> str:
    """Load the API key into the environment and return it.

    Kept for callers that pass a key positionally to ``Gen``. The actual loading
    lives in ``llm.load_api_key`` (the one shared implementation); this returns
    the value so existing callers that build their own client can reuse it.
    """
    import os

    llm.load_api_key(env_file)
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("No OPENAI_API_KEY found")
    return key


def category_hint(topic: str, text: str) -> str:
    t = text.lower()
    if re.search(
        r"circuit|capacitor|resistor|inductor|rlc|ammeter|voltmeter|emf|battery|reactance|impedance",
        t,
    ):
        return "circuit diagram"
    if re.search(
        r"incline|pulley|ramp|projectile|block|spring|rod|rails|loop|pendulum|collision",
        t,
    ):
        return "mechanics setup with free-body arrows"
    if re.search(r"p-?v|isotherm|carnot|adiabatic|cycle", t):
        return "P-V diagram with labeled points"
    if re.search(r"lens|mirror|focal|refract|prism|ray|slit|grating", t):
        return "optics ray diagram"
    return "schematic"


def build_html(out: list[dict]) -> str:
    def panel(cls, bg, fg):
        cards = "".join(
            f'<div class="fig"><div class="stem">{r["id"]} &mdash; {r.get("hint", "")}</div>'
            f'<div class="stemtext">{(r.get("stem") or "")[:180]}</div>'
            f'<div class="svgbox">{r.get("svg") or "<em>(empty)</em>"}</div></div>'
            for r in out
        )
        return f'<section class="{cls}" style="background:{bg};color:{fg}"><h2>{cls}</h2>{cards}</section>'

    return (
        "<!doctype html><meta charset=utf-8><title>Figures</title>"
        "<style>body{font-family:-apple-system,system-ui,sans-serif;margin:0}"
        "section{padding:24px}h2{opacity:.6;font-weight:500;text-transform:uppercase;letter-spacing:.08em;font-size:12px}"
        ".fig{border:1px solid currentColor;border-radius:12px;padding:16px;margin:0 0 16px;max-width:640px}"
        ".stem{font-size:12px;opacity:.6;margin-bottom:4px}.stemtext{font-size:13px;opacity:.85;margin-bottom:12px;line-height:1.4}"
        ".svgbox svg{max-width:100%;height:auto}</style>"
        + panel("light", "#f4f1ec", "#1c1a17")
        + panel("dark", "#17150f", "#efe9df")
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument(
        "--refine-json",
        default=None,
        help="refine the SVGs in an existing output json instead of generating",
    )
    ap.add_argument(
        "--no-refine",
        action="store_true",
        help="skip the cleanup pass in generate mode",
    )
    ap.add_argument("--model", default="gpt-5.5")
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--json", default="tools/figure_pilot.json")
    ap.add_argument("--html", default="tools/figure_pilot.html")
    args = ap.parse_args()

    llm.load_api_key(args.env_file)
    gen = Gen(args.model)

    if args.refine_json:
        out = json.loads(Path(args.refine_json).read_text())
        print(f"model: {args.model}; refining {len(out)} figures...")
        for r in out:
            before = r.get("svg", "")
            r["svg"] = gen.refine(before)
            print(f"  {r['id']}  refined  {len(before)} -> {len(r['svg'])} chars")
    else:
        if not args.ids:
            print("Pass --ids or --refine-json.")
            return 0
        bundle = json.loads(Path(args.bundle).read_text())
        by_id = {p["id"]: p for p in bundle["problems"]}
        picks = [by_id[i] for i in args.ids if i in by_id]
        print(
            f"model: {args.model}; generating {len(picks)} figures (refine={'off' if args.no_refine else 'on'})..."
        )
        out = []
        for p in picks:
            stem = p.get("stem", "")
            hint = category_hint(
                p.get("topic", ""), stem + " " + " ".join(p.get("choices", []))
            )
            svg = gen.svg_for(stem, hint)
            if not args.no_refine and svg.strip().startswith("<svg"):
                svg = gen.refine(svg)
            ok = svg.strip().startswith("<svg")
            print(f"  {p['id']}  [{hint}]  {'ok' if ok else 'EMPTY'}  {len(svg)} chars")
            out.append({"id": p["id"], "hint": hint, "stem": stem, "svg": svg})

    Path(args.json).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    Path(args.html).write_text(build_html(out))
    print(f"wrote {args.json} and {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
