# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Tests for the pgrep content-bundle invariants (the CI content gate).

Two layers:

- ``test_shipped_bundle_passes_hard_invariants`` loads the real
  ``pylib/anki/pgrep/content_bundle.json`` and asserts it has no hard failures.
  This is the gate that runs under ``just test-py``. If the shipped bundle
  regresses (or already violates an invariant), this test fails and names the
  offending ids, and the fix belongs in the bundle, not in the check.
- focused unit tests build tiny in-memory bundles: a clean bundle passes, and one
  deliberately broken bundle per invariant fails with the expected message.

Runnable two ways: under pytest (``just test-py``) and as a plain script
(``python3 pylib/tests/test_pgrep_content_invariants.py``) for offline checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from anki.pgrep import content_invariants as ci
except ModuleNotFoundError:  # allow `python3 pylib/tests/...` without a full build
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from anki.pgrep import content_invariants as ci

BUNDLE_PATH = Path(ci.__file__).resolve().with_name("content_bundle.json")

_SVG = '<svg viewBox="0 0 10 10" stroke="currentColor"></svg>'


def _card(**over: object) -> dict:
    base: dict[str, object] = {
        "id": "c-1",
        "topic": "topic::mechanics::energy",
        "kind": "conceptual",
        "front": "What is kinetic energy?",
        "back": r"Kinetic energy is \(K = \tfrac{1}{2}mv^2\).",
        "source_ref": "OpenStax University Physics Volume 1, p. 100",
    }
    base.update(over)
    return base


def _problem(**over: object) -> dict:
    base: dict[str, object] = {
        "id": "p-1",
        "topic": "topic::mechanics::energy",
        "kind": "computational",
        "stem": r"A block of mass \(m\) moves at speed \(v\).",
        "choices": ["A0", "B0", "C0", "D0", "E0"],
        "correct": "A",
        "distractors": [],
        "solution_decomposition": [],
        "difficulty": 0.4,
        "source_ref": "OpenStax University Physics Volume 1, p. 101",
    }
    base.update(over)
    return base


def _bundle(cards: list[dict], problems: list[dict]) -> dict:
    return {
        "schema": "pgrep-content-bundle/v1",
        "provenance": {},
        "counts": {
            "cards": len(cards),
            "problems": len(problems),
            "total": len(cards) + len(problems),
        },
        "cards": cards,
        "problems": problems,
    }


def _good_bundle() -> dict:
    p1 = _problem(id="p-1", stem=r"A block of mass \(m\) moves at speed \(v\).")
    p2 = _problem(
        id="p-2",
        correct="B",
        stem=r"A spring of constant \(k\) is compressed by \(x\).",
    )
    return _bundle([_card()], [p1, p2])


# --- the CI gate over the shipped bundle -----------------------------------


def test_shipped_bundle_passes_hard_invariants() -> None:
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    report = ci.check_bundle(bundle)
    fails = ci.hard_failures(report)
    assert fails == [], "shipped content_bundle.json has hard failures:\n" + "\n".join(
        fails
    )


# --- a clean in-memory bundle passes everything ----------------------------


def test_good_bundle_passes() -> None:
    assert ci.hard_failures(ci.check_bundle(_good_bundle())) == []


# --- one broken invariant per test -----------------------------------------


def test_four_choices_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["choices"] = ["A0", "B0", "C0", "D0"]
    report = ci.check_bundle(b)
    assert [d["id"] for d in report["violations"]["bad_choice_count"]] == ["p-1"]
    assert any(
        "without exactly 5 choices" in f and "p-1" in f
        for f in ci.hard_failures(report)
    )


def test_bad_correct_key_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["correct"] = "F"
    report = ci.check_bundle(b)
    assert [d["id"] for d in report["violations"]["bad_correct_key"]] == ["p-1"]
    assert any("correct key is not a letter A-E" in f for f in ci.hard_failures(report))


def test_correct_key_out_of_range_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["choices"] = ["A0", "B0", "C0"]
    b["problems"][0]["correct"] = "E"  # a valid letter, but no 5th choice
    report = ci.check_bundle(b)
    assert [d["id"] for d in report["violations"]["bad_correct_key"]] == ["p-1"]


def test_duplicate_id_fails() -> None:
    b = _good_bundle()
    b["problems"].append(
        _problem(id="p-1", stem="A lens forms a real image on a screen.")
    )
    b["counts"]["problems"] = 3
    b["counts"]["total"] = 4
    report = ci.check_bundle(b)
    assert report["violations"]["duplicate_ids"] == ["p-1"]
    assert any("duplicate id" in f for f in ci.hard_failures(report))


def test_duplicate_stem_fails() -> None:
    b = _good_bundle()
    # p-2 normalizes to p-1's stem: only case, spacing, and a tag differ.
    b["problems"][1]["stem"] = "<b>" + b["problems"][0]["stem"].upper() + "</b>     "
    report = ci.check_bundle(b)
    dups = report["violations"]["duplicate_stems"]
    assert dups and dups[0]["duplicate"] == "p-2" and dups[0]["first"] == "p-1"
    assert any(
        "duplicate normalized problem stem" in f for f in ci.hard_failures(report)
    )


def test_duplicate_front_fails() -> None:
    b = _good_bundle()
    b["cards"].append(_card(id="c-2", front=b["cards"][0]["front"].upper()))
    b["counts"]["cards"] = 2
    b["counts"]["total"] = 4
    report = ci.check_bundle(b)
    dups = report["violations"]["duplicate_fronts"]
    assert dups and dups[0]["duplicate"] == "c-2"
    assert any("duplicate normalized card front" in f for f in ci.hard_failures(report))


def test_unbalanced_latex_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["stem"] = r"A stray delimiter \( x = 1 with no close."
    report = ci.check_bundle(b)
    locs = [(d["id"], d["field"]) for d in report["violations"]["unbalanced_latex"]]
    assert ("p-1", "stem") in locs
    assert any("unbalanced LaTeX" in f for f in ci.hard_failures(report))


def test_cases_row_break_reads_as_unbalanced() -> None:
    # A display equation whose cases row break is written \\[4pt] places a "\["
    # next to the real display-math "\[", so the literal delimiter count is odd.
    # This mirrors the shipped p4-prob-0258 finding: the check reports it rather
    # than silently accepting it.
    b = _good_bundle()
    b["problems"][0]["stem"] = (
        r"\[ f(x)=\begin{cases} 1, & x>0,\\[4pt] 0, & x<0. \end{cases} \]"
    )
    report = ci.check_bundle(b)
    assert any(
        d["id"] == "p-1" and d["field"] == "stem"
        for d in report["violations"]["unbalanced_latex"]
    )


def test_odd_unescaped_dollar_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["stem"] = "An energy $E = mc^2 with one dollar."
    report = ci.check_bundle(b)
    assert any(
        d["id"] == "p-1" and d["field"] == "stem"
        for d in report["violations"]["unbalanced_latex"]
    )


def test_even_unescaped_dollar_passes() -> None:
    b = _good_bundle()
    b["problems"][0]["stem"] = "An energy $E = mc^2$ is defined."
    assert ci.hard_failures(ci.check_bundle(b)) == []


def test_escaped_dollars_are_ignored() -> None:
    b = _good_bundle()
    b["problems"][0]["stem"] = r"It costs \$5, about \$5 in total."
    assert ci.hard_failures(ci.check_bundle(b)) == []


def test_missing_source_ref_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["source_ref"] = ""
    report = ci.check_bundle(b)
    assert report["violations"]["missing_source_ref_problems"] == ["p-1"]
    assert any("missing a source_ref" in f for f in ci.hard_failures(report))


def test_empty_stem_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["stem"] = "   "
    report = ci.check_bundle(b)
    assert report["violations"]["empty_stem"] == ["p-1"]
    assert any("empty stem" in f for f in ci.hard_failures(report))


def test_counts_mismatch_fails() -> None:
    b = _good_bundle()
    b["counts"]["problems"] = 99
    report = ci.check_bundle(b)
    assert report["counts"]["match"] is False
    assert any("counts dict does not match" in f for f in ci.hard_failures(report))


def test_dangling_figure_ref_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["stem"] = "As shown in the figure, a ray strikes a mirror."
    report = ci.check_bundle(b)
    assert [d["id"] for d in report["violations"]["dangling_figure_refs"]] == ["p-1"]
    assert any("dangling figure reference" in f for f in ci.hard_failures(report))


def test_figure_reference_with_svg_passes() -> None:
    b = _good_bundle()
    b["problems"][0]["stem"] = (
        "As shown in the figure, a ray strikes a mirror.\n"
        f'<div class="pg-figure">{_SVG}</div>'
    )
    report = ci.check_bundle(b)
    assert report["violations"]["dangling_figure_refs"] == []
    assert ci.hard_failures(report) == []


def test_pg_figure_without_svg_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["stem"] = (
        'A self-contained kinematics problem.\n<div class="pg-figure">no svg here</div>'
    )
    report = ci.check_bundle(b)
    assert report["violations"]["figure_without_svg"] == ["p-1"]
    assert any("pg-figure block" in f for f in ci.hard_failures(report))


def test_decomposition_variant_bad_choices_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["decomposition_tutor"] = {
        "subproblems": [
            {
                "prompt": "step",
                "variants": [
                    {"stem": "v", "choices": ["a", "b", "c", "d"], "key": "A"}
                ],
            }
        ],
    }
    report = ci.check_bundle(b)
    bad = report["violations"]["decomp_bad_choice_count"]
    assert bad and bad[0]["id"] == "p-1"
    assert any(
        "decomposition variant" in f and "choices" in f
        for f in ci.hard_failures(report)
    )


def test_decomposition_variant_bad_key_fails() -> None:
    b = _good_bundle()
    b["problems"][0]["decomposition_tutor"] = {
        "subproblems": [
            {
                "prompt": "step",
                "variants": [
                    {"stem": "v", "choices": ["a", "b", "c", "d", "e"], "key": "Q"}
                ],
            }
        ],
    }
    report = ci.check_bundle(b)
    bad = report["violations"]["decomp_bad_key"]
    assert bad and bad[0]["key"] == "Q"
    assert any("key is not A-E" in f for f in ci.hard_failures(report))


def test_good_decomposition_passes() -> None:
    b = _good_bundle()
    b["problems"][0]["decomposition_tutor"] = {
        "subproblems": [
            {
                "prompt": "step",
                "variants": [
                    {
                        "stem": r"Find \(v\).",
                        "choices": ["a", "b", "c", "d", "e"],
                        "key": "C",
                    }
                ],
            }
        ],
        "parent_variants": [],
    }
    assert ci.hard_failures(ci.check_bundle(b)) == []


def test_cards_missing_source_ref_reported_not_gated() -> None:
    # Card citations are tracked but not a hard failure, matching the existing
    # audit. A card with no source_ref shows up in the report yet does not gate.
    b = _good_bundle()
    b["cards"][0]["source_ref"] = ""
    report = ci.check_bundle(b)
    assert report["violations"]["missing_source_ref_cards"] == ["c-1"]
    assert ci.hard_failures(report) == []


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001 - report and continue the sweep
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
