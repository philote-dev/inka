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
from dataclasses import dataclass, field
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

# Math delimiters, counted so an escaped line break ("\\[" or "\\(", optionally
# with a spacing arg like "\\[4pt]") is not mistaken for a math opener: a
# delimiter backslash that is itself preceded by a backslash is a LaTeX line
# break, not the start of inline or display math.
_MATH_INLINE_OPEN_RE = re.compile(r"(?<!\\)\\\(")
_MATH_INLINE_CLOSE_RE = re.compile(r"(?<!\\)\\\)")
_MATH_DISPLAY_OPEN_RE = re.compile(r"(?<!\\)\\\[")
_MATH_DISPLAY_CLOSE_RE = re.compile(r"(?<!\\)\\\]")

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
    """True when a field's LaTeX math delimiters balance.

    Counts genuine inline ``\\(``/``\\)`` and display ``\\[``/``\\]`` delimiters and
    requires an even number of unescaped ``$``. A delimiter whose backslash is
    itself preceded by a backslash is an escaped LaTeX line break, not math (for
    example a ``cases`` row break written ``\\\\[4pt]``), so it is excluded from the
    count. This is stricter than ``pgrep_content_audit.balanced``'s literal token
    count, which false-positives on such row breaks.
    """
    t = text or ""
    return (
        len(_MATH_INLINE_OPEN_RE.findall(t)) == len(_MATH_INLINE_CLOSE_RE.findall(t))
        and len(_MATH_DISPLAY_OPEN_RE.findall(t))
        == len(_MATH_DISPLAY_CLOSE_RE.findall(t))
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


@dataclass
class _DecompositionViolations:
    bad_choice_count: list[dict] = field(default_factory=list)
    bad_key: list[dict] = field(default_factory=list)


def _check_decomposition_tutor_variants(
    problem_id: object, decomposition_tutor: object
) -> _DecompositionViolations:
    violations = _DecompositionViolations()
    if not isinstance(decomposition_tutor, dict):
        return violations

    for subproblem_index, subproblem in enumerate(
        decomposition_tutor.get("subproblems", []) or []
    ):
        variants = (
            subproblem.get("variants", []) if isinstance(subproblem, dict) else []
        )
        for variant_index, variant in enumerate(variants or []):
            location = {
                "id": problem_id,
                "subproblem": subproblem_index,
                "variant": variant_index,
            }
            if not isinstance(variant, dict):
                violations.bad_choice_count.append({**location, "choices": 0})
                violations.bad_key.append({**location, "key": None})
                continue

            choices = variant.get("choices")
            choice_count = len(choices) if isinstance(choices, list) else 0
            if choice_count != CHOICES_EXPECTED:
                violations.bad_choice_count.append(
                    {**location, "choices": choice_count}
                )
            if variant.get("key") not in VALID_KEYS:
                violations.bad_key.append({**location, "key": variant.get("key")})

    return violations


@dataclass
class _ProblemViolations:
    bad_choice_count: list[dict] = field(default_factory=list)
    bad_correct_key: list[dict] = field(default_factory=list)
    empty_stem: list[str] = field(default_factory=list)
    missing_source_ref: list[str] = field(default_factory=list)
    dangling_figure_refs: list[dict] = field(default_factory=list)
    figure_without_svg: list[str] = field(default_factory=list)
    decomp_bad_choice_count: list[dict] = field(default_factory=list)
    decomp_bad_key: list[dict] = field(default_factory=list)

    def extend(self, other: _ProblemViolations) -> None:
        self.bad_choice_count.extend(other.bad_choice_count)
        self.bad_correct_key.extend(other.bad_correct_key)
        self.empty_stem.extend(other.empty_stem)
        self.missing_source_ref.extend(other.missing_source_ref)
        self.dangling_figure_refs.extend(other.dangling_figure_refs)
        self.figure_without_svg.extend(other.figure_without_svg)
        self.decomp_bad_choice_count.extend(other.decomp_bad_choice_count)
        self.decomp_bad_key.extend(other.decomp_bad_key)


def _check_problem(problem: dict) -> _ProblemViolations:
    violations = _ProblemViolations()
    problem_id = problem.get("id")

    choices = problem.get("choices")
    choice_count = len(choices) if isinstance(choices, list) else 0
    if choice_count != CHOICES_EXPECTED:
        violations.bad_choice_count.append({"id": problem_id, "choices": choice_count})

    correct_index = _key_index(problem.get("correct"))
    if correct_index is None or not (
        isinstance(choices, list) and 0 <= correct_index < len(choices)
    ):
        violations.bad_correct_key.append(
            {"id": problem_id, "correct": problem.get("correct")}
        )

    stem = problem.get("stem")
    if not (isinstance(stem, str) and stem.strip()):
        violations.empty_stem.append(problem_id)

    source_ref = problem.get("source_ref")
    if not (isinstance(source_ref, str) and source_ref.strip()):
        violations.missing_source_ref.append(problem_id)

    raw_stem = stem if isinstance(stem, str) else ""
    has_svg = bool(_SVG_RE.search(raw_stem))
    has_pg_figure = bool(_PG_FIGURE_OPEN_RE.search(raw_stem))
    stem_without_svg = _strip_svg(raw_stem)
    if _FIG_REF_RE.search(stem_without_svg) and not has_svg:
        violations.dangling_figure_refs.append(
            {"id": problem_id, "snippet": _fig_snippet(stem_without_svg)}
        )
    if has_pg_figure and not has_svg:
        violations.figure_without_svg.append(problem_id)

    decomposition = _check_decomposition_tutor_variants(
        problem_id, problem.get("decomposition_tutor")
    )
    violations.decomp_bad_choice_count.extend(decomposition.bad_choice_count)
    violations.decomp_bad_key.extend(decomposition.bad_key)
    return violations


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

    problem_violations = _ProblemViolations()
    unbalanced_latex: list[dict] = []

    for problem in problems:
        problem_violations.extend(_check_problem(problem))

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
        "bad_choice_count": problem_violations.bad_choice_count,
        "bad_correct_key": problem_violations.bad_correct_key,
        "empty_stem": problem_violations.empty_stem,
        "missing_source_ref_problems": problem_violations.missing_source_ref,
        "missing_source_ref_cards": missing_source_ref_cards,
        "duplicate_ids": duplicate_ids,
        "duplicate_stems": duplicate_stems,
        "duplicate_fronts": duplicate_fronts,
        "unbalanced_latex": unbalanced_latex,
        "dangling_figure_refs": problem_violations.dangling_figure_refs,
        "figure_without_svg": problem_violations.figure_without_svg,
        "decomp_bad_choice_count": problem_violations.decomp_bad_choice_count,
        "decomp_bad_key": problem_violations.decomp_bad_key,
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
