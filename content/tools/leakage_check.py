"""The pgrep leakage guard (E2 firewall backstop).

The firewall is structural first: the index build reads ``content/corpus/`` only,
so gold, held-out, and Tier-3 text cannot reach the index or a prompt by
construction. This guard is the automated backstop that fails loudly if that
ever breaks. It implements the six checks written down in
``docs_pgrep/ai/heldout-and-leakage.md`` section 4 and ``docs_pgrep/ai/ai-layer.md``
section 10.

Checks:
  1. Corpus only. Every source indexed in ``content/index/corpus.db`` resolves
     to a file under ``content/corpus/`` and never under a private root
     (``tier3-private/``, ``gold/``, ``heldout/``).
  2. No held-out or gold copy-in. The longest contiguous verbatim word span
     shared between any held-out or gold item and any indexed chunk stays below
     the copy-in threshold. Isolated short overlaps are standard physics
     phrasing, not leakage, so the signal is a long contiguous span, not a
     single n-gram.
  3. No held-out or gold copy-in in saved prompt logs (if any exist).
  4. Foundry preference JSONL has valid schema and IDs, no private-root path
     markers, and no long verbatim spans copied from available private items.
  5. The AI path never references a private root. Shipped pgrep modules under
     ``pylib/anki/pgrep/`` may only reference ``tier3-private`` via the
     ``constants/`` subpath (the readiness reader), never the items.
  6. Readiness reader is constants-only. Restated by check 5 for the shipped
     code; the items under ``tier3-private/`` are never opened by the AI path.

This is a process guard, not a model. It reads text only, never writes.

Run:
    conda run -n pgrep-ai python content/tools/leakage_check.py
    conda run -n pgrep-ai python content/tools/leakage_check.py --span-threshold 25 -v
Exit code is 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field

import _ai_path

_ai_path.add_ai_core()

from pgrep.ai import preference  # type: ignore[import-not-found]  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.dirname(HERE)
REPO = os.path.dirname(CONTENT)

INDEX_DB = os.path.join(CONTENT, "index", "corpus.db")
CORPUS_DIR = os.path.join(CONTENT, "corpus")
PRIVATE_ROOTS = {
    "tier3-private": os.path.join(CONTENT, "tier3-private"),
    "gold": os.path.join(CONTENT, "gold"),
    "heldout": os.path.join(CONTENT, "heldout"),
}
# Where generation/tutor prompt transcripts land, when logging is on.
PROMPT_LOG_DIRS = [
    os.path.join(CONTENT, "index", "prompt_logs"),
    os.path.join(CONTENT, "run", "prompt_logs"),
]
FOUNDRY_RUN_DIR = os.path.join(CONTENT, "run", "foundry")
# Shipped AI/runtime code that must never reach a private root except constants.
SHIPPED_AI_DIR = os.path.join(REPO, "pylib", "anki", "pgrep")
_FORBIDDEN_FOUNDRY_PATH_MARKERS = (
    "content/gold",
    "content/heldout",
    "tier3-private",
)

# The unit n-gram used to locate contiguous overlap. Small enough to place a
# span precisely, large enough that one match is not pure noise.
SHINGLE_N = 8
# A contiguous verbatim span at or above this many words is treated as copy-in.
# ETS stems copied whole run 20+ words; standard physics phrasing coincidences
# top out around a dozen, so 25 separates cleanly.
DEFAULT_SPAN_THRESHOLD = 25

_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    hits: list[str] = field(default_factory=list)


def normalize_words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _ngrams(words: list[str], n: int) -> list[str]:
    if len(words) < n:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def _hash(text: str) -> bytes:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()


def hashes_from_texts(texts: list[str], n: int = SHINGLE_N) -> set[bytes]:
    hashes: set[bytes] = set()
    for text in texts:
        for gram in _ngrams(normalize_words(text), n):
            hashes.add(_hash(gram))
    return hashes


def longest_match_span(
    words: list[str], index_hashes: set[bytes], n: int = SHINGLE_N
) -> tuple[int, str]:
    """Longest run of consecutive n-grams present in the index, as a word span.

    A run of ``r`` consecutive matching n-grams covers ``r + n - 1`` contiguous
    words. Returns that word count and the covered text (empty when nothing
    matches).
    """
    if len(words) < n:
        gram = " ".join(words)
        if gram and _hash(gram) in index_hashes:
            return len(words), gram
        return 0, ""
    matched = [
        (_hash(" ".join(words[i : i + n])) in index_hashes)
        for i in range(len(words) - n + 1)
    ]
    best_len = 0
    best_start = 0
    run = 0
    start = 0
    for i, hit in enumerate(matched):
        if hit:
            if run == 0:
                start = i
            run += 1
            if run > best_len:
                best_len = run
                best_start = start
        else:
            run = 0
    if best_len == 0:
        return 0, ""
    span_words = best_len + n - 1
    return span_words, " ".join(words[best_start : best_start + span_words])


# --- item loading ----------------------------------------------------------


def _heldout_item_texts() -> list[tuple[str, str]]:
    """(label, text) for every parsed held-out ETS item (stem + choices)."""
    out: list[tuple[str, str]] = []
    for path in sorted(
        glob.glob(os.path.join(CONTENT, "tier3-private", "items", "*.json"))
    ):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        for it in data:
            parts = [str(it.get("stem", ""))]
            parts += [str(c) for c in it.get("choices", []) if c]
            text = " ".join(p for p in parts if p.strip())
            if text.strip():
                out.append((f"heldout:{it.get('id', '?')}", text))
    return out


def _gold_item_texts() -> list[tuple[str, str]]:
    """(label, text) for every gold item (cards: front+back, problems: stem+choices)."""
    out: list[tuple[str, str]] = []
    for path in sorted(glob.glob(os.path.join(CONTENT, "gold", "cards", "*.json"))):
        try:
            it = json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        text = " ".join(str(it.get(k, "")) for k in ("front", "back"))
        if text.strip():
            out.append((f"gold-card:{it.get('id', os.path.basename(path))}", text))
    for path in sorted(glob.glob(os.path.join(CONTENT, "gold", "problems", "*.json"))):
        try:
            it = json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        parts = [str(it.get("stem", ""))]
        choices = it.get("choices", [])
        if isinstance(choices, list):
            for c in choices:
                parts.append(c.get("text", "") if isinstance(c, dict) else str(c))
        text = " ".join(p for p in parts if p)
        if text.strip():
            out.append((f"gold-problem:{it.get('id', os.path.basename(path))}", text))
    return out


# --- the checks ------------------------------------------------------------


def check_index_paths(db_path: str) -> CheckResult:
    """Every indexed source resolves under corpus/ and never under a private root."""
    if not os.path.exists(db_path):
        return CheckResult("index-paths", False, f"no index at {db_path}")
    db = sqlite3.connect(db_path)
    try:
        rows = db.execute("SELECT DISTINCT source_file FROM chunks").fetchall()
    finally:
        db.close()
    hits: list[str] = []
    corpus_files = {
        os.path.basename(p)
        for p in glob.glob(os.path.join(CORPUS_DIR, "**", "*"), recursive=True)
    }
    private_files: dict[str, str] = {}
    for label, root in PRIVATE_ROOTS.items():
        for p in glob.glob(os.path.join(root, "**", "*"), recursive=True):
            private_files[os.path.basename(p)] = label
    for (source_file,) in rows:
        base = os.path.basename(source_file)
        if base in private_files:
            hits.append(
                f"{source_file} resolves under private root {private_files[base]}"
            )
        elif base not in corpus_files:
            hits.append(f"{source_file} is not present under content/corpus/")
    ok = not hits
    detail = (
        f"{len(rows)} distinct sources indexed, all under content/corpus/"
        if ok
        else f"{len(hits)} indexed source(s) not corpus-only"
    )
    return CheckResult("index-paths", ok, detail, hits)


def _copyin_check(
    name: str,
    target_hashes: set[bytes],
    items: list[tuple[str, str]],
    threshold: int,
    where: str,
) -> CheckResult:
    """Flag any item whose longest contiguous span in the target reaches threshold."""
    hits: list[str] = []
    worst = 0
    worst_label = ""
    for label, text in items:
        span, covered = longest_match_span(normalize_words(text), target_hashes)
        if span > worst:
            worst, worst_label = span, label
        if span >= threshold:
            hits.append(f'{label}: {span}-word span {where}: "{covered[:120]}"')
    ok = not hits
    if ok:
        detail = (
            f"{len(items)} items, longest overlap {worst} words "
            f"({worst_label or 'n/a'}), under the {threshold}-word copy-in bar"
        )
    else:
        detail = f"{len(hits)} item(s) with a copy-in span >= {threshold} words"
    return CheckResult(name, ok, detail, hits[:20])


def check_shingles(
    db_path: str, items: list[tuple[str, str]], threshold: int
) -> CheckResult:
    """No held-out or gold item shares a long contiguous span with the index."""
    if not os.path.exists(db_path):
        return CheckResult("copy-in-index", False, f"no index at {db_path}")
    if not items:
        return CheckResult(
            "copy-in-index", True, "no held-out or gold items present to check yet"
        )
    db = sqlite3.connect(db_path)
    try:
        texts = [t for (t,) in db.execute("SELECT text FROM chunks")]
    finally:
        db.close()
    return _copyin_check(
        "copy-in-index", hashes_from_texts(texts), items, threshold, "in index"
    )


def check_prompt_logs(items: list[tuple[str, str]], threshold: int) -> CheckResult:
    """No held-out or gold item shares a long contiguous span with a saved prompt."""
    log_files: list[str] = []
    for d in PROMPT_LOG_DIRS:
        if os.path.isdir(d):
            log_files += glob.glob(os.path.join(d, "**", "*"), recursive=True)
    log_files = [f for f in log_files if os.path.isfile(f)]
    if not log_files:
        return CheckResult("copy-in-prompts", True, "no prompt logs on disk to scan")
    if not items:
        return CheckResult(
            "copy-in-prompts",
            True,
            f"{len(log_files)} logs, no gold/held-out items to match",
        )
    texts = []
    for path in log_files:
        try:
            texts.append(open(path, encoding="utf-8", errors="ignore").read())
        except OSError:
            continue
    res = _copyin_check(
        "copy-in-prompts", hashes_from_texts(texts), items, threshold, "in prompt logs"
    )
    res.detail = f"{len(log_files)} prompt log(s): " + res.detail
    return res


def _nested_path(path: str, key: object) -> str:
    return f"{path}.{key}" if isinstance(key, str) else f"{path}[{key!r}]"


def _private_root_errors(value: object, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, str):
        normalized = value.lower().replace("\\\\", "/").replace("\\", "/")
        for marker in _FORBIDDEN_FOUNDRY_PATH_MARKERS:
            if marker in normalized:
                errors.append(f"{path}: forbidden private-root marker: {marker}")
    elif isinstance(value, dict):
        for key, nested in value.items():
            child = _nested_path(path, key)
            if isinstance(key, str):
                errors.extend(_private_root_errors(key, f"{child} (key)"))
            errors.extend(_private_root_errors(nested, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            errors.extend(_private_root_errors(nested, f"{path}[{index}]"))
    return errors


def foundry_jsonl_is_clean(path: str) -> list[str]:
    """Validate one preference JSONL file and reject private-root path markers."""
    errors = preference.scan_jsonl(path)
    try:
        with open(path, encoding="utf-8") as file:
            for lineno, line in enumerate(file, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                errors.extend(
                    f"line {lineno}: {error}" for error in _private_root_errors(record)
                )
    except OSError:
        pass
    return errors


def check_foundry_preferences(
    items: list[tuple[str, str]],
    threshold: int,
    foundry_dir: str = FOUNDRY_RUN_DIR,
) -> CheckResult:
    """Validate all foundry JSONL and compare it with available private items."""
    files = sorted(
        path
        for path in glob.glob(
            os.path.join(foundry_dir, "**", "*.jsonl"), recursive=True
        )
        if os.path.isfile(path)
    )
    if not files:
        return CheckResult(
            "foundry-preferences",
            True,
            "no foundry preference JSONL files on disk to scan",
        )

    hits: list[str] = []
    texts: list[str] = []
    for path in files:
        rel = os.path.relpath(path, REPO)
        hits.extend(f"{rel}:{error}" for error in foundry_jsonl_is_clean(path))
        try:
            texts.append(open(path, encoding="utf-8").read())
        except OSError:
            continue

    if items and texts:
        copyin = _copyin_check(
            "foundry-preferences",
            hashes_from_texts(texts),
            items,
            threshold,
            "in foundry preference JSONL",
        )
        hits.extend(copyin.hits)

    ok = not hits
    if ok:
        private_detail = (
            f"; no copy-in from {len(items)} private item(s)"
            if items
            else "; no private items present for copy-in matching"
        )
        detail = (
            f"{len(files)} foundry preference file(s), schema and paths clean"
            f"{private_detail}"
        )
    else:
        detail = f"{len(hits)} foundry preference leakage error(s)"
    return CheckResult("foundry-preferences", ok, detail, hits[:20])


def check_ai_path_references() -> CheckResult:
    """Shipped pgrep code may touch tier3-private only via constants/, never gold/heldout."""
    if not os.path.isdir(SHIPPED_AI_DIR):
        return CheckResult("ai-path-refs", True, "no shipped pgrep code yet")
    hits: list[str] = []
    py_files = glob.glob(os.path.join(SHIPPED_AI_DIR, "**", "*.py"), recursive=True)
    for path in py_files:
        try:
            for lineno, line in enumerate(open(path, encoding="utf-8"), start=1):
                for token in ("tier3-private", "content/gold", "content/heldout"):
                    if token in line:
                        allowed = token == "tier3-private" and "constants" in line
                        if not allowed:
                            rel = os.path.relpath(path, REPO)
                            hits.append(
                                f"{rel}:{lineno} references {token}: {line.strip()[:80]}"
                            )
        except OSError:
            continue
    ok = not hits
    detail = (
        f"{len(py_files)} shipped pgrep file(s), no forbidden private-root access"
        if ok
        else f"{len(hits)} forbidden reference(s) in the AI path"
    )
    return CheckResult("ai-path-refs", ok, detail, hits[:20])


# --- driver ----------------------------------------------------------------


def run_checks(
    db_path: str = INDEX_DB,
    span_threshold: int = DEFAULT_SPAN_THRESHOLD,
    foundry_dir: str = FOUNDRY_RUN_DIR,
) -> list[CheckResult]:
    items = _heldout_item_texts() + _gold_item_texts()
    return [
        check_index_paths(db_path),
        check_shingles(db_path, items, span_threshold),
        check_prompt_logs(items, span_threshold),
        check_foundry_preferences(items, span_threshold, foundry_dir),
        check_ai_path_references(),
    ]


def report(results: list[CheckResult], verbose: bool = False) -> bool:
    all_ok = all(r.ok for r in results)
    print("pgrep leakage check")
    print("-" * 60)
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"[{mark}] {r.name:16} {r.detail}")
        if r.hits and (verbose or not r.ok):
            for h in r.hits:
                print(f"         - {h}")
    print("-" * 60)
    print(
        "OK: firewall intact"
        if all_ok
        else "FAILED: leakage detected, do not report results"
    )
    return all_ok


def main() -> None:
    ap = argparse.ArgumentParser(description="pgrep leakage guard (firewall backstop).")
    ap.add_argument("--db", default=INDEX_DB)
    ap.add_argument(
        "--span-threshold",
        type=int,
        default=DEFAULT_SPAN_THRESHOLD,
        help="contiguous verbatim word span treated as copy-in",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    results = run_checks(args.db, args.span_threshold)
    ok = report(results, args.verbose)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
