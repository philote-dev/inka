# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Deterministic invariants for the pgrep content bundle.

This module owns the single question "is the shipped ``content_bundle.json``
valid?". It is pure Python and import-light on purpose (only the standard
library, ``json`` and ``re``), so it runs directly over the raw JSON without
loading the compiled app, a Collection, or any AI dependency. That lets the same
code back both the CI gate (``pylib/tests/test_pgrep_content_invariants.py``) and
the assembly command (``content/tools/assemble_bundle.py``).

The public surface is two functions:

- ``check_bundle(bundle)`` returns a structured report: a per-violation list of
  offending ids, plus a ``summary`` of counts and the counts-metadata check.
- ``hard_failures(report)`` distills that report into the list of human-readable
  strings that must fail CI. An empty list means the bundle is shippable.

The checks (per problem unless noted):

- exactly five ``choices``;
- ``correct`` is a single letter A-E whose index lands inside ``choices``;
- a non-empty ``stem``;
- a present ``source_ref``;
- no duplicate ids across cards and problems;
- no duplicate normalized problem stems and no duplicate normalized card fronts,
  normalized the way ``tools/pgrep_content_audit.py`` does (strip the figure div,
  strip tags, lowercase, collapse to word tokens);
- balanced LaTeX delimiters in each prose field (equal counts of ``\\(`` and
  ``\\)``, of ``\\[`` and ``\\]``, and an even number of unescaped ``$``);
- the ``counts`` dict agrees with the actual card and problem counts;
- figure necessity: a stem that promises a figure ("as shown", "in the figure",
  "figure below", and the like) must carry an ``<svg>``, and a ``.pg-figure``
  wrapper must contain one;
- for a ``decomposition_tutor`` when present: each subproblem variant has five
  choices and a ``key`` in A-E.

The regexes and the normalization deliberately mirror ``pgrep_content_audit.py``
and ``content/tools/check_figure_necessity.py`` so the gate agrees with the
existing audit tools, while staying self-contained here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CHOICES_EXPECTED = 5
VALID_KEYS = ("A", "B", "C", "D", "E")

# The embedded figure block, as wired by tools/pgrep_wire_figures.py and stripped
# by pgrep_content_audit.py before it scans prose.
_FIGURE_DIV_RE = re.compile(
    r'\s*<div class="pg-figure">[\s\S]*?</div>\s*', re.IGNORECASE
)
# Just the wrapper opener, so a figure block with no <svg> is still detectable.
_PG_FIGURE_OPEN_RE = re.compile(r'<div class="pg-figure">', re.IGNORECASE)
# A rendered figure body (check_figure_necessity.py SVG / audit _SVG_RE).
_SVG_RE = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)
# Any HTML tag, for the "strip tags" step of normalization.
_TAG_RE = re.compile(r"<[^>]+>")
# Word tokens, matching pgrep_content_audit._WORD.
_WORD_RE = re.compile(r"[a-z0-9]+")
# An unescaped dollar: a "$" not immediately preceded by a backslash.
_DOLLAR_RE = re.compile(r"(?<!\\)\$")

# Phrases that promise a figure to the reader (check_figure_necessity.FIG_REF).
_FIG_REF_RE = re.compile(
    r"\b(as shown|shown (?:above|below)|shown in the (?:figure|diagram)|"
    r"in the (?:figure|diagram)|the (?:figure|diagram) (?:above|below|shows)|"
    r"figure (?:above|below)|diagram (?:above|below)|the adjacent (?:figure|diagram))\b",
    re.IGNORECASE,
)


def _strip_figure(text: str) -> str:
    return _FIGURE_DIV_RE.sub(" ", text or "")


def _strip_svg(text: str) -> str:
    return _SVG_RE.sub(" ", text or "")


def _normalize(text: str) -> str:
    """Normalized form for dedup: strip the figure div, strip tags, lowercase,
    and collapse to space-joined word tokens.

    This reproduces ``pgrep_content_audit.normalized_hash`` (which lowercases and
    keeps only ``[a-z0-9]+`` runs) with an explicit figure-div and tag strip in
    front, so the gate's duplicate decisions match the audit's.
    """
    stripped = _TAG_RE.sub(" ", _strip_figure(text or ""))
    return " ".join(_WORD_RE.findall(stripped.lower()))


def _latex_balanced(text: str) -> bool:
    """True when a field's LaTeX delimiters balance.

    Uses the same naive token counting as ``pgrep_content_audit.balanced``: equal
    counts of ``\\(``/``\\)`` and ``\\[``/``\\]``, plus an even number of
    unescaped ``$``. It is deliberately literal, so content that happens to place
    a ``\\[`` next to a real display-math ``\\[`` (for example a ``cases`` row
    break written ``\\\\[4pt]``) is reported rather than silently accepted.
    """
    t = text or ""
    return (
        t.count(r"\(") == t.count(r"\)")
        and t.count(r"\[") == t.count(r"\]")
        and len(_DOLLAR_RE.findall(t)) % 2 == 0
    )


def _key_index(key: object) -> int | None:
    """0-based index of a single-letter A-E key, or None if it is not one."""
    if isinstance(key, str) and len(key) == 1 and key in "ABCDE":
        return ord(key) - ord("A")
    return None


def _fig_snippet(text: str, width: int = 60) -> str:
    """A short context window around the figure-reference phrase in a stem."""
    match = _FIG_REF_RE.search(text or "")
    if not match:
        return (text or "")[:width]
    lo = max(0, match.start() - 20)
    return ("..." if lo else "") + text[lo : match.end() + 30].replace("\n", " ")


def _text_fields(item: dict, kind: str) -> list[tuple[str, str]]:
    """(field-label, text) pairs of the prose that carries LaTeX, per item.

    Mirrors ``pgrep_content_audit.prose_fields``: the problem stem is scanned with
    its embedded figure stripped, so figure markup never affects delimiter counts.
    """
    out: list[tuple[str, object]] = []
    if kind == "card":
        out.append(("front", item.get("front", "")))
        out.append(("back", item.get("back", "")))
    else:
        out.append(("stem", _strip_figure(item.get("stem", ""))))
        for i, choice in enumerate(item.get("choices", []) or []):
            out.append((f"choices[{i}]", choice))
        for i, d in enumerate(item.get("distractors", []) or []):
            if isinstance(d, dict):
                out.append((f"distractors[{i}].rationale", d.get("rationale", "")))
        for i, step in enumerate(item.get("solution_decomposition", []) or []):
            if isinstance(step, dict):
                out.append(
                    (f"solution_decomposition[{i}].subgoal", step.get("subgoal", ""))
                )
                out.append(
                    (f"solution_decomposition[{i}].rubric", step.get("rubric", ""))
                )
    return [(label, text) for label, text in out if isinstance(text, str) and text]


def _duplicate_ids(cards: list[dict], problems: list[dict]) -> list[str]:
    """Ids that appear more than once across cards and problems, first seen order."""
    seen: set[str] = set()
    dups: list[str] = []
    for item in list(cards) + list(problems):
        item_id = item.get("id")
        if item_id in seen and item_id not in dups:
            dups.append(item_id)
        seen.add(item_id)
    return dups


def _duplicate_text(items: list[dict], key: str) -> list[dict]:
    """Pairs of items whose normalized ``key`` field collides.

    Empty normalized text is skipped, so an empty stem is reported once by the
    empty-stem check rather than a second time as a false duplicate.
    """
    seen: dict[str, str] = {}
    dups: list[dict] = []
    for item in items:
        norm = _normalize(item.get(key, ""))
        if not norm:
            continue
        if norm in seen:
            dups.append({"first": seen[norm], "duplicate": item.get("id")})
        else:
            seen[norm] = item.get("id")
    return dups


def check_bundle(bundle: dict) -> dict:
    """Check every invariant and return a structured report.

    The report has ``schema``, a ``counts`` block (actual, metadata, and whether
    they match), a ``violations`` block mapping each invariant to the offending
    ids, and a ``summary`` of counts. ``hard_failures`` turns this into the CI
    verdict.
    """
    cards = bundle.get("cards") or []
    problems = bundle.get("problems") or []
    meta = bundle.get("counts") or {}

    bad_choice_count: list[dict] = []
    bad_correct_key: list[dict] = []
    empty_stem: list[str] = []
    missing_source_ref_problems: list[str] = []
    dangling_figure_refs: list[dict] = []
    figure_without_svg: list[str] = []
    decomp_bad_choice_count: list[dict] = []
    decomp_bad_key: list[dict] = []
    unbalanced_latex: list[dict] = []

    for p in problems:
        pid = p.get("id")

        choices = p.get("choices")
        n_choices = len(choices) if isinstance(choices, list) else 0
        if n_choices != CHOICES_EXPECTED:
            bad_choice_count.append({"id": pid, "choices": n_choices})

        idx = _key_index(p.get("correct"))
        if idx is None or not (isinstance(choices, list) and 0 <= idx < len(choices)):
            bad_correct_key.append({"id": pid, "correct": p.get("correct")})

        stem = p.get("stem")
        if not (isinstance(stem, str) and stem.strip()):
            empty_stem.append(pid)

        if not (isinstance(p.get("source_ref"), str) and p["source_ref"].strip()):
            missing_source_ref_problems.append(pid)

        raw_stem = stem if isinstance(stem, str) else ""
        has_svg = bool(_SVG_RE.search(raw_stem))
        has_pg_figure = bool(_PG_FIGURE_OPEN_RE.search(raw_stem))
        refs_figure = bool(_FIG_REF_RE.search(_strip_svg(raw_stem)))
        if refs_figure and not has_svg:
            dangling_figure_refs.append(
                {"id": pid, "snippet": _fig_snippet(_strip_svg(raw_stem))}
            )
        if has_pg_figure and not has_svg:
            figure_without_svg.append(pid)

        dt = p.get("decomposition_tutor")
        if isinstance(dt, dict):
            for si, sub in enumerate(dt.get("subproblems", []) or []):
                variants = sub.get("variants", []) if isinstance(sub, dict) else []
                for vi, var in enumerate(variants or []):
                    if not isinstance(var, dict):
                        decomp_bad_choice_count.append(
                            {"id": pid, "subproblem": si, "variant": vi, "choices": 0}
                        )
                        decomp_bad_key.append(
                            {"id": pid, "subproblem": si, "variant": vi, "key": None}
                        )
                        continue
                    vch = var.get("choices")
                    vn = len(vch) if isinstance(vch, list) else 0
                    if vn != CHOICES_EXPECTED:
                        decomp_bad_choice_count.append(
                            {"id": pid, "subproblem": si, "variant": vi, "choices": vn}
                        )
                    if var.get("key") not in VALID_KEYS:
                        decomp_bad_key.append(
                            {
                                "id": pid,
                                "subproblem": si,
                                "variant": vi,
                                "key": var.get("key"),
                            }
                        )

    for kind, items in (("card", cards), ("problem", problems)):
        for item in items:
            for field, text in _text_fields(item, kind):
                if not _latex_balanced(text):
                    unbalanced_latex.append(
                        {"id": item.get("id"), "kind": kind, "field": field}
                    )

    missing_source_ref_cards = [
        c.get("id")
        for c in cards
        if not (isinstance(c.get("source_ref"), str) and c["source_ref"].strip())
    ]

    duplicate_ids = _duplicate_ids(cards, problems)
    duplicate_stems = _duplicate_text(problems, "stem")
    duplicate_fronts = _duplicate_text(cards, "front")

    counts_actual = {
        "cards": len(cards),
        "problems": len(problems),
        "total": len(cards) + len(problems),
    }
    counts_match = (
        meta.get("cards") == counts_actual["cards"]
        and meta.get("problems") == counts_actual["problems"]
    )
    if "total" in meta:
        counts_match = counts_match and meta.get("total") == counts_actual["total"]

    violations: dict[str, list] = {
        "bad_choice_count": bad_choice_count,
        "bad_correct_key": bad_correct_key,
        "empty_stem": empty_stem,
        "missing_source_ref_problems": missing_source_ref_problems,
        "missing_source_ref_cards": missing_source_ref_cards,
        "duplicate_ids": duplicate_ids,
        "duplicate_stems": duplicate_stems,
        "duplicate_fronts": duplicate_fronts,
        "unbalanced_latex": unbalanced_latex,
        "dangling_figure_refs": dangling_figure_refs,
        "figure_without_svg": figure_without_svg,
        "decomp_bad_choice_count": decomp_bad_choice_count,
        "decomp_bad_key": decomp_bad_key,
    }
    summary = {name: len(items) for name, items in violations.items()}
    summary["counts_match"] = bool(counts_match)
    return {
        "schema": bundle.get("schema"),
        "counts": {
            "actual": counts_actual,
            "metadata": meta,
            "match": bool(counts_match),
        },
        "violations": violations,
        "summary": summary,
    }


def _fmt_ids(values: list, limit: int = 20) -> str:
    """Compact, deterministic id list for a failure message."""
    shown = [str(v) for v in values[:limit]]
    suffix = f" ... (+{len(values) - limit} more)" if len(values) > limit else ""
    return ", ".join(shown) + suffix


def hard_failures(report: dict) -> list[str]:
    """The invariants that must fail CI, as human-readable strings.

    An empty list means the bundle is shippable. Cards missing a ``source_ref``
    are reported by ``check_bundle`` but intentionally not gated here, matching the
    existing audit, which tracks card citations but hard-fails only on problems.
    """
    v = report["violations"]
    fails: list[str] = []

    if v["bad_choice_count"]:
        ids = [d["id"] for d in v["bad_choice_count"]]
        fails.append(
            f"{len(ids)} problem(s) without exactly {CHOICES_EXPECTED} choices: "
            f"{_fmt_ids(ids)}"
        )
    if v["bad_correct_key"]:
        ids = [d["id"] for d in v["bad_correct_key"]]
        fails.append(
            f"{len(ids)} problem(s) whose correct key is not a letter A-E within "
            f"choices: {_fmt_ids(ids)}"
        )
    if v["duplicate_ids"]:
        fails.append(
            f"{len(v['duplicate_ids'])} duplicate id(s) across cards and problems: "
            f"{_fmt_ids(v['duplicate_ids'])}"
        )
    if v["duplicate_stems"]:
        pairs = [f"{d['duplicate']} == {d['first']}" for d in v["duplicate_stems"]]
        fails.append(
            f"{len(pairs)} duplicate normalized problem stem(s): {_fmt_ids(pairs)}"
        )
    if v["duplicate_fronts"]:
        pairs = [f"{d['duplicate']} == {d['first']}" for d in v["duplicate_fronts"]]
        fails.append(
            f"{len(pairs)} duplicate normalized card front(s): {_fmt_ids(pairs)}"
        )
    if v["unbalanced_latex"]:
        locs = [f"{d['id']}:{d['field']}" for d in v["unbalanced_latex"]]
        fails.append(
            f"{len(locs)} field(s) with unbalanced LaTeX delimiters: {_fmt_ids(locs)}"
        )
    if v["missing_source_ref_problems"]:
        fails.append(
            f"{len(v['missing_source_ref_problems'])} problem(s) missing a "
            f"source_ref: {_fmt_ids(v['missing_source_ref_problems'])}"
        )
    if not report["counts"]["match"]:
        fails.append(
            "counts dict does not match the actual counts: "
            f"metadata={report['counts']['metadata']} "
            f"actual={report['counts']['actual']}"
        )
    if v["dangling_figure_refs"]:
        ids = [d["id"] for d in v["dangling_figure_refs"]]
        fails.append(
            f"{len(ids)} dangling figure reference(s) (stem promises a figure with "
            f"no <svg>): {_fmt_ids(ids)}"
        )

    # Extensions of the same content contract, gated for the same reasons.
    if v["empty_stem"]:
        fails.append(
            f"{len(v['empty_stem'])} problem(s) with an empty stem: "
            f"{_fmt_ids(v['empty_stem'])}"
        )
    if v["figure_without_svg"]:
        fails.append(
            f"{len(v['figure_without_svg'])} pg-figure block(s) without an <svg>: "
            f"{_fmt_ids(v['figure_without_svg'])}"
        )
    if v["decomp_bad_choice_count"]:
        locs = [
            f"{d['id']}#s{d['subproblem']}v{d['variant']}"
            for d in v["decomp_bad_choice_count"]
        ]
        fails.append(
            f"{len(locs)} decomposition variant(s) without exactly "
            f"{CHOICES_EXPECTED} choices: {_fmt_ids(locs)}"
        )
    if v["decomp_bad_key"]:
        locs = [
            f"{d['id']}#s{d['subproblem']}v{d['variant']}" for d in v["decomp_bad_key"]
        ]
        fails.append(
            f"{len(locs)} decomposition variant(s) whose key is not A-E: "
            f"{_fmt_ids(locs)}"
        )
    return fails


def format_report(report: dict) -> str:
    """A short human-readable rendering of the report and the CI verdict."""
    lines: list[str] = []
    c = report["counts"]
    lines.append("== pgrep content bundle invariants ==")
    lines.append(f"schema: {report['schema']}")
    lines.append(
        f"counts: actual={c['actual']} metadata={c['metadata']} match={c['match']}"
    )
    lines.append("")
    lines.append("violation counts:")
    for name, count in report["summary"].items():
        if name == "counts_match":
            continue
        flag = "  " if count == 0 else "!!"
        lines.append(f"  {flag} {name}: {count}")

    fails = hard_failures(report)
    lines.append("")
    lines.append("== HARD INVARIANTS ==")
    if not fails:
        lines.append("  all clear")
    else:
        for f in fails:
            lines.append(f"  FAIL: {f}")
    return "\n".join(lines)


def _default_bundle_path() -> Path:
    return Path(__file__).resolve().with_name("content_bundle.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--bundle",
        default=str(_default_bundle_path()),
        help="path to content_bundle.json (defaults to the shipped bundle)",
    )
    ap.add_argument(
        "--json", action="store_true", help="emit the machine report as JSON"
    )
    args = ap.parse_args(argv)

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    report = check_bundle(bundle)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))
    return 1 if hard_failures(report) else 0


if __name__ == "__main__":
    sys.exit(main())
