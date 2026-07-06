#!/usr/bin/env python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Public, re-runnable demonstrator of the pgrep AI-evaluation methodology.

WHAT AND WHY
  The real pgrep AI evaluation (gold sets, held-out ETS forms, the corpus, and
  the scoring harness) lives in the git-ignored private ``content/`` tree and is
  never committed, so a grader who clones the PUBLIC repo cannot run it. This
  script reproduces the SAME SHAPE of evaluation on a tiny, fully synthetic sample
  that is safe to commit (``tools/pgrep_eval_sample/``), so the methodology is
  reproducible from the public repo alone.

  It is a METHODOLOGY DEMONSTRATOR, not the real gate. The synthetic AI batch is
  hand-constructed to exercise a mostly-passing path with a couple of deliberate
  flaws, so the numbers here are illustrative. The real gate scores real
  generations against Frank's verified gold, rated by two raters (Frank plus an
  LLM-as-judge), per ``docs_pgrep/ai/cutoffs-and-baselines.md``.

WHAT IT MIRRORS (private -> this file)
  content/tools/eval_metrics.py   -> bootstrap CIs, paired advantage, kappa,
                                     useful-yield / distractor-quality, beat-baseline
  content/tools/baselines.py      -> a keyword (BM25) and a vector baseline; here the
                                     "vector" baseline is an embedding-free TF-IDF
                                     cosine stand-in so it needs no model or API
  content/tools/eval_judge.py     -> a deterministic heuristic judge (offline
                                     stand-in for the two-rater human + LLM process)
  content/tools/leakage_check.py  -> the corpus-only + verbatim copy-in firewall
  content/tools/smoke_batch.py    -> building AI / naive candidates from the gold
  docs_pgrep/ai/cutoffs-and-baselines.md -> the frozen, pre-registered cutoffs

HONESTY
  - Deterministic: fixed seed, no randomness beyond the seeded bootstrap.
  - Offline: standard library + numpy only. No API key, no network, no content/.
  - The exit code is driven by the LEAKAGE check: 0 when the firewall holds,
    1 on contamination (try ``--inject-leak`` to see it fail loudly).

USAGE
    out/pyenv/bin/python tools/pgrep_eval_public.py          # human-readable report
    out/pyenv/bin/python tools/pgrep_eval_public.py --json   # machine-readable
    out/pyenv/bin/python tools/pgrep_eval_public.py --inject-leak   # firewall fails
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SAMPLE_DIR = Path(__file__).resolve().parent / "pgrep_eval_sample"
PREREG_MD = REPO / "docs_pgrep" / "ai" / "cutoffs-and-baselines.md"

BASELINE_SYSTEMS = ("keyword", "tfidf")

# The frozen pre-registration, embedded as a self-contained fallback. These
# mirror the LOCKED block in docs_pgrep/ai/cutoffs-and-baselines.md; the doc is
# the source of truth when present (see load_cutoffs).
EMBEDDED_CUTOFFS = {
    "round": "L4.0-round-1 (embedded fallback)",
    "card": {"fact_precision": 0.95, "useful_yield": 0.80, "batch_size": 50},
    "problem": {
        "key_correctness": 0.95,
        "distractor_quality": 0.70,
        "useful_yield": 0.75,
        "batch_size": 30,
    },
    "beat_baseline": {"headline_margin": 0.10, "ci_rule": "advantage CI excludes 0"},
}


# ---------------------------------------------------------------------------
# Cutoffs: read the frozen pre-registration block from the tracked doc, with an
# embedded fallback (mirrors content/tools/eval_manifest.load_prereg).
# ---------------------------------------------------------------------------

_SECTION = {
    "card gate": "card",
    "problem gate": "problem",
    "beat-baseline": "beat_baseline",
    "raters": "raters",
}


def _parse_prereg(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    blocks = re.findall(r"```(.*?)```", text, re.S)
    block = next((b for b in blocks if "PRE-REGISTRATION" in b), None)
    if block is None:
        return None
    result: dict = {"card": {}, "problem": {}, "beat_baseline": {}, "raters": {}}
    section: str | None = None
    for raw in block.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s in _SECTION:
            section = _SECTION[s]
            continue
        meta = re.match(r"(round|date frozen|frozen by)\s*:\s*(.+)", s)
        if meta and section is None:
            result[meta.group(1).replace(" ", "_")] = meta.group(2).strip()
            continue
        if section is None:
            continue
        m = re.match(r"(.+?)\s*(>=|=|:)\s*(.+)", s)
        if not m:
            continue
        label = m.group(1).strip().lower().replace(" ", "_").replace("-", "_")
        val = m.group(3).strip()
        parts = val.split()
        num = re.match(r"^([\d.]+)$", parts[0]) if parts else None
        result[section][label] = float(num.group(1)) if num else val
    return result


def load_cutoffs() -> tuple[dict, str]:
    """Return (cutoffs, source). Prefer the tracked doc; fall back to embedded."""
    parsed = _parse_prereg(PREREG_MD)
    if parsed and parsed.get("card") and parsed.get("problem"):
        merged = json.loads(json.dumps(EMBEDDED_CUTOFFS))
        merged["round"] = parsed.get("round", merged["round"])
        for group in ("card", "problem", "beat_baseline"):
            merged[group].update({k: v for k, v in parsed.get(group, {}).items()})
        return merged, str(PREREG_MD.relative_to(REPO))
    return json.loads(json.dumps(EMBEDDED_CUTOFFS)), "embedded fallback (doc not found)"


# ---------------------------------------------------------------------------
# Metrics (ported verbatim in spirit from content/tools/eval_metrics.py).
# ---------------------------------------------------------------------------


@dataclass
class Interval:
    point: float
    low: float
    high: float

    def as_dict(self) -> dict:
        return {"point": self.point, "low": self.low, "high": self.high}


def bootstrap_ci(
    values, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0
) -> Interval:
    """Percentile bootstrap CI for the mean of 0/1 (or real) values."""
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return Interval(float("nan"), float("nan"), float("nan"))
    point = float(arr.mean())
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    means = arr[idx].mean(axis=1)
    return Interval(
        point,
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
    )


def paired_advantage_ci(
    ai_values, base_values, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0
) -> Interval:
    """Bootstrap CI for (AI mean - baseline mean), paired by item index."""
    ai = np.asarray(list(ai_values), dtype=float)
    base = np.asarray(list(base_values), dtype=float)
    if ai.size == 0 or ai.size != base.size:
        return Interval(float("nan"), float("nan"), float("nan"))
    point = float(ai.mean() - base.mean())
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, ai.size, size=(n_boot, ai.size))
    diffs = ai[idx].mean(axis=1) - base[idx].mean(axis=1)
    return Interval(
        point,
        float(np.quantile(diffs, alpha / 2)),
        float(np.quantile(diffs, 1 - alpha / 2)),
    )


def cohens_kappa(labels_a, labels_b) -> float:
    """Cohen's kappa for two raters over aligned categorical labels."""
    a, b = list(labels_a), list(labels_b)
    if not a or len(a) != len(b):
        return float("nan")
    n = len(a)
    cats = sorted(set(a) | set(b))
    idx = {c: i for i, c in enumerate(cats)}
    conf = np.zeros((len(cats), len(cats)), dtype=float)
    for x, y in zip(a, b):
        conf[idx[x], idx[y]] += 1
    po = np.trace(conf) / n
    row = conf.sum(axis=1) / n
    col = conf.sum(axis=0) / n
    pe = float((row * col).sum())
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return float((po - pe) / (1 - pe))


def distractor_passes(distractor: dict) -> bool:
    return all(
        bool(distractor.get(c))
        for c in (
            "plausible",
            "misconception_grounded",
            "non_overlapping",
            "source_grounded",
        )
    )


def problem_all_four_pass(judgment: dict) -> bool:
    ds = judgment.get("distractors", [])
    if len(ds) < 4:
        return False
    return all(distractor_passes(d) for d in ds)


def headline_value(judgment: dict, kind: str) -> float:
    if kind == "problem":
        return 1.0 if problem_all_four_pass(judgment) else 0.0
    return 1.0 if judgment.get("useful") else 0.0


def summarize(judgments: list[dict], kind: str, seed: int = 0) -> dict:
    if not judgments:
        return {"n": 0}
    fact = [1.0 if j.get("fact_precision") else 0.0 for j in judgments]
    useful = [1.0 if j.get("useful") else 0.0 for j in judgments]
    out: dict = {
        "n": len(judgments),
        "fact_precision": bootstrap_ci(fact, seed=seed).as_dict(),
        "useful_yield": bootstrap_ci(useful, seed=seed).as_dict(),
    }
    if kind == "problem":
        key = [1.0 if j.get("key_correct") else 0.0 for j in judgments]
        per_prob = [1.0 if problem_all_four_pass(j) else 0.0 for j in judgments]
        out["key_correctness"] = bootstrap_ci(key, seed=seed).as_dict()
        out["distractor_quality_per_problem"] = bootstrap_ci(
            per_prob, seed=seed
        ).as_dict()
        out["headline_metric"] = "distractor_quality_per_problem"
    else:
        out["headline_metric"] = "useful_yield"
    return out


def per_area_breakdown(judgments: list[dict], kind: str, seed: int = 0) -> dict:
    areas: dict[str, list[float]] = {}
    for j in judgments:
        area = j.get("blueprint_area") or "unknown"
        areas.setdefault(area, []).append(headline_value(j, kind))
    return {a: bootstrap_ci(v, seed=seed).as_dict() for a, v in sorted(areas.items())}


def beat_baseline(
    ai_judgments: list[dict],
    baseline_judgments: dict[str, list[dict]],
    kind: str,
    margin: float = 0.10,
    seed: int = 0,
) -> dict:
    """AI beats a baseline when advantage >= margin AND its CI excludes zero.
    The gate uses the better (highest-scoring) baseline."""
    ai_by = {j.get("target_id"): headline_value(j, kind) for j in ai_judgments}
    results: dict[str, dict] = {}
    best_name, best_point = None, -1.0
    for name, judgs in baseline_judgments.items():
        base_by = {j.get("target_id"): headline_value(j, kind) for j in judgs}
        common = [t for t in ai_by if t in base_by]
        if not common:
            continue
        adv = paired_advantage_ci(
            [ai_by[t] for t in common], [base_by[t] for t in common], seed=seed
        )
        base_point = float(np.mean([base_by[t] for t in common]))
        results[name] = {
            "baseline_headline": base_point,
            "advantage": adv.as_dict(),
            "beats": adv.point >= margin and adv.low > 0,
            "n_paired": len(common),
        }
        if base_point > best_point:
            best_point, best_name = base_point, name
    overall = bool(results.get(best_name, {}).get("beats")) if best_name else False
    return {
        "margin_required": margin,
        "ci_rule": "advantage CI excludes 0",
        "best_baseline": best_name,
        "per_baseline": results,
        "passes": overall,
    }


# ---------------------------------------------------------------------------
# Leakage firewall (ported from content/tools/leakage_check.py). The unit shingle
# is 8 words; a contiguous verbatim span at or above 25 words is treated as
# copy-in (isolated short overlaps are ordinary physics phrasing).
# ---------------------------------------------------------------------------

SHINGLE_N = 8
DEFAULT_SPAN_THRESHOLD = 25
_WORD = re.compile(r"[a-z0-9]+")


def normalize_words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _ngrams(words: list[str], n: int) -> list[str]:
    if len(words) < n:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def hashes_from_texts(texts: list[str], n: int = SHINGLE_N) -> set[str]:
    out: set[str] = set()
    for text in texts:
        out.update(_ngrams(normalize_words(text), n))
    return out


def longest_match_span(words: list[str], index_grams: set[str], n: int = SHINGLE_N):
    """Longest run of consecutive n-grams present in the index, as a word span."""
    if len(words) < n:
        gram = " ".join(words)
        return (len(words), gram) if gram and gram in index_grams else (0, "")
    matched = [
        (" ".join(words[i : i + n]) in index_grams) for i in range(len(words) - n + 1)
    ]
    best_len = best_start = run = start = 0
    for i, hit in enumerate(matched):
        if hit:
            if run == 0:
                start = i
            run += 1
            if run > best_len:
                best_len, best_start = run, start
        else:
            run = 0
    if best_len == 0:
        return 0, ""
    span_words = best_len + n - 1
    return span_words, " ".join(words[best_start : best_start + span_words])


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    hits: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "hits": self.hits,
        }


def check_corpus_only(corpus: list[dict], candidates: list[dict]) -> CheckResult:
    """Every citation an AI/baseline candidate carries resolves to a corpus passage,
    never to a gold or held-out source (the public analog of 'the index reads
    corpus/ only, retrieval returns corpus chunks')."""
    corpus_refs = {p.get("source_ref") for p in corpus}
    hits = []
    for c in candidates:
        ref = c.get("source_ref")
        if ref and ref not in corpus_refs:
            hits.append(
                f"{c.get('system')}:{c.get('target_id')} cites non-corpus source {ref!r}"
            )
    ok = not hits
    detail = (
        f"{len(candidates)} candidates, all citations resolve to the "
        f"{len(corpus_refs)} corpus passages"
        if ok
        else f"{len(hits)} candidate(s) cite a non-corpus source"
    )
    return CheckResult("corpus-only", ok, detail, hits[:20])


def check_copy_in(
    corpus: list[dict],
    items: list[tuple[str, str]],
    threshold: int = DEFAULT_SPAN_THRESHOLD,
) -> CheckResult:
    """No gold or held-out item shares a >= threshold contiguous verbatim span
    with any corpus passage."""
    grams = hashes_from_texts([p.get("text", "") for p in corpus])
    hits, worst, worst_label = [], 0, ""
    for label, text in items:
        span, covered = longest_match_span(normalize_words(text), grams)
        if span > worst:
            worst, worst_label = span, label
        if span >= threshold:
            hits.append(
                f'{label}: {span}-word verbatim span in corpus: "{covered[:110]}"'
            )
    ok = not hits
    detail = (
        f"{len(items)} gold+held-out items, longest overlap {worst} words "
        f"({worst_label or 'n/a'}), under the {threshold}-word copy-in bar"
        if ok
        else f"{len(hits)} item(s) with a copy-in span >= {threshold} words"
    )
    return CheckResult("copy-in-index", ok, detail, hits[:20])


def check_heldout_isolation(
    heldout_ids: set[str], candidates: list[dict]
) -> CheckResult:
    """No held-out item is ever scored as a candidate (held out means held out)."""
    hits = [
        f"held-out id {c.get('target_id')} appears as a {c.get('system')} candidate"
        for c in candidates
        if c.get("target_id") in heldout_ids
    ]
    ok = not hits
    detail = (
        f"{len(heldout_ids)} held-out items, none scored as candidates"
        if ok
        else f"{len(hits)} held-out item(s) leaked into the graded batch"
    )
    return CheckResult("heldout-isolation", ok, detail, hits[:20])


# ---------------------------------------------------------------------------
# Baselines (embedding-free), mirroring content/tools/baselines.py. Baseline A is
# keyword BM25; baseline B is a TF-IDF cosine stand-in for the dense-vector
# baseline, so no embedding model or API is needed. A baseline's candidate is its
# top retrieved passage: the honest "you did not need AI, search would do" test.
# ---------------------------------------------------------------------------

_STOP = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "to",
    "in",
    "on",
    "for",
    "with",
    "is",
    "are",
    "be",
    "at",
    "as",
    "by",
    "from",
    "that",
    "this",
    "it",
    "what",
    "which",
    "how",
    "when",
    "where",
    "why",
    "does",
    "if",
    "its",
}


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1]


class KeywordBaseline:
    """BM25 over the synthetic corpus passages (pure Python)."""

    name = "keyword"

    def __init__(self, corpus: list[dict], k1: float = 1.5, b: float = 0.75):
        self.passages = corpus
        self.k1, self.b = k1, b
        self.docs = [_tokens(p.get("text", "")) for p in corpus]
        self.lengths = [len(d) for d in self.docs]
        self.avgdl = (sum(self.lengths) / len(self.docs)) if self.docs else 0.0
        self.tf: list[dict[str, int]] = [dict() for _ in self.docs]
        df: dict[str, int] = {}
        for i, doc in enumerate(self.docs):
            for t in doc:
                self.tf[i][t] = self.tf[i].get(t, 0) + 1
            for t in set(doc):
                df[t] = df.get(t, 0) + 1
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def top(self, query: str, k: int = 1) -> list[dict]:
        q = [t for t in _tokens(query) if t in self.idf]
        scored = []
        for i, passage in enumerate(self.passages):
            s = 0.0
            dl = self.lengths[i] or 1
            for t in q:
                f = self.tf[i].get(t, 0)
                if f:
                    denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                    s += self.idf[t] * (f * (self.k1 + 1)) / denom
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [
            dict(self.passages[i], rank=r + 1, score=round(s, 4))
            for r, (s, i) in enumerate(scored[:k])
        ]


class TfidfBaseline:
    """TF-IDF cosine retrieval, an embedding-free stand-in for the dense-vector
    baseline (content/tools/baselines.py VectorBaseline)."""

    name = "tfidf"

    def __init__(self, corpus: list[dict]):
        self.passages = corpus
        docs = [_tokens(p.get("text", "")) for p in corpus]
        vocab = sorted({t for d in docs for t in d})
        self.index = {t: i for i, t in enumerate(vocab)}
        n = len(docs)
        df = np.zeros(len(vocab))
        for d in docs:
            for t in set(d):
                df[self.index[t]] += 1
        self.idf = np.log((1 + n) / (1 + df)) + 1.0
        self.matrix = np.zeros((n, len(vocab)))
        for i, d in enumerate(docs):
            for t in d:
                self.matrix[i, self.index[t]] += 1.0
        self.matrix *= self.idf
        norms = np.linalg.norm(self.matrix, axis=1, keepdims=True)
        self.matrix = self.matrix / np.where(norms == 0, 1, norms)

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(len(self.index))
        for t in _tokens(text):
            if t in self.index:
                v[self.index[t]] += 1.0
        v *= self.idf
        norm = np.linalg.norm(v)
        return v / norm if norm else v

    def top(self, query: str, k: int = 1) -> list[dict]:
        sims = self.matrix @ self._vec(query)
        order = np.argsort(-sims, kind="stable")
        out = []
        for rank, i in enumerate(order[:k]):
            if sims[i] <= 0:
                break
            out.append(
                dict(self.passages[i], rank=rank + 1, score=round(float(sims[i]), 4))
            )
        return out


def baseline_candidate(baseline, target: dict) -> dict:
    """Shape a baseline's top passage into a scorer candidate (mirrors
    baselines.candidate). A miss yields a refusal-shaped candidate."""
    hits = baseline.top(target["query"], k=1)
    base = {
        "system": baseline.name,
        "target_id": target["id"],
        "kind": target["kind"],
        "blueprint_area": target.get("blueprint_area"),
    }
    if not hits:
        base.update({"refused": True, "text": "", "source_ref": None})
        return base
    top = hits[0]
    base.update(
        {
            "refused": False,
            "text": top.get("text", ""),
            "source_ref": top.get("source_ref"),
            "retrieval_score": top.get("score"),
        }
    )
    return base


# ---------------------------------------------------------------------------
# The judge: a transparent, deterministic, answer-aware heuristic. This is an
# OFFLINE STAND-IN for the locked two-rater process (Frank as rater 1 and
# adjudicator, an LLM-as-judge as rater 2). On real data the raters decide fact
# precision, usefulness, and distractor quality; here we decide them mechanically
# from the known gold answers plus item structure and grounding.
# ---------------------------------------------------------------------------

_ANS = re.compile(r"\d+(?:\.\d+)?|[a-z]+")


def _answer_tokens(s: str) -> list[str]:
    return _ANS.findall((s or "").lower())


def _answer_present(gold_answer: str, cand_answer: str) -> bool:
    gold = _answer_tokens(gold_answer)
    cand = set(_answer_tokens(cand_answer))
    return bool(gold) and all(t in cand for t in gold)


def _norm_key(k) -> str:
    return str(k or "").strip().upper()


def _refused_judgment(kind: str) -> dict:
    j = {
        "fact_precision": True,
        "useful": False,
        "refused": True,
        "notes": "refused: no cited source",
    }
    if kind == "problem":
        j.update(
            {
                "key_correct": False,
                "distractors": [
                    {
                        "plausible": False,
                        "misconception_grounded": False,
                        "non_overlapping": False,
                        "source_grounded": False,
                    }
                    for _ in range(4)
                ],
            }
        )
    else:
        j["category"] = "refused"
    return j


def judge(item: dict, gold: dict, kind: str) -> dict:
    if item.get("refused"):
        return _refused_judgment(kind)
    has_source = bool(item.get("source_ref"))
    if kind == "problem":
        choices = item.get("choices") or []
        texts = [c.get("text", "") if isinstance(c, dict) else str(c) for c in choices]
        has_structure = len(choices) >= 5 and bool(item.get("key"))
        key_match = _norm_key(item.get("key")) == _norm_key(gold.get("key"))
        grounded = bool(item.get("distractor_rationales"))
        distinct = len(set(texts)) == len(texts) and len(texts) >= 5
        fact_precision = has_source and key_match  # a wrong key is a wrong fact
        key_correct = has_structure and has_source and key_match
        useful = fact_precision and has_structure and key_correct
        distractors = [
            {
                "plausible": bool(useful),
                "misconception_grounded": bool(grounded),
                "non_overlapping": bool(distinct),
                "source_grounded": bool(has_source),
            }
            for _ in range(4)
        ]
        return {
            "fact_precision": fact_precision,
            "key_correct": key_correct,
            "useful": useful,
            "distractors": distractors,
            "notes": f"key_match={key_match} grounded={grounded} distinct={distinct}",
        }
    back = str(item.get("back") or "")
    has_structure = bool(back) and len(back) <= 600
    answer_match = _answer_present(gold.get("back", ""), back)
    fact_precision = has_source and answer_match
    useful = fact_precision and has_structure and not item.get("_bad_teaching")
    category = (
        "correct_useful"
        if useful
        else ("wrong_fact" if not fact_precision else "correct_bad_teaching")
    )
    return {
        "fact_precision": fact_precision,
        "useful": useful,
        "category": category,
        "notes": f"answer_match={answer_match} structure={has_structure}",
    }


# ---------------------------------------------------------------------------
# Data loading + candidate construction (mirrors content/tools/smoke_batch.py).
# ---------------------------------------------------------------------------

# Deliberate, documented flaws in the synthetic AI batch, so the demo shows the
# gate discriminating rather than a rigged clean sweep:
AI_REFUSED_CARD = "syn-card-08"  # cite-or-refuse refusal (useful=False)
AI_WRONG_KEY_PROBLEM = "syn-prob-06"  # a degraded generation: wrong key + no rationales


def load_sample(sample_dir: Path) -> dict:
    corpus = json.loads(
        (sample_dir / "corpus" / "corpus.json").read_text(encoding="utf-8")
    )
    cards = json.loads((sample_dir / "gold" / "cards.json").read_text(encoding="utf-8"))
    problems = json.loads(
        (sample_dir / "gold" / "problems.json").read_text(encoding="utf-8")
    )
    heldout = json.loads(
        (sample_dir / "heldout" / "heldout.json").read_text(encoding="utf-8")
    )
    passages = corpus["passages"] if isinstance(corpus, dict) else corpus
    held_items = heldout["items"] if isinstance(heldout, dict) else heldout
    return {
        "corpus": passages,
        "cards": cards,
        "problems": problems,
        "heldout": held_items,
    }


def _held_text(it: dict) -> str:
    parts = [str(it.get("stem", ""))] + [str(c) for c in it.get("choices", [])]
    return " ".join(p for p in parts if p)


def _gold_text(it: dict) -> str:
    parts = [str(it.get(k, "")) for k in ("front", "back", "stem")]
    for c in it.get("choices", []):
        parts.append(c.get("text", "") if isinstance(c, dict) else str(c))
    return " ".join(p for p in parts if p)


def build_candidates(sample: dict, corpus: list[dict]) -> list[dict]:
    """AI + naive candidates from the gold (like smoke_batch), plus a keyword and a
    TF-IDF baseline candidate per target."""
    kw, tf = KeywordBaseline(corpus), TfidfBaseline(corpus)
    out: list[dict] = []

    for c in sample["cards"]:
        cid, area = c["id"], c.get("blueprint_area")
        src = c.get("provenance", {}).get("source_ref")
        if cid == AI_REFUSED_CARD:
            out.append(
                {
                    "system": "ai",
                    "target_id": cid,
                    "kind": "card",
                    "blueprint_area": area,
                    "refused": True,
                    "back": "",
                    "source_ref": None,
                }
            )
        else:
            out.append(
                {
                    "system": "ai",
                    "target_id": cid,
                    "kind": "card",
                    "blueprint_area": area,
                    "refused": False,
                    "front": c["front"],
                    "back": c["back"],
                    "source_ref": src,
                }
            )
        target = {
            "id": cid,
            "query": c["front"],
            "kind": "card",
            "blueprint_area": area,
        }
        out.append(baseline_candidate(kw, target))
        out.append(baseline_candidate(tf, target))

    for p in sample["problems"]:
        pid, area = p["id"], p.get("blueprint_area")
        src = p.get("provenance", {}).get("source_ref")
        choices = [{"label": ch["label"], "text": ch["text"]} for ch in p["choices"]]
        rationales = {
            ch["label"]: ch.get("rationale", "")
            for ch in p["choices"]
            if not ch.get("is_key")
        }
        if pid == AI_WRONG_KEY_PROBLEM:
            wrong = next(ch["label"] for ch in p["choices"] if not ch.get("is_key"))
            out.append(
                {
                    "system": "ai",
                    "target_id": pid,
                    "kind": "problem",
                    "blueprint_area": area,
                    "refused": False,
                    "stem": p["stem"],
                    "choices": choices,
                    "key": wrong,
                    "distractor_rationales": {},
                    "source_ref": src,
                }
            )
        else:
            out.append(
                {
                    "system": "ai",
                    "target_id": pid,
                    "kind": "problem",
                    "blueprint_area": area,
                    "refused": False,
                    "stem": p["stem"],
                    "choices": choices,
                    "key": p["key"],
                    "distractor_rationales": rationales,
                    "source_ref": src,
                }
            )
        # naive: correct key + choices, but NO misconception rationales.
        out.append(
            {
                "system": "naive",
                "target_id": pid,
                "kind": "problem",
                "blueprint_area": area,
                "refused": False,
                "stem": p["stem"],
                "choices": choices,
                "key": p["key"],
                "distractor_rationales": {},
                "source_ref": src,
            }
        )
        target = {
            "id": pid,
            "query": p["stem"],
            "kind": "problem",
            "blueprint_area": area,
        }
        out.append(baseline_candidate(kw, target))
        out.append(baseline_candidate(tf, target))
    return out


# ---------------------------------------------------------------------------
# Scoring driver.
# ---------------------------------------------------------------------------


def attach_meta(j: dict, cand: dict) -> dict:
    j.update(
        {
            "target_id": cand.get("target_id"),
            "system": cand.get("system"),
            "kind": cand.get("kind"),
            "blueprint_area": cand.get("blueprint_area"),
        }
    )
    return j


def gate_card(summary: dict, beat: dict, cut: dict) -> dict:
    c = cut.get("card", {})
    checks = {
        "fact_precision": summary["fact_precision"]["point"]
        >= c.get("fact_precision", 0.95),
        "useful_yield": summary["useful_yield"]["point"] >= c.get("useful_yield", 0.80),
        "beats_baseline": beat["passes"],
    }
    batch = {
        "n": summary["n"],
        "locked_min": int(c.get("batch_size", 50)),
        "meets": summary["n"] >= c.get("batch_size", 50),
    }
    return {
        "checks": checks,
        "batch_size": batch,
        "quality_passes": all(checks.values()),
    }


def gate_problem(summary: dict, beat: dict, cut: dict) -> dict:
    c = cut.get("problem", {})
    checks = {
        "key_correctness": summary["key_correctness"]["point"]
        >= c.get("key_correctness", 0.95),
        "distractor_quality_per_problem": summary["distractor_quality_per_problem"][
            "point"
        ]
        >= c.get("distractor_quality", 0.70),
        "useful_yield": summary["useful_yield"]["point"] >= c.get("useful_yield", 0.75),
        "beats_baseline": beat["passes"],
    }
    batch = {
        "n": summary["n"],
        "locked_min": int(c.get("batch_size", 30)),
        "meets": summary["n"] >= c.get("batch_size", 30),
    }
    return {
        "checks": checks,
        "batch_size": batch,
        "quality_passes": all(checks.values()),
    }


def run_eval(sample_dir: Path, seed: int = 0, inject_leak: bool = False) -> dict:
    sample = load_sample(sample_dir)
    corpus = sample["corpus"]
    cut, cut_source = load_cutoffs()
    margin = float(cut.get("beat_baseline", {}).get("headline_margin", 0.10))

    candidates = build_candidates(sample, corpus)

    # --- Leakage firewall (drives the exit code) ---
    scan_corpus = list(corpus)
    if inject_leak:
        # Copy a gold problem verbatim into the "index" to prove the guard fires.
        leaked = sample["problems"][0]
        scan_corpus = corpus + [
            {
                "source_ref": "LEAK",
                "text": _gold_text(leaked),
                "chunk_id": "leak",
                "synthetic": True,
            }
        ]
    gold_texts = [(f"gold-card:{c['id']}", _gold_text(c)) for c in sample["cards"]]
    gold_texts += [
        (f"gold-problem:{p['id']}", _gold_text(p)) for p in sample["problems"]
    ]
    held_texts = [(f"heldout:{h['id']}", _held_text(h)) for h in sample["heldout"]]
    heldout_ids = {h["id"] for h in sample["heldout"]}
    leakage = [
        check_corpus_only(corpus, candidates),
        check_copy_in(scan_corpus, gold_texts + held_texts),
        check_heldout_isolation(heldout_ids, candidates),
    ]
    firewall_ok = all(r.ok for r in leakage)

    # --- Score every candidate against its gold (canonical order = deterministic) ---
    gold_by_id = {c["id"]: c for c in sample["cards"]} | {
        p["id"]: p for p in sample["problems"]
    }
    order = sorted(candidates, key=lambda c: (c["kind"], c["target_id"], c["system"]))
    judged = [
        attach_meta(judge(c, gold_by_id.get(c["target_id"], {}), c["kind"]), c)
        for c in order
    ]

    by_sk: dict[tuple, list] = {}
    for j in judged:
        by_sk.setdefault((j["system"], j["kind"]), []).append(j)

    report: dict = {
        "cutoffs_source": cut_source,
        "round": cut.get("round"),
        "systems": {},
        "beat_baseline": {},
        "per_area": {},
        "gate": {},
        "naive_comparison": {},
        "leakage": [r.as_dict() for r in leakage],
        "firewall_ok": firewall_ok,
    }

    for kind in ("card", "problem"):
        ai_j = by_sk.get(("ai", kind), [])
        if not ai_j:
            continue
        report["systems"][kind] = {
            s: summarize(by_sk.get((s, kind), []), kind, seed=seed)
            for s in ("ai", *BASELINE_SYSTEMS, "naive")
            if by_sk.get((s, kind))
        }
        base_j = {
            s: by_sk.get((s, kind), [])
            for s in BASELINE_SYSTEMS
            if by_sk.get((s, kind))
        }
        beat = beat_baseline(ai_j, base_j, kind, margin=margin, seed=seed)
        report["beat_baseline"][kind] = beat
        report["per_area"][kind] = per_area_breakdown(ai_j, kind, seed=seed)
        ai_sum = report["systems"][kind]["ai"]
        report["gate"][kind] = (
            gate_card(ai_sum, beat, cut)
            if kind == "card"
            else gate_problem(ai_sum, beat, cut)
        )
        if kind == "problem" and by_sk.get(("naive", kind)):
            naive_j = by_sk[("naive", kind)]
            ai_by = {j["target_id"]: headline_value(j, kind) for j in ai_j}
            nv_by = {j["target_id"]: headline_value(j, kind) for j in naive_j}
            common = [t for t in ai_by if t in nv_by]
            adv = paired_advantage_ci(
                [ai_by[t] for t in common], [nv_by[t] for t in common], seed=seed
            )
            report["naive_comparison"][kind] = {
                "note": "reported comparison only, not a gate",
                "ai_minus_naive": adv.as_dict(),
            }

    # --- Illustrative inter-rater agreement (single mechanical judge perturbed to
    # stand in for a second rater; shows the kappa the real two-rater gate reports).
    rng = np.random.default_rng(seed)
    ai_all = [j for j in judged if j["system"] == "ai"]
    r1 = [bool(j.get("useful")) for j in ai_all]
    r2 = [(not u) if rng.random() < 0.15 else u for u in r1]
    report["inter_rater"] = {
        "note": "illustrative: one mechanical judge perturbed to stand in "
        "for a second rater (the real gate uses Frank + an LLM judge)",
        "n": len(r1),
        "kappa_useful": cohens_kappa(r1, r2),
    }
    report["seen_vs_held"] = {
        "fed": [],
        "gold": sorted(gold_by_id),
        "heldout": sorted(heldout_ids),
        "statement": (
            "Synthetic sample: nothing is fed to generation; the AI candidates ground "
            f"on the {len(corpus)} corpus passages only. Held out, never graded: "
            f"{', '.join(sorted(heldout_ids))}."
        ),
    }
    return report


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------


def _fmt(ci: dict) -> str:
    if ci is None or any(
        math.isnan(ci.get(k, float("nan"))) for k in ("point", "low", "high")
    ):
        return "  n/a"
    return f"{ci['point']:.3f} [{ci['low']:.3f}, {ci['high']:.3f}]"


def _mark(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def print_report(report: dict) -> None:
    line = "=" * 74
    print(line)
    print("pgrep public evaluation  (methodology demonstrator on a synthetic sample)")
    print(line)
    print(f"cutoffs: {report['round']}   source: {report['cutoffs_source']}")
    print(
        "note: synthetic AI batch, hand-built with deliberate flaws; illustrative, not the gate."
    )

    print("\nLEAKAGE FIREWALL  (drives the exit code)")
    print("-" * 74)
    for r in report["leakage"]:
        print(f"  [{_mark(r['ok'])}] {r['name']:20} {r['detail']}")
        for h in r["hits"]:
            print(f"           - {h}")
    print(f"  => firewall {'intact' if report['firewall_ok'] else 'BREACHED'}")

    for kind in ("card", "problem"):
        systems = report["systems"].get(kind)
        if not systems:
            continue
        head = "useful_yield" if kind == "card" else "distractor_quality_per_problem"
        print(f"\n{kind.upper()} RESULTS   (headline metric: {head})")
        print("-" * 74)
        for s, summ in systems.items():
            if not summ.get("n"):
                continue
            row = f"  {s:8} n={summ['n']:<3} fact_prec={_fmt(summ['fact_precision'])}  useful={_fmt(summ['useful_yield'])}"
            if kind == "problem":
                row += f"\n{'':13}key_correct={_fmt(summ['key_correctness'])}  distractor/prob={_fmt(summ['distractor_quality_per_problem'])}"
            print(row)
        beat = report["beat_baseline"][kind]
        print(
            f"  beat-baseline (need >= {beat['margin_required']:.2f} and {beat['ci_rule']}): "
            f"best baseline = {beat['best_baseline']}, AI {_mark(beat['passes'])}"
        )
        for name, b in beat["per_baseline"].items():
            print(
                f"     vs {name:8} advantage={_fmt(b['advantage'])}  beats={b['beats']}"
            )
        if kind == "problem" and report["naive_comparison"].get(kind):
            nv = report["naive_comparison"][kind]
            print(
                f"  naive-distractor (reported, not a gate): AI - naive = {_fmt(nv['ai_minus_naive'])}"
            )
        print("  per-area headline:")
        for area, ci in report["per_area"][kind].items():
            print(f"     {area:20} {_fmt(ci)}")
        gate = report["gate"][kind]
        print(f"  GATE ({kind}) vs locked cutoffs:")
        for metric, ok in gate["checks"].items():
            print(f"     [{_mark(ok)}] {metric}")
        bs = gate["batch_size"]
        print(
            f"     [{_mark(bs['meets'])}] batch_size  n={bs['n']} vs locked {bs['locked_min']}  "
            f"(demo sample is intentionally tiny; not a quality signal)"
        )
        print(
            f"  => quality gate {_mark(gate['quality_passes'])}  (batch size excluded: demo)"
        )

    ir = report["inter_rater"]
    kappa = ir["kappa_useful"]
    print(
        f"\ninter-rater kappa (useful): {kappa:.3f}  over n={ir['n']}  [{ir['note']}]"
    )
    print("\nseen vs held:")
    print(f"  {report['seen_vs_held']['statement']}")

    print("\n" + line)
    print(
        f"LEAKAGE FIREWALL: {'intact -> exit 0' if report['firewall_ok'] else 'BREACHED -> exit 1'}"
    )
    print(line)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--sample-dir", default=str(SAMPLE_DIR), help="synthetic sample directory"
    )
    ap.add_argument(
        "--seed", type=int, default=0, help="bootstrap seed (deterministic)"
    )
    ap.add_argument(
        "--json", action="store_true", help="emit the machine-readable report"
    )
    ap.add_argument(
        "--inject-leak",
        action="store_true",
        help="copy a gold item into the corpus to prove the firewall fails (exit 1)",
    )
    args = ap.parse_args()

    report = run_eval(
        Path(args.sample_dir), seed=args.seed, inject_leak=args.inject_leak
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)
    sys.exit(0 if report["firewall_ok"] else 1)


if __name__ == "__main__":
    main()
