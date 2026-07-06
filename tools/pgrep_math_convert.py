#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Convert bare ASCII/Unicode physics notation in the pgrep content bundle into
delimited LaTeX so MathJax can typeset it.

The UI renderer (ts/lib/pgrep/math.ts) turns \\( ... \\) inline and \\[ ... \\]
display spans into SVG. Some generated Problems already carry delimited LaTeX;
the Cards and many Problem fields are still ASCII (for example "K = (1/2)mv^2").
This tool sends each math-bearing content field to an LLM with a strict
instruction to wrap only the mathematics in delimiters and leave the surrounding
prose byte for byte identical. Existing LaTeX spans are skipped, so re-running is
safe.

Modes:
  --sample   convert a small review set to tools/mathconv_sample.(md|json); never
             touches the source bundle.
  --apply    convert every math-bearing field and write a NEW bundle to --out
             plus a change report to --md; still never overwrites the source.

Fields are deduplicated before calling the model and converted concurrently.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = REPO / "pylib" / "anki" / "pgrep" / "content_bundle.json"

CARD_FIELDS = ("front", "back")

# Already-delimited LaTeX or a TeX environment: do not touch.
LATEX = re.compile(r"\\\(|\\\[|\\begin\{")

# Heuristic for bare math outside LaTeX: superscripts, sqrt, integrals, common
# operators and Greek, digit/letter fractions, and subscripts on symbols.
MATH_SIGNAL = re.compile(
    r"\^"
    r"|(?<![A-Za-z])sqrt\("
    r"|[∫√≈≥≤≠·×÷→±∞ΔδθλμνπρστφχψωΩ∇∑∏∂]"
    r"|[A-Za-z0-9\)]_[0-9A-Za-z]"
    r"|(?<![A-Za-z])\d+\s*/\s*[0-9A-Za-z(]"
)

SYSTEM = r"""You convert physics notation into LaTeX for a Physics GRE study app.

Rules:
- Wrap every mathematical expression in LaTeX delimiters: \( ... \) for inline math, \[ ... \] for a standalone displayed equation.
- Leave all non-mathematical prose exactly as written, character for character. Do not reword, translate, summarize, add, or drop anything.
- Never alter text that is already inside \( \) or \[ \].
- Use standard LaTeX: \frac or \tfrac, ^{ }, _{ }, \sqrt{ }, \vec{ }, \hat{ }, \int_a^b, \partial, \Delta, \omega, \pi, \cdot, \times, \approx, \geq, \leq, and \mathrm{ } for units and upright words inside math.
- Preserve meaning precisely. Treat a dot product as vectors only when the source clearly means vectors.
- Respond with ONLY a JSON object of the form {"text": "<converted string>"} and no other commentary."""

FEWSHOT = [
    (
        "The kinetic energy is K = (1/2)mv^2.",
        r"The kinetic energy is \(K = \tfrac{1}{2}mv^2\).",
    ),
    (
        "W_net = ΔK = K_f − K_i, with K = (1/2)mv^2.",
        r"\(W_{\mathrm{net}} = \Delta K = K_f - K_i\), with \(K = \tfrac{1}{2}mv^2\).",
    ),
    (
        "The net work is the line integral W_net = ∫_A^B F_net · dr.",
        r"The net work is the line integral \(W_{\mathrm{net}} = \int_A^B \vec{F}_{\mathrm{net}} \cdot d\vec{r}\).",
    ),
    ("and/or (left alone)", "and/or (left alone)"),
]


def needs_math(s: str) -> bool:
    return bool(s) and not LATEX.search(s) and bool(MATH_SIGNAL.search(s))


def load_key(env_file: str | None) -> str:
    import os

    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    candidates: list[Path] = []
    if env_file:
        candidates.append(Path(env_file))
    candidates += [REPO / "content" / ".env", REPO / ".env"]
    for path in candidates:
        if path and path.is_file():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line.startswith("OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(
        "No OPENAI_API_KEY in the environment or any --env-file candidate: "
        + ", ".join(str(c) for c in candidates)
    )


class Converter:
    """Model-aware conversion. GPT-5 and o-series reasoning models reject
    temperature and may not take response_format, so the call degrades
    gracefully across a few parameter sets."""

    def __init__(self, model: str, key: str) -> None:
        from openai import OpenAI  # type: ignore[import-not-found]

        self.model = model
        self.client = OpenAI(api_key=key, max_retries=5)
        self._reasoning = model.startswith(("gpt-5", "o1", "o3", "o4"))
        self._base = [{"role": "system", "content": SYSTEM}]
        for src, dst in FEWSHOT:
            self._base.append({"role": "user", "content": src})
            self._base.append({"role": "assistant", "content": json.dumps({"text": dst})})

    def _parse(self, content: str, fallback: str) -> str:
        content = (content or "").strip()
        try:
            return json.loads(content).get("text", fallback)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", content, re.S)
            if m:
                try:
                    return json.loads(m.group(0)).get("text", fallback)
                except json.JSONDecodeError:
                    pass
            return fallback

    def convert(self, text: str) -> str:
        messages = self._base + [{"role": "user", "content": text}]
        temp = {} if self._reasoning else {"temperature": 0}
        attempts: list[dict[str, Any]] = [
            dict(response_format={"type": "json_object"}, **temp),
            dict(**temp),
            dict(),
        ]
        last = None
        for extra in attempts:
            try:
                # The bundle builds plain-dict messages; OpenAI's param type is a
                # stricter union that still accepts these at runtime.
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore[arg-type]
                    **extra,
                )
                return self._parse(resp.choices[0].message.content, text)
            except Exception as e:  # noqa: BLE001 - try the next, simpler param set
                last = e
        print(f"  ! convert failed: {type(last).__name__}: {str(last)[:160]}", file=sys.stderr)
        return text


def balanced(s: str) -> bool:
    return s.count(r"\(") == s.count(r"\)") and s.count(r"\[") == s.count(r"\]")


def prose_preserved(before: str, after: str) -> bool:
    from collections import Counter

    strip = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)
    a = re.sub(r"[^a-zA-Z]", "", strip.sub(" ", after)).lower()
    b = re.sub(r"[^a-zA-Z]", "", before).lower()
    ca, cb = Counter(a), Counter(b)
    return all(cb[ch] >= n for ch, n in ca.items())


def candidates(bundle: dict) -> list[dict]:
    """Every math-bearing content field as a locator record. Metadata (ids,
    topic, kind, source_ref, difficulty, and the distractor misconception slug)
    is never included."""
    out: list[dict] = []
    for ci, c in enumerate(bundle.get("cards", [])):
        for f in CARD_FIELDS:
            v = c.get(f)
            if isinstance(v, str) and needs_math(v):
                out.append({"kind": "card", "ci": ci, "id": c.get("id"), "path": (f,), "field": f, "before": v})
    for pi, p in enumerate(bundle.get("problems", [])):
        pid = p.get("id")
        if isinstance(p.get("stem"), str) and needs_math(p["stem"]):
            out.append({"kind": "problem", "pi": pi, "id": pid, "path": ("stem",), "field": "stem", "before": p["stem"]})
        for i, ch in enumerate(p.get("choices", []) or []):
            if isinstance(ch, str) and needs_math(ch):
                out.append({"kind": "problem", "pi": pi, "id": pid, "path": ("choices", i), "field": f"choices[{i}]", "before": ch})
        for i, d in enumerate(p.get("distractors", []) or []):
            # Only the user-facing rationale. "misconception" is an internal
            # snake_case taxonomy slug (for example zero_speed_at_top), not math.
            v = d.get("rationale") if isinstance(d, dict) else None
            if isinstance(v, str) and needs_math(v):
                out.append({"kind": "problem", "pi": pi, "id": pid, "path": ("distractors", i, "rationale"), "field": f"distractors[{i}].rationale", "before": v})
        for i, sd in enumerate(p.get("solution_decomposition", []) or []):
            for f in ("subgoal", "rubric"):
                v = sd.get(f) if isinstance(sd, dict) else None
                if isinstance(v, str) and needs_math(v):
                    out.append({"kind": "problem", "pi": pi, "id": pid, "path": ("solution_decomposition", i, f), "field": f"solution_decomposition[{i}].{f}", "before": v})
    return out


def convert_unique(conv: Converter, strings: list[str], workers: int) -> dict[str, str]:
    uniq = list(dict.fromkeys(strings))
    mapping: dict[str, str] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for s, out in zip(uniq, ex.map(conv.convert, uniq)):
            mapping[s] = out
            done += 1
            if done % 25 == 0 or done == len(uniq):
                print(f"  converted {done}/{len(uniq)} unique strings", flush=True)
    return mapping


def set_at(container: dict, item_index_key: str, pi: int, path: tuple, value: str) -> None:
    node = container[item_index_key][pi]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def write_report(md_path: str, model: str, records: list[dict], scope: tuple[int, int]) -> int:
    n_card, n_prob = scope
    flagged = [r for r in records if not r["ok_balanced"] or not r["ok_prose"]]
    lines = [
        "# Math conversion report",
        "",
        f"model: `{model}`",
        f"scope: {len(records)} fields converted ({n_card} card, {n_prob} problem)",
        f"flagged for review: {len(flagged)}",
        f"unchanged (possible gaps): {sum(1 for r in records if not r['changed'])}",
        "",
    ]
    ordered = flagged + [r for r in records if r not in flagged]
    for r in ordered:
        flags = []
        if not r["ok_balanced"]:
            flags.append("UNBALANCED")
        if not r["ok_prose"]:
            flags.append("PROSE?")
        if not r["changed"]:
            flags.append("no change")
        head = f"## {r['id']} . {r['field']}"
        if flags:
            head += "  [" + ", ".join(flags) + "]"
        lines += [head, "", "BEFORE", "", "```", r["before"], "```", "", "AFTER", "", "```", r["after"], "```", ""]
    Path(md_path).write_text("\n".join(lines))
    return len(flagged)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    ap.add_argument("--sample", action="store_true", help="convert a small review set; write no bundle")
    ap.add_argument("--apply", action="store_true", help="convert everything; write a NEW bundle to --out")
    ap.add_argument("--limit", type=int, default=10, help="sample size (sample mode)")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--out", default=None, help="apply: converted bundle path (default alongside source)")
    ap.add_argument("--md", default=None, help="report path")
    args = ap.parse_args()

    bundle = json.loads(Path(args.bundle).read_text())
    cands = candidates(bundle)
    if args.ids:
        wanted = set(args.ids)
        cands = [c for c in cands if c["id"] in wanted]
    n_card = sum(1 for c in cands if c["kind"] == "card")
    n_prob = len(cands) - n_card
    print(f"candidates needing conversion: {len(cands)} ({n_card} card, {n_prob} problem)")

    if not (args.sample or args.apply):
        print("Pass --sample or --apply.")
        return 0

    picks = cands
    if args.sample:
        cards_first = [c for c in cands if c["kind"] == "card"] + [c for c in cands if c["kind"] == "problem"]
        picks = cards_first[: args.limit]

    key = load_key(args.env_file)
    conv = Converter(args.model, key)
    print(f"model: {args.model}; workers: {args.workers}; converting {len(picks)} fields...", flush=True)
    mapping = convert_unique(conv, [c["before"] for c in picks], args.workers)

    records = []
    for c in picks:
        after = mapping.get(c["before"], c["before"])
        records.append({
            **{k: c[k] for k in ("kind", "id", "field", "before")},
            "loc": c,
            "after": after,
            "ok_balanced": balanced(after),
            "ok_prose": prose_preserved(c["before"], after),
            "changed": after != c["before"],
        })

    if args.apply:
        out_bundle = copy.deepcopy(bundle)
        for r in records:
            c = r["loc"]
            key_name = "cards" if c["kind"] == "card" else "problems"
            idx = c.get("ci") if c["kind"] == "card" else c.get("pi")
            set_at(out_bundle, key_name, idx, c["path"], r["after"])
        out_path = args.out or str(Path(args.bundle).with_name("content_bundle.converted.json"))
        Path(out_path).write_text(json.dumps(out_bundle, indent=2, ensure_ascii=False) + "\n")
        md_path = args.md or "tools/mathconv_report.md"
        n_flag = write_report(md_path, args.model, records, (n_card, n_prob))
        n_unchanged = sum(1 for r in records if not r["changed"])
        print(f"wrote converted bundle: {out_path}")
        print(f"wrote report: {md_path}")
        print(f"flagged for review: {n_flag}/{len(records)}")
        print(f"unchanged/possible gaps: {n_unchanged}/{len(records)}")
        return 0

    # sample
    out_path = args.out or "tools/mathconv_sample.json"
    md_path = args.md or "tools/mathconv_sample.md"
    Path(out_path).write_text(json.dumps({"model": args.model, "results": [
        {k: r[k] for k in ("kind", "id", "field", "before", "after", "ok_balanced", "ok_prose", "changed")} for r in records
    ]}, indent=2, ensure_ascii=False))
    n_flag = write_report(md_path, args.model, records, (n_card, n_prob))
    print(f"wrote {out_path} and {md_path}")
    print(f"flagged for closer look: {n_flag}/{len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
