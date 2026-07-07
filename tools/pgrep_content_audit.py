#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Audit the pgrep content bundle: counts, blueprint coverage, citations, copy.

A read-only, stdlib-only report over ``content_bundle.json`` (no AI deps, no
Collection). It is the ground-truth check behind the L5.9 content moves:

- counts of cards and problems, cross-checked against the bundle's own metadata;
- blueprint coverage across the nine areas, for cards and problems separately;
- ``source_ref`` coverage (a real citation versus none), the cite-or-refuse rule;
- the copy rule: every em-dash (and, for review, every en-dash) in the shipped
  prose, with its item id, field, and a context snippet, so the sweep can drive
  the count to zero;
- near-duplicate stems/fronts (normalized-text hash), to confirm the dedup;
- the authored difficulty range on problems (the 0..1 fraction the seeder maps
  to the 1..5 Performance scale);
- how many problems ship an embedded figure versus are text-only.

Run it before and after a content edit; ``--json`` emits the machine report and
the exit code is non-zero when a hard invariant fails (an em-dash remains, a
problem is uncited, or the counts disagree with the metadata).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.dom import minidom

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = REPO / "pylib" / "anki" / "pgrep" / "content_bundle.json"

# The nine canonical blueprint categories, in order, duplicated from
# ``anki.pgrep.blueprint`` so this tool imports nothing from the compiled app.
BLUEPRINT_PERCENT: dict[str, float] = {
    "mechanics": 0.20,
    "electromagnetism": 0.18,
    "quantum": 0.13,
    "thermodynamics": 0.10,
    "atomic": 0.10,
    "optics_waves": 0.08,
    "special_relativity": 0.06,
    "lab": 0.06,
    "specialized": 0.09,
}
CATEGORY_SLUGS = tuple(BLUEPRINT_PERCENT)

EM_DASH = "\u2014"  # —
EN_DASH = "\u2013"  # –
_WORD = re.compile(r"[a-z0-9]+")
_FIGURE_RE = re.compile(r'\s*<div class="pg-figure">[\s\S]*?</div>\s*', re.IGNORECASE)

# Figure conventions (pgrep_figure_gen.py): monochrome, theme-aware via
# currentColor, symbolic labels only, and token-free (numbers live in the stem).
_SVG_RE = re.compile(r"<svg[\s\S]*?</svg>")
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,6}")
_SVG_TEXT_RE = re.compile(r"<text[^>]*>(.*?)</text>", re.S)
_NUM_UNIT_RE = re.compile(
    r"\d\s*(?:ohm|Ω|m/s|mH|µF|uF|nF|pF|mA|kV|kg|cm|mm|nm|eV|Hz|rad|deg|°)|\d+\.\d+",
    re.IGNORECASE,
)


def category_of(topic: str | None) -> str:
    """Category slug (2nd ``::`` segment) of a ``topic::…`` tag; else ``unknown``."""
    if not topic:
        return "unknown"
    parts = topic.split("::")
    if len(parts) >= 2 and parts[0].lower() == "topic" and parts[1].strip():
        return parts[1].strip().lower()
    return "unknown"


def normalized_hash(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def strip_figure(stem: str) -> str:
    return _FIGURE_RE.sub(" ", stem)


def prose_fields(item: dict, kind: str) -> list[tuple[str, str]]:
    """(field-label, text) pairs of the shipped prose for one item.

    The problem stem is scanned with its embedded SVG figure stripped, so figure
    markup never counts as copy.
    """
    out: list[tuple[str, str]] = []
    if kind == "card":
        out.append(("front", item.get("front", "")))
        out.append(("back", item.get("back", "")))
    else:
        out.append(("stem", strip_figure(item.get("stem", ""))))
        for i, choice in enumerate(item.get("choices", [])):
            out.append((f"choices[{i}]", str(choice)))
        for d in item.get("distractors", []):
            if isinstance(d, dict):
                out.append(
                    (f"distractor {d.get('label', '?')}", d.get("rationale", ""))
                )
        for i, step in enumerate(item.get("solution_decomposition", [])):
            if isinstance(step, dict):
                out.append((f"decomp[{i}].subgoal", step.get("subgoal", "")))
                out.append((f"decomp[{i}].rubric", step.get("rubric", "")))
    return [(label, text) for label, text in out if isinstance(text, str) and text]


def snippet(text: str, index: int, width: int = 34) -> str:
    lo = max(0, index - width)
    hi = min(len(text), index + width)
    return (
        ("…" if lo else "")
        + text[lo:hi].replace("\n", " ")
        + ("…" if hi < len(text) else "")
    )


def find_dashes(items: list[dict], kind: str, char: str) -> list[dict]:
    hits: list[dict] = []
    for item in items:
        for label, text in prose_fields(item, kind):
            for m in re.finditer(re.escape(char), text):
                hits.append(
                    {
                        "id": item.get("id"),
                        "field": label,
                        "context": snippet(text, m.start()),
                    }
                )
    return hits


def coverage(items: list[dict]) -> dict[str, int]:
    counts = {slug: 0 for slug in CATEGORY_SLUGS}
    counts["unknown"] = 0
    for item in items:
        counts[category_of(item.get("topic"))] = (
            counts.get(category_of(item.get("topic")), 0) + 1
        )
    return counts


def cited(item: dict) -> bool:
    return bool((item.get("source_ref") or "").strip())


def duplicates(items: list[dict], key: str) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    dups: list[tuple[str, str]] = []
    for item in items:
        raw = item.get(key, "")
        if key == "stem":
            raw = strip_figure(raw)
        h = normalized_hash(raw)
        if h in seen:
            dups.append((seen[h], item.get("id", "?")))
        else:
            seen[h] = item.get("id", "?")
    return dups


def difficulty_range(problems: list[dict]) -> dict:
    vals = [
        p["difficulty"]
        for p in problems
        if isinstance(p.get("difficulty"), (int, float))
        and not isinstance(p.get("difficulty"), bool)
    ]
    non_numeric = [
        p.get("id")
        for p in problems
        if not (
            isinstance(p.get("difficulty"), (int, float))
            and not isinstance(p.get("difficulty"), bool)
        )
    ]
    return {
        "n_numeric": len(vals),
        "min": min(vals) if vals else None,
        "max": max(vals) if vals else None,
        "looks_like_0_1": bool(vals) and min(vals) >= 0.0 and max(vals) <= 1.0,
        "non_numeric_ids": non_numeric,
    }


# A stem that hands over the solving relation reads like "using <symbol> = ...",
# "recall that ...", or "apply the ... formula/relation/law". This is a cheap,
# offline signal (the AI judge in content/tools/check_technique_giveaway.py is the
# thorough check); it deliberately ignores plain given constants like "g = 9.8".
_GIVEAWAY_RE = re.compile(
    r"(?i)\b(?:using|use|apply(?:ing)?)\b[^.]{0,40}"
    r"(?:\brelation\b|\bformula\b|\bequation\b|\bidentity\b|\blaw\b|"
    r"[A-Za-z_](?:_\{?[A-Za-z0-9]+\}?)?\s*=)"
    r"|\brecall that\b|\bthe (?:key|trick|method) (?:is|to)\b"
)


def giveaway_signals(stem: str) -> list[str]:
    """Phrases in a stem that likely hand over the solving relation, empty if none.

    Strips the figure markup first. This is a heuristic tripwire, not the final
    word; the AI judge is authoritative. It exists so the standard audit surfaces
    obvious regressions without needing an API key.
    """
    text = strip_figure(stem)
    hits: list[str] = []
    for m in _GIVEAWAY_RE.finditer(text):
        snip = text[m.start():m.start() + 60].replace("\n", " ").strip()
        hits.append(snip)
    return hits


def figure_violations(stem: str) -> list[str]:
    """Convention problems in an embedded figure, empty when it is clean.

    Enforces the ``pgrep_figure_gen`` rules: a well-formed, theme-aware SVG with a
    viewBox and ``currentColor``, no hardcoded colors, no design tokens, and no
    numeric or unit labels (those belong in the stem text).
    """
    match = _SVG_RE.search(stem)
    if not match:
        return ["figure marker present but no <svg> found"]
    svg = match.group(0)
    issues: list[str] = []
    try:
        minidom.parseString(svg)
    except Exception as exc:  # noqa: BLE001 - report, do not crash the audit
        issues.append(f"malformed SVG ({str(exc)[:40]})")
    if "viewBox" not in svg:
        issues.append("no viewBox")
    if "currentColor" not in svg:
        issues.append("not theme-aware (no currentColor)")
    if _HEX_RE.search(svg):
        issues.append(f"hardcoded color {sorted(set(_HEX_RE.findall(svg)))}")
    if "var(--" in svg:
        issues.append("uses a design token (var(--...))")
    for label in _SVG_TEXT_RE.findall(svg):
        if _NUM_UNIT_RE.search(label):
            issues.append(f"numeric/unit label {label.strip()[:24]!r}")
            break
    return issues


def figures(problems: list[dict]) -> dict:
    with_fig = [p for p in problems if "pg-figure" in p.get("stem", "")]
    violations = [
        {"id": p.get("id"), "issues": issues}
        for p in with_fig
        if (issues := figure_violations(p.get("stem", "")))
    ]
    return {
        "with_figure": len(with_fig),
        "text_only": len(problems) - len(with_fig),
        "violations": violations,
    }


def build_report(bundle: dict) -> dict:
    cards = bundle.get("cards", [])
    problems = bundle.get("problems", [])
    meta_counts = bundle.get("counts", {})

    card_cov = coverage(cards)
    prob_cov = coverage(problems)

    return {
        "counts": {
            "cards": len(cards),
            "problems": len(problems),
            "total": len(cards) + len(problems),
            "metadata_says": meta_counts,
            "counts_match_metadata": (
                meta_counts.get("cards") == len(cards)
                and meta_counts.get("problems") == len(problems)
            ),
        },
        "coverage": {
            "areas_covered_cards": sum(1 for s in CATEGORY_SLUGS if card_cov[s] > 0),
            "areas_covered_problems": sum(1 for s in CATEGORY_SLUGS if prob_cov[s] > 0),
            "cards_by_area": card_cov,
            "problems_by_area": prob_cov,
        },
        "citations": {
            "cards_cited": sum(1 for c in cards if cited(c)),
            "cards_uncited": sorted(c["id"] for c in cards if not cited(c)),
            "problems_cited": sum(1 for p in problems if cited(p)),
            "problems_uncited": sorted(p["id"] for p in problems if not cited(p)),
        },
        "copy": {
            "em_dash_cards": find_dashes(cards, "card", EM_DASH),
            "em_dash_problems": find_dashes(problems, "problem", EM_DASH),
            "en_dash_count_cards": len(find_dashes(cards, "card", EN_DASH)),
            "en_dash_count_problems": len(find_dashes(problems, "problem", EN_DASH)),
        },
        "duplicates": {
            "card_fronts": duplicates(cards, "front"),
            "problem_stems": duplicates(problems, "stem"),
        },
        "difficulty": difficulty_range(problems),
        "technique_giveaways": [
            {"id": p.get("id"), "signals": sig}
            for p in problems
            if (sig := giveaway_signals(p.get("stem", "")))
        ],
        "figures": figures(problems),
        "excluded_ids": bundle.get("provenance", {}).get("excluded_ids", {}),
    }


def print_report(r: dict) -> None:
    c = r["counts"]
    print("== COUNTS ==")
    print(f"  cards={c['cards']}  problems={c['problems']}  total={c['total']}")
    print(f"  metadata says {c['metadata_says']}  match={c['counts_match_metadata']}")

    cov = r["coverage"]
    print("\n== BLUEPRINT COVERAGE (9 areas) ==")
    print(
        f"  cards cover {cov['areas_covered_cards']}/9   problems cover {cov['areas_covered_problems']}/9"
    )
    print(f"  {'area':<18}{'weight':>7}{'cards':>7}{'problems':>10}")
    for slug in CATEGORY_SLUGS:
        print(
            f"  {slug:<18}{BLUEPRINT_PERCENT[slug] * 100:>6.0f}%"
            f"{cov['cards_by_area'][slug]:>7}{cov['problems_by_area'][slug]:>10}"
        )
    if cov["cards_by_area"].get("unknown") or cov["problems_by_area"].get("unknown"):
        print(
            f"  !! unknown/untagged: cards={cov['cards_by_area'].get('unknown', 0)}"
            f" problems={cov['problems_by_area'].get('unknown', 0)}"
        )

    cit = r["citations"]
    print("\n== CITATIONS (cite-or-refuse) ==")
    print(
        f"  cards cited    {cit['cards_cited']}/{c['cards']}   uncited: {cit['cards_uncited'] or 'none'}"
    )
    print(
        f"  problems cited {cit['problems_cited']}/{c['problems']}   uncited: {cit['problems_uncited'] or 'none'}"
    )

    copy = r["copy"]
    em = copy["em_dash_cards"] + copy["em_dash_problems"]
    print("\n== COPY RULE ==")
    print(f"  em-dashes (—): {len(em)}   [must reach 0]")
    for h in em:
        print(f"    {h['id']:<16} {h['field']:<22} {h['context']}")
    print(
        f"  en-dashes (–) for review: cards={copy['en_dash_count_cards']} problems={copy['en_dash_count_problems']}"
    )

    dup = r["duplicates"]
    print("\n== DUPLICATES (normalized text) ==")
    print(f"  card fronts: {dup['card_fronts'] or 'none'}")
    print(f"  problem stems: {dup['problem_stems'] or 'none'}")

    d = r["difficulty"]
    print("\n== DIFFICULTY (problems) ==")
    print(
        f"  numeric={d['n_numeric']}  min={d['min']}  max={d['max']}  looks_like_0..1={d['looks_like_0_1']}"
    )
    if d["non_numeric_ids"]:
        print(f"  non-numeric: {d['non_numeric_ids']}")

    tg = r.get("technique_giveaways", [])
    print("\n== TECHNIQUE GIVEAWAYS (heuristic; AI judge is authoritative) ==")
    print(f"  stems that may hand over the solving relation: {len(tg)}")
    for h in tg[:15]:
        print(f"    {h['id']}: {h['signals'][0]}")
    if len(tg) > 15:
        print(f"    ... and {len(tg) - 15} more")

    f = r["figures"]
    print("\n== FIGURES ==")
    print(f"  with figure: {f['with_figure']}   text-only: {f['text_only']}")
    if f.get("violations"):
        for v in f["violations"]:
            print(f"    {v['id']}: {', '.join(v['issues'])}")
    else:
        print(
            "  all embedded figures pass the monochrome/currentColor/no-number conventions"
        )


def hard_failures(r: dict) -> list[str]:
    fails = []
    em = r["copy"]["em_dash_cards"] + r["copy"]["em_dash_problems"]
    if em:
        fails.append(f"{len(em)} em-dash(es) remain in shipped prose")
    if r["citations"]["problems_uncited"]:
        fails.append(
            f"{len(r['citations']['problems_uncited'])} problem(s) have no source_ref"
        )
    if not r["counts"]["counts_match_metadata"]:
        fails.append("counts disagree with bundle metadata")
    if r["figures"].get("violations"):
        fails.append(
            f"{len(r['figures']['violations'])} figure(s) violate the SVG conventions"
        )
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    ap.add_argument(
        "--json", action="store_true", help="emit the machine report as JSON"
    )
    ap.add_argument(
        "--strict", action="store_true", help="exit non-zero on any hard failure"
    )
    args = ap.parse_args()

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    report = build_report(bundle)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)
        fails = hard_failures(report)
        print("\n== HARD INVARIANTS ==")
        print("  all clear" if not fails else "\n".join(f"  FAIL: {f}" for f in fails))

    if args.strict and hard_failures(report):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
