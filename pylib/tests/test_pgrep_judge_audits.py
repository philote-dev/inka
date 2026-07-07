# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the five on-demand bundle audits (no network).

The two new judge audits (independent answer-key solve, distractor plausibility)
are driven through a fake client that returns canned JSON, so nothing touches the
API. The deterministic audits (decomposition leak, citation) are exercised through
the orchestrator's pure helpers: the leak check runs the real
``verify.find_giveaway`` on a crafted leaking vs clean tutor, and the citation
resolver is checked for its graceful skip when no corpus index is present (plus a
tiny temp index to prove the light metadata read). Runs under pytest and directly
as ``python3 pylib/tests/test_pgrep_judge_audits.py``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The offline AI core imports as ``pgrep.ai.*`` with pylib/anki appended (never
# prepended: it holds stdlib-named modules); the orchestrator lives in
# content/tools next to its ``_ai_path`` helper.
_AI_CORE = REPO / "pylib" / "anki"
_TOOLS = REPO / "content" / "tools"
for _p in (_AI_CORE, _TOOLS):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.append(str(_p))

import audit_bundle_ai as audit  # type: ignore[import-not-found]  # noqa: E402
from pgrep.ai import judge  # type: ignore[import-not-found]  # noqa: E402

_DATED = "gpt-judge-2026-01-01"


# --- fakes -----------------------------------------------------------------


class _FakeClient:
    """Injected through the judge's ``client`` seam; returns one canned reply."""

    model = "fake-2026-01-01"

    def __init__(self, text: str):
        self.text = text
        self.calls: list[tuple] = []

    def complete_text(self, system, user, *, json_object=False):
        self.calls.append((system, user, json_object))
        return self.text


class _RaisingClient:
    model = "fake-2026-01-01"

    def complete_text(self, *args, **kwargs):
        raise RuntimeError("boom")


def _mcq(correct: str = "C", correct_text: str = "42.0 joules") -> dict:
    choices = ["w", "x", "y", "z", "q"]
    choices["ABCDE".index(correct)] = correct_text
    return {
        "id": "p-test-1",
        "topic": "mechanics",
        "stem": "A block slides down a smooth ramp.",
        "choices": choices,
        "correct": correct,
        "distractors": [
            {"label": "A", "misconception": "sign_slip", "rationale": "forgot a sign"},
        ],
    }


# --- 1. answer key (independent solve) -------------------------------------


def test_answer_key_agrees():
    reply = {"answer": "C", "confidence": 0.9, "reasoning": "energy conservation"}
    fake = _FakeClient(json.dumps(reply))
    v = judge.Judge(_DATED, client=fake).answer_key(_mcq(correct="C"))
    assert isinstance(v, judge.AnswerKeyVerdict)
    assert v.predicted_letter == "C"
    assert v.agrees is True
    assert v.confidence == 0.9
    assert v.to_dict() == {
        "predicted_letter": "C",
        "agrees": True,
        "confidence": 0.9,
        "reasoning": "energy conservation",
    }
    system, _user, json_object = fake.calls[0]
    assert json_object is True
    assert system == judge.ANSWER_KEY_SYSTEM


def test_answer_key_disagrees():
    fake = _FakeClient(json.dumps({"answer": "A", "confidence": 0.7, "reasoning": "x"}))
    v = judge.Judge(_DATED, client=fake).answer_key(_mcq(correct="C"))
    assert v.predicted_letter == "A"
    assert v.agrees is False


def test_answer_key_payload_is_blind_to_the_stored_key():
    fake = _FakeClient('{"answer": "A"}')
    judge.Judge(_DATED, client=fake).answer_key(_mcq(correct="C"))
    _system, user, _ = fake.calls[0]
    # The stored key is never shown to the solver (unlike the giveaway payload).
    assert "CORRECT" not in user
    assert "OPTIONS:" in user


def test_answer_key_includes_svg_when_the_stem_has_a_figure():
    fake = _FakeClient('{"answer": "B"}')
    problem = _mcq(correct="B")
    problem["stem"] = 'Before <div class="pg-figure"><svg id="f"/></div> after'
    judge.Judge(_DATED, client=fake).answer_key(problem)
    _system, user, _ = fake.calls[0]
    assert "pg-figure" not in user
    assert "FIGURE (SVG" in user
    assert '<svg id="f"/>' in user


def test_answer_key_unparseable_reply_is_inconclusive():
    fake = _FakeClient("sorry, no answer")
    v = judge.Judge(_DATED, client=fake).answer_key(_mcq(correct="C"))
    # No valid letter: the auditor treats this as inconclusive, not a disagreement.
    assert v.predicted_letter == ""
    assert v.agrees is False


def test_answer_key_client_error_is_inconclusive():
    v = judge.Judge(_DATED, client=_RaisingClient()).answer_key(_mcq(correct="C"))
    assert v.predicted_letter == ""
    assert v.agrees is False
    assert "judge call failed" in v.reasoning


# --- 4. distractor plausibility --------------------------------------------


def test_distractor_plausibility_parses_and_normalizes():
    reply = {"implausible_labels": ["b", "X", "D", "d"], "notes": "two are weak"}
    fake = _FakeClient(json.dumps(reply))
    v = judge.Judge(_DATED, client=fake).distractor_plausibility(_mcq(correct="A"))
    assert isinstance(v, judge.DistractorVerdict)
    # Normalized to uppercase, non-letters dropped, deduped, order preserved.
    assert v.implausible_labels == ["B", "D"]
    assert v.notes == "two are weak"
    assert v.to_dict() == {"implausible_labels": ["B", "D"], "notes": "two are weak"}
    system, _user, json_object = fake.calls[0]
    assert json_object is True
    assert system == judge.DISTRACTOR_SYSTEM


def test_distractor_plausibility_malformed_reply_is_safe_default():
    v = judge.Judge(_DATED, client=_FakeClient("garbage")).distractor_plausibility(
        {"stem": "s"}
    )
    assert v.implausible_labels == []


# --- 3. decomposition leak (real verify.find_giveaway) ---------------------

_LEAKING_TUTOR = {
    "subproblems": [
        {
            "prompt": "Pin the relation.",
            "variants": [
                {
                    "stem": "A frictionless bead starts from rest on a wire.",
                    "choices": ["a", "b", "c", "d", "e"],
                    "key": "B",
                    # Leaks the PARENT's answer value (42.0 joules).
                    "explain_why": "Energy conservation leaves the bead 42.0 joules.",
                    "source_ref": "OpenStax Vol 1, p. 100",
                }
            ],
        }
    ]
}

_CLEAN_TUTOR = {
    "subproblems": [
        {
            "prompt": "Pin the relation.",
            "variants": [
                {
                    "stem": "A frictionless bead starts from rest on a wire.",
                    "choices": ["a", "b", "c", "d", "e"],
                    "key": "B",
                    "explain_why": "Apply conservation of mechanical energy between the two points.",
                    "source_ref": "OpenStax Vol 1, p. 100",
                }
            ],
        }
    ]
}


def test_decomposition_leak_flags_a_leaking_variant():
    problem = _mcq(correct="C", correct_text="42.0 joules")
    problem["decomposition_tutor"] = _LEAKING_TUTOR
    findings = audit.decomposition_leaks(problem)
    assert findings, "expected the shared answer value to be caught"
    assert findings[0]["kind"] == "leak"
    assert findings[0]["field"] == "explain_why"


def test_decomposition_leak_clean_tutor_has_no_findings():
    problem = _mcq(correct="C", correct_text="42.0 joules")
    problem["decomposition_tutor"] = _CLEAN_TUTOR
    assert audit.decomposition_leaks(problem) == []


_COINCIDENTAL_TUTOR = {
    "subproblems": [
        {
            "prompt": "step",
            "variants": [
                {
                    "stem": "Setup has E=20 J, d=1.0 mm, and t=5.0 s.",
                    "choices": ["a", "b", "c", "d", "e"],
                    "key": "B",
                    "explain_why": "Compute the ratio of the two setups.",
                }
            ],
        }
    ]
}


def test_decomposition_leak_bare_number_overlap_is_weak_not_decisive():
    # A bare-numeric parent answer ("5.0%") shares its "5.0" with a "t=5.0 s"
    # datum. find_giveaway flags it, but it is a coincidence, not a leak, so it is
    # recorded as weak and does not fail the run.
    problem = _mcq(correct="C", correct_text="5.0%")
    problem["decomposition_tutor"] = _COINCIDENTAL_TUTOR
    leaks = audit.decomposition_leaks(problem)
    assert leaks and all(not leak["decisive"] for leak in leaks)
    result = audit.run_decomposition_leak([problem], None, 4, False)
    assert result.failed is False
    assert result.extra["weak_overlaps_count"] >= 1


def test_run_decomposition_leak_fails_hard_on_a_leak_and_passes_when_clean():
    leaking = _mcq(correct="C", correct_text="42.0 joules")
    leaking["decomposition_tutor"] = _LEAKING_TUTOR
    clean = _mcq(correct="C", correct_text="42.0 joules")
    clean["decomposition_tutor"] = _CLEAN_TUTOR
    # judge=None and the flag off: purely deterministic, no network.
    bad = audit.run_decomposition_leak([leaking], None, 4, False)
    assert bad.severity == audit.HARD
    assert bad.checked == 1
    assert bad.failed is True
    good = audit.run_decomposition_leak([clean], None, 4, False)
    assert good.failed is False


# --- 5. citation (graceful skip + light read) ------------------------------


def test_citation_resolver_reports_unavailable_without_an_index():
    resolver = audit.CitationResolver("/no/such/corpus.db")
    assert resolver.available is False
    assert "not available" in resolver.reason


def test_citation_audit_skips_when_no_index_is_present():
    result = audit.run_citation(
        [{"id": "p1", "source_ref": "OpenStax, p. 1"}], "/no/such/corpus.db"
    )
    assert result.skipped is True
    assert result.severity == audit.SOFT
    assert result.failed is False
    assert "not available" in result.note


def test_citation_resolves_against_a_light_temp_index():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "corpus.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE chunks (source_title TEXT, source_ref TEXT)")
    con.execute(
        "INSERT INTO chunks VALUES (?, ?)",
        (
            "OpenStax University Physics Volume 1",
            "OpenStax University Physics Volume 1, p. 337, §7.3",
        ),
    )
    con.commit()
    con.close()
    resolver = audit.CitationResolver(db)
    assert resolver.available is True
    assert resolver.resolves(
        "OpenStax University Physics Volume 1, pp. 337-338, §7.3 Work-Energy Theorem"
    )
    assert resolver.resolves("Some Unknown Book, p. 1") is False
    # Only the unresolved citation is flagged, and the audit does not skip.
    result = audit.run_citation(
        [
            {"id": "ok", "source_ref": "OpenStax University Physics Volume 1, p. 10"},
            {"id": "bad", "source_ref": "Some Unknown Book, p. 1"},
        ],
        db,
    )
    assert result.skipped is False
    assert [f["id"] for f in result.findings] == ["bad"]


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
