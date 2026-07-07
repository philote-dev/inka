#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Run the five on-demand AI content audits over the shipped bundle.

This is a pre-release / nightly scan of ``content_bundle.json``, not a per-commit
gate. Every audit rides the shared ``pgrep.ai.judge`` seam (a real judge in
production, a fake in tests), so nothing here is bespoke:

  1. answer_key (LLM, HARD)   - independently solve each problem, blind to the
     stored key, and flag disagreements.
  2. figure_fidelity (LLM, HARD) - for every problem whose stem carries a
     ``pg-figure``, judge whether the SVG faithfully depicts the (figure-stripped)
     stem, and flag mismatches.
  3. decomposition_leak (deterministic, HARD) - for every decomposition tutor,
     run the shipped giveaway verifier on each subproblem variant's stem and
     explanation against the PARENT's correct answer text. ``--include-variant-
     solve`` adds a bounded LLM re-solve of each variant to confirm its own key.
  4. distractor_plausibility (LLM, SOFT) - flag wrong options that are obviously
     wrong (free to eliminate). Reported, never fails the run.
  5. citation (deterministic, SOFT) - check each ``source_ref`` resolves against
     the private corpus index metadata. When the index is absent the audit SKIPS
     with a clear note (not a failure).

HARD audits (answer_key, figure_fidelity, decomposition_leak) make the run exit
nonzero when they find something; SOFT audits (distractor_plausibility, citation)
only report. Writes a JSON report and a Markdown summary under ``--out``. Read-only
over the bundle. Run from the worktree root:

    python content/tools/audit_bundle_ai.py --workers 8
    python content/tools/audit_bundle_ai.py --only answer_key figure_fidelity
    python content/tools/audit_bundle_ai.py --only decomposition_leak citation
    python content/tools/audit_bundle_ai.py --ids p4-prob-0044 --limit 5
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import judge as ai_judge  # type: ignore[import-not-found]  # noqa: E402
from pgrep.ai import llm, verify  # type: ignore[import-not-found]  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BUNDLE = os.path.join(REPO, "pylib", "anki", "pgrep", "content_bundle.json")
DEFAULT_OUT = os.path.join("content", "run", "audit")
DEFAULT_MODEL = "gpt-5.5-2026-04-23"

HARD = "hard"
SOFT = "soft"
ALL_AUDITS = (
    "answer_key",
    "figure_fidelity",
    "decomposition_leak",
    "distractor_plausibility",
    "citation",
)
LLM_AUDITS = {"answer_key", "figure_fidelity", "distractor_plausibility"}
SEVERITY = {
    "answer_key": HARD,
    "figure_fidelity": HARD,
    "decomposition_leak": HARD,
    "distractor_plausibility": SOFT,
    "citation": SOFT,
}

_LETTERS = "ABCDE"
_FIG_DIV = re.compile(r'<div class="pg-figure">[\s\S]*?</div>')
_FIG_SVG = re.compile(r'<div class="pg-figure">([\s\S]*?)</div>')
_print_lock = threading.Lock()


# --- helpers ---------------------------------------------------------------


def _strip_figure(stem: str) -> str:
    return _FIG_DIV.sub(" ", stem or "").strip()


def _extract_svg(stem: str) -> str:
    m = _FIG_SVG.search(stem or "")
    return m.group(1).strip() if m else ""


def _correct_text(problem: dict) -> str:
    """The text of the parent's correct choice, or "" when it cannot be resolved."""
    choices = problem.get("choices", []) or []
    letter = str(problem.get("correct", "")).strip().upper()[:1]
    if letter in _LETTERS and _LETTERS.index(letter) < len(choices):
        return str(choices[_LETTERS.index(letter)])
    return ""


@dataclass
class AuditResult:
    name: str
    severity: str
    checked: int
    findings: list[dict] = field(default_factory=list)
    skipped: bool = False
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        """A HARD audit that ran and found something fails the run."""
        return self.severity == HARD and not self.skipped and bool(self.findings)


def _parallel(
    work: Callable[[dict], Any], items: list, workers: int, label: str
) -> list:
    """Map ``work`` over ``items`` with a thread pool, logging progress."""
    total = len(items)
    if total == 0:
        return []
    done = {"n": 0}

    def wrapped(item: dict) -> Any:
        result = work(item)
        with _print_lock:
            done["n"] += 1
            if done["n"] % 25 == 0 or done["n"] == total:
                print(f"  [{label}] {done['n']}/{total}", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(wrapped, items))


# --- 1. answer key ---------------------------------------------------------


def run_answer_key(problems: list, judge: Any, workers: int) -> AuditResult:
    pairs = _parallel(
        lambda p: (p, judge.answer_key(p)), problems, workers, "answer_key"
    )
    findings: list[dict] = []
    inconclusive: list[dict] = []
    for p, verdict in pairs:
        rec = {
            "id": p.get("id", ""),
            "topic": p.get("topic", ""),
            "stored": str(p.get("correct", "")),
            **verdict.to_dict(),
        }
        if not verdict.predicted_letter:
            inconclusive.append(rec)
        elif not verdict.agrees:
            findings.append(rec)
    return AuditResult(
        "answer_key",
        HARD,
        len(problems),
        findings,
        note=(
            f"{len(inconclusive)} inconclusive (no confident solve; "
            "reported, not failed)"
        ),
        extra={"inconclusive": inconclusive},
    )


# --- 2. figure fidelity ----------------------------------------------------


def run_figure_fidelity(problems: list, judge: Any, workers: int) -> AuditResult:
    targets = [p for p in problems if _extract_svg(p.get("stem", ""))]

    def work(p: dict) -> tuple:
        stem = _strip_figure(p.get("stem", ""))
        return p, judge.figure_fidelity(stem, _extract_svg(p.get("stem", "")))

    findings = []
    for p, verdict in _parallel(work, targets, workers, "figure_fidelity"):
        if not verdict.matches:
            findings.append(
                {
                    "id": p.get("id", ""),
                    "topic": p.get("topic", ""),
                    **verdict.to_dict(),
                }
            )
    return AuditResult(
        "figure_fidelity",
        HARD,
        len(targets),
        findings,
        note=f"{len(targets)} of {len(problems)} problems carry a figure",
    )


# --- 3. decomposition leak -------------------------------------------------


def _decisive_leak(reason: str, text: str, answer: str) -> bool:
    """Whether a ``find_giveaway`` hit is a reliable cross-problem leak.

    Only two signals hold up when a numeric subproblem is checked against a short
    symbolic PARENT answer: the parent answer expression appearing verbatim, or a
    reveal phrase / key-letter naming. A shared-number overlap is not reliable
    here (a sub-step's given quantities routinely coincide with an answer's
    coefficients or denominators, e.g. the 6 in a "1/6" answer vs a "6 m/s"
    datum), so those are reported as weak overlaps and never fail the run.
    """
    ans = verify.normalize(answer)
    # A verbatim match only counts when the answer is a real symbolic expression
    # (has letters: a variable or unit). A bare numeric answer like "5.0%" collapses
    # to the digits "5 0", which appear in any "5.0 s" datum, so it is not verbatim.
    has_symbol = any(c.isalpha() for c in ans)
    if has_symbol and len(ans) >= 4 and ans in verify.normalize(text):
        return True
    return not reason.startswith("hint states the answer value")


def decomposition_leaks(problem: dict) -> list[dict]:
    """Deterministic leak check: does any variant reveal the PARENT's answer?

    Runs the shipped ``verify.find_giveaway`` on every subproblem variant's
    ``stem`` and ``explain_why`` against the parent problem's correct answer text
    and returns every hit. Each carries a ``decisive`` flag; only decisive hits
    fail the run (see ``_decisive_leak``), the rest are reported as weak overlaps.
    """
    tutor = problem.get("decomposition_tutor")
    if not isinstance(tutor, dict):
        return []
    correct_text = _correct_text(problem)
    parent_key = str(problem.get("correct", "")).strip().upper()[:1]
    out: list[dict] = []
    for si, sub in enumerate(tutor.get("subproblems", []) or []):
        if not isinstance(sub, dict):
            continue
        for vi, var in enumerate(sub.get("variants", []) or []):
            if not isinstance(var, dict):
                continue
            for fld in ("stem", "explain_why"):
                text = str(var.get(fld, "") or "")
                if not text:
                    continue
                reason = verify.find_giveaway(
                    text, correct_text, choice_label=parent_key
                )
                if reason:
                    out.append(
                        {
                            "id": problem.get("id", ""),
                            "subproblem": si,
                            "variant": vi,
                            "field": fld,
                            "reason": reason,
                            "kind": "leak",
                            "decisive": _decisive_leak(reason, text, correct_text),
                        }
                    )
    return out


def _variant_solve_disagreements(
    problems: list, judge: Any, workers: int
) -> list[dict]:
    """Bounded LLM re-solve of each variant, confirming its own stated key."""
    variants = []
    for p in problems:
        tutor = p.get("decomposition_tutor") or {}
        for si, sub in enumerate(tutor.get("subproblems", []) or []):
            if not isinstance(sub, dict):
                continue
            for vi, var in enumerate(sub.get("variants", []) or []):
                if (
                    isinstance(var, dict)
                    and len(var.get("choices", []) or []) == 5
                    and var.get("key")
                ):
                    variants.append((p, si, vi, var))

    def work(item: tuple) -> tuple:
        p, si, vi, var = item
        pseudo = {
            "stem": var.get("stem", ""),
            "choices": var.get("choices", []),
            "correct": var.get("key", ""),
        }
        return item, judge.answer_key(pseudo)

    out = []
    for (p, si, vi, var), verdict in _parallel(
        work, variants, workers, "variant_solve"
    ):
        if verdict.predicted_letter and not verdict.agrees:
            out.append(
                {
                    "id": p.get("id", ""),
                    "subproblem": si,
                    "variant": vi,
                    "stated_key": str(var.get("key", "")),
                    "predicted_letter": verdict.predicted_letter,
                    "confidence": verdict.confidence,
                    "reasoning": verdict.reasoning,
                    "kind": "variant_key",
                }
            )
    return out


def run_decomposition_leak(
    problems: list, judge: Any, workers: int, include_variant_solve: bool
) -> AuditResult:
    targets = [p for p in problems if isinstance(p.get("decomposition_tutor"), dict)]
    findings: list[dict] = []
    weak: list[dict] = []
    for p in targets:
        for leak in decomposition_leaks(p):
            (findings if leak["decisive"] else weak).append(leak)
    extra: dict = {
        "weak_overlaps_count": len(weak),
        "weak_overlaps_sample": weak[:50],
    }
    note = (
        f"{len(targets)} tutors; {len(weak)} weak number-overlaps reported "
        "(coincidental shared numbers, not failed)"
    )
    if include_variant_solve and judge is not None:
        disagreements = _variant_solve_disagreements(targets, judge, workers)
        findings.extend(disagreements)
        extra["variant_solve"] = {"disagreements": len(disagreements)}
    else:
        note += "; variant re-solve off (use --include-variant-solve)"
    return AuditResult(
        "decomposition_leak", HARD, len(targets), findings, note=note, extra=extra
    )


# --- 4. distractor plausibility --------------------------------------------


def run_distractor_plausibility(
    problems: list, judge: Any, workers: int
) -> AuditResult:
    def work(p: dict) -> tuple:
        return p, judge.distractor_plausibility(p)

    findings = []
    for p, verdict in _parallel(work, problems, workers, "distractor_plausibility"):
        if verdict.implausible_labels:
            findings.append(
                {
                    "id": p.get("id", ""),
                    "topic": p.get("topic", ""),
                    **verdict.to_dict(),
                }
            )
    return AuditResult(
        "distractor_plausibility",
        SOFT,
        len(problems),
        findings,
        note="soft: reports weak distractors, does not fail the run",
    )


# --- 5. citation -----------------------------------------------------------


def _book_of(source_ref: str) -> str:
    """The book/source portion of a ``source_ref`` (the text before the pages)."""
    if not source_ref:
        return ""
    return source_ref.split(",", 1)[0].strip()


def _index_candidates() -> list[str]:
    cands = [
        os.path.join(os.getcwd(), "content", "index", "corpus.db"),
        os.path.join(REPO, "content", "index", "corpus.db"),
    ]
    # Reuse query_index's notion of the path when it imports cleanly (its heavy
    # embedding deps may be absent, so guard the import).
    try:
        import query_index  # type: ignore[import-not-found]

        cands.append(query_index.DB_PATH)
    except Exception:  # noqa: BLE001
        pass
    return cands


class CitationResolver:
    """Best-effort check that a ``source_ref`` book appears in the corpus index.

    An explicit ``index_path`` is used verbatim (and only that path). With no
    path, common locations are probed. When no readable index is found the
    resolver is ``unavailable`` and the audit skips rather than fails. Matching is
    deliberately loose (normalized book title present in an index title or ref),
    since the bundle's ``source_ref`` formatting need not match the index's.
    """

    def __init__(self, index_path: str | None = None) -> None:
        self.reason = ""
        self._haystack: list[str] = []
        if index_path is not None:
            self.path: str | None = index_path if os.path.isfile(index_path) else None
        else:
            self.path = next(
                (c for c in _index_candidates() if os.path.isfile(c)), None
            )
        self.available = self.path is not None
        if not self.available:
            self.reason = "corpus index not available"
            return
        try:
            self._load()
        except Exception as e:  # noqa: BLE001
            self.available = False
            self.reason = f"corpus index present but unreadable: {e}"

    def _load(self) -> None:
        con = sqlite3.connect(str(self.path))
        try:
            rows = con.execute(
                "SELECT DISTINCT source_title, source_ref FROM chunks"
            ).fetchall()
        finally:
            con.close()
        for title, ref in rows:
            if title:
                self._haystack.append(verify.normalize(str(title)))
            if ref:
                self._haystack.append(verify.normalize(str(ref)))

    def resolves(self, source_ref: str) -> bool:
        book = verify.normalize(_book_of(source_ref))
        if not book:
            return True  # nothing parseable to check; do not flag
        return any(book in hay for hay in self._haystack)


def run_citation(problems: list, index_path: str | None) -> AuditResult:
    resolver = CitationResolver(index_path)
    if not resolver.available:
        return AuditResult(
            "citation",
            SOFT,
            0,
            [],
            skipped=True,
            note=resolver.reason or "corpus index not available",
        )
    findings = []
    for p in problems:
        ref = str(p.get("source_ref", "") or "")
        if not resolver.resolves(ref):
            findings.append(
                {"id": p.get("id", ""), "source_ref": ref, "book": _book_of(ref)}
            )
    return AuditResult(
        "citation",
        SOFT,
        len(problems),
        findings,
        note=f"resolved against {resolver.path}",
    )


# --- orchestration ---------------------------------------------------------


def _select_audits(only: list | None) -> list[str]:
    if not only:
        return list(ALL_AUDITS)
    names: list[str] = []
    for tok in only:
        names.extend(t for t in tok.replace(",", " ").split() if t)
    unknown = [n for n in names if n not in ALL_AUDITS]
    if unknown:
        raise SystemExit(
            f"unknown audit(s): {', '.join(unknown)}; "
            f"choose from {', '.join(ALL_AUDITS)}"
        )
    chosen = set(names)
    return [n for n in ALL_AUDITS if n in chosen]


def _load_problems(bundle_path: str, ids: list | None, limit: int) -> list:
    with open(bundle_path, encoding="utf-8") as fh:
        bundle = json.load(fh)
    problems = bundle.get("problems", [])
    if ids:
        idset = set(ids)
        problems = [p for p in problems if p.get("id") in idset]
    if limit and limit > 0:
        problems = problems[:limit]
    return problems


def _dispatch(
    name: str, problems: list, judge: Any, args: argparse.Namespace
) -> AuditResult:
    if name == "answer_key":
        return run_answer_key(problems, judge, args.workers)
    if name == "figure_fidelity":
        return run_figure_fidelity(problems, judge, args.workers)
    if name == "decomposition_leak":
        return run_decomposition_leak(
            problems, judge, args.workers, args.include_variant_solve
        )
    if name == "distractor_plausibility":
        return run_distractor_plausibility(problems, judge, args.workers)
    if name == "citation":
        return run_citation(problems, args.index)
    raise SystemExit(f"unknown audit: {name}")


def _finding_line(name: str, f: dict) -> str:
    pid = f.get("id", "")
    if name == "answer_key":
        return (
            f"`{pid}` stored {f.get('stored')} vs solved "
            f"{f.get('predicted_letter')} (conf {f.get('confidence')}): "
            f"{f.get('reasoning', '')}"
        )
    if name == "figure_fidelity":
        bits = []
        if f.get("missing"):
            bits.append("missing: " + ", ".join(f["missing"]))
        if f.get("contradictions"):
            bits.append("contradictions: " + ", ".join(f["contradictions"]))
        if f.get("has_numbers"):
            bits.append("figure carries numbers")
        if f.get("notes"):
            bits.append(str(f["notes"]))
        return f"`{pid}` " + " | ".join(bits)
    if name == "decomposition_leak":
        if f.get("kind") == "variant_key":
            return (
                f"`{pid}` sub {f.get('subproblem')} var {f.get('variant')} "
                f"stated {f.get('stated_key')} vs solved {f.get('predicted_letter')}"
            )
        return (
            f"`{pid}` sub {f.get('subproblem')} var {f.get('variant')} "
            f"[{f.get('field')}]: {f.get('reason')}"
        )
    if name == "distractor_plausibility":
        labels = ", ".join(f.get("implausible_labels", []))
        return f"`{pid}` weak options {labels}: {f.get('notes', '')}"
    if name == "citation":
        return f"`{pid}` unresolved source_ref: {f.get('source_ref', '')}"
    return f"`{pid}`"


def _audit_md_section(r: AuditResult) -> list[str]:
    lines = [f"## {r.name} ({r.severity})", "", r.note or "", ""]
    if r.skipped:
        return lines + ["_skipped._", ""]
    if not r.findings:
        return lines + ["No findings.", ""]
    lines.append(f"{len(r.findings)} finding(s):")
    lines.append("")
    for f in r.findings[:200]:
        lines.append(f"- {_finding_line(r.name, f)}")
    if len(r.findings) > 200:
        lines.append(f"- ... and {len(r.findings) - 200} more (see audit_report.json)")
    lines.append("")
    return lines


def _markdown(report: dict, results: list) -> str:
    hard_fail = report["hard_failed"]
    verdict = "FAIL" if hard_fail else "PASS"
    header = f" (hard: {', '.join(hard_fail)})" if hard_fail else ""
    lines = [
        "# Bundle AI audit",
        "",
        f"- generated: {report['generated_at']}",
        f"- bundle: `{report['bundle']}`",
        f"- model: `{report['model']}`",
        f"- problems checked: {report['problems_checked']}",
        f"- variant re-solve: {report['include_variant_solve']}",
        "",
        f"**Result: {verdict}**{header}",
        "",
        "| audit | severity | checked | findings | status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        status = "skipped" if r.skipped else ("FAIL" if r.failed else "ok")
        lines.append(
            f"| {r.name} | {r.severity} | {r.checked} | {len(r.findings)} | {status} |"
        )
    lines.append("")
    for r in results:
        lines.extend(_audit_md_section(r))
    return "\n".join(lines) + "\n"


def _build_report(
    results: list, args: argparse.Namespace, problems: list, judge: Any
) -> dict:
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "bundle": args.bundle,
        "model": getattr(judge, "model", None),
        "problems_checked": len(problems),
        "include_variant_solve": args.include_variant_solve,
        "hard_failed": [r.name for r in results if r.failed],
        "audits": [
            {
                "name": r.name,
                "severity": r.severity,
                "checked": r.checked,
                "skipped": r.skipped,
                "failed": r.failed,
                "note": r.note,
                "findings_count": len(r.findings),
                "findings": r.findings,
                "extra": r.extra,
            }
            for r in results
        ],
    }


def _write_report(report: dict, results: list, out_dir: str) -> tuple[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "audit_report.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    md_path = os.path.join(out_dir, "audit_summary.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(_markdown(report, results))
    return json_path, md_path


def _print_summary(results: list, out_dir: str) -> None:
    print("\n==== audit summary ====")
    for r in results:
        status = "SKIP" if r.skipped else ("FAIL" if r.failed else "ok")
        print(
            f"  {r.name:24} {r.severity:4} checked={r.checked:5} "
            f"findings={len(r.findings):4} [{status}]"
        )
    hard_fail = [r.name for r in results if r.failed]
    print(f"\nreport:  {os.path.join(out_dir, 'audit_report.json')}")
    print(f"summary: {os.path.join(out_dir, 'audit_summary.md')}")
    if hard_fail:
        print(f"HARD audits with findings: {', '.join(hard_fail)} -> exit 1")
    else:
        print("no hard findings -> exit 0")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--only", nargs="*", default=None, help="subset of audits (default all)"
    )
    ap.add_argument("--ids", nargs="*", default=None, help="restrict to problem ids")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--limit", type=int, default=0, help="smoke: only the first N problems"
    )
    ap.add_argument("--bundle", default=DEFAULT_BUNDLE)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--env-file", default=None)
    ap.add_argument(
        "--index", default=None, help="path to corpus.db for the citation audit"
    )
    ap.add_argument(
        "--include-variant-solve",
        action="store_true",
        help="also LLM re-solve each decomposition variant to confirm its key",
    )
    args = ap.parse_args()

    selected = _select_audits(args.only)
    problems = _load_problems(args.bundle, args.ids, args.limit)
    print(f"auditing {len(problems)} problem(s): {', '.join(selected)}")

    judge = None
    need_llm = bool(LLM_AUDITS & set(selected)) or (
        "decomposition_leak" in selected and args.include_variant_solve
    )
    if need_llm:
        llm.load_api_key(args.env_file)
        if not llm.has_api_key():
            print(
                "error: an LLM audit was selected but no OPENAI_API_KEY was found "
                "(export it or add it to content/.env, or run only the "
                "deterministic audits: decomposition_leak, citation)",
                file=sys.stderr,
            )
            return 2
        judge = ai_judge.Judge(args.model, client=llm.judge_client(args.model))
        print(f"judge model: {judge.model}")

    results = []
    for name in selected:
        print(f"\n== {name} ({SEVERITY[name]}) ==")
        results.append(_dispatch(name, problems, judge, args))

    report = _build_report(results, args, problems, judge)
    _write_report(report, results, args.out)
    _print_summary(results, args.out)

    return 1 if any(r.failed for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
