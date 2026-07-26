# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Token/spend ledger, budgets and kill switch for paid model calls (WS10).

Every paid call in the content pipeline goes through
:class:`anki.pgrep.ai.llm.LLMClient`, which now consults this module before the
network call and records one event after it. That gives two things the pipeline
previously lacked: an answer to "what have we spent today", and a way to stop a
runaway batch without waiting for an invoice.

**The ledger** is JSONL, one file per UTC day, under ``content/run/usage/``
(git-ignored). Events carry metadata and counts only -- never prompts,
completions, corpus text, API keys, or a full base URL. TrueFoundry's dashboard
stays the invoice source of truth; this is the run-time control plane, and its
USD figures are estimates from :mod:`anki.pgrep.ai.usage_prices`.

**The budgets** are resolved once per process from the environment, with an
optional operator file at ``content/run/usage/budget.env``:

===============================  =======================================
``PGREP_BUDGET_SOFT_USD``        warn once and continue
``PGREP_BUDGET_HARD_USD``        refuse further calls today
``PGREP_BUDGET_HARD_TOKENS``     refuse further calls today
``PGREP_BUDGET_RUN_USD``         refuse further calls in this run
``PGREP_AI_SPEND_LOCK=1``        refuse every paid call immediately
===============================  =======================================

Code defaults to no cap so CI and offline tests stay quiet; operators set hard
caps for real work. Caps are checked *before* each call against spend so far,
so the call that crosses a limit still completes and the next one is refused --
a cap bounds a batch, it does not clip an individual request.

Two knobs support attribution: ``PGREP_USAGE_RUN_ID`` tags one batch and
``PGREP_USAGE_TOOL`` tags the calling tool, both set by the ``just`` recipes.
``PGREP_USAGE_DIR`` relocates the ledger (tests, sandboxes).

Fail-closed rule: when any hard cap is set and the ledger cannot be read or
written, calls are refused rather than run blind. With no hard cap set, ledger
trouble degrades to a warning so an offline or read-only checkout still works.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from .usage_prices import estimate_usd, family_for

LEDGER_SCHEMA = "pgrep-usage/v1"
BUDGET_FILE = "budget.env"

_ENV_SOFT_USD = "PGREP_BUDGET_SOFT_USD"
_ENV_HARD_USD = "PGREP_BUDGET_HARD_USD"
_ENV_HARD_TOKENS = "PGREP_BUDGET_HARD_TOKENS"
_ENV_RUN_USD = "PGREP_BUDGET_RUN_USD"
_ENV_LOCK = "PGREP_AI_SPEND_LOCK"
_BUDGET_ENV_VARS = (
    _ENV_SOFT_USD,
    _ENV_HARD_USD,
    _ENV_HARD_TOKENS,
    _ENV_RUN_USD,
    _ENV_LOCK,
)

_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    """A configured spend cap would be exceeded, or paid calls are locked off."""


class LedgerUnavailable(BudgetExceeded):
    """A hard cap is set but the ledger cannot be read or written."""


# --- paths -----------------------------------------------------------------


def ledger_dir() -> str:
    """The directory holding the day files, honouring ``PGREP_USAGE_DIR``."""
    override = os.environ.get("PGREP_USAGE_DIR")
    if override:
        return os.path.abspath(override)
    here = os.path.abspath(__file__)
    repo = here
    for _ in range(5):  # ai -> pgrep -> anki -> pylib -> repo root
        repo = os.path.dirname(repo)
    return os.path.join(repo, "content", "run", "usage")


def day_path(day: str | None = None) -> str:
    """Path to one UTC day's JSONL file (defaults to today)."""
    return os.path.join(ledger_dir(), f"{day or today()}.jsonl")


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def run_id() -> str | None:
    return os.environ.get("PGREP_USAGE_RUN_ID") or None


def tool_name() -> str | None:
    return os.environ.get("PGREP_USAGE_TOOL") or None


# --- budgets ---------------------------------------------------------------


@dataclass(frozen=True)
class Budgets:
    soft_usd: float | None = None
    hard_usd: float | None = None
    hard_tokens: int | None = None
    run_usd: float | None = None
    locked: bool = False

    @property
    def any_hard(self) -> bool:
        """True when a limit exists that must not be crossed silently."""
        return (
            self.locked
            or self.hard_usd is not None
            or self.hard_tokens is not None
            or self.run_usd is not None
        )

    @property
    def configured(self) -> bool:
        return self.any_hard or self.soft_usd is not None


def _budget_file_values() -> dict[str, str]:
    """Budget vars from the operator file, if it exists. Never raises."""
    path = os.path.join(ledger_dir(), BUDGET_FILE)
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, val = stripped.split("=", 1)
                key = key.strip()
                if key in _BUDGET_ENV_VARS:
                    values[key] = val.strip().strip('"').strip("'")
    except OSError:
        return {}
    return values


def _as_float(raw: str | None, *, name: str) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value}")
    return value


def _as_int(raw: str | None, *, name: str) -> int | None:
    value = _as_float(raw, name=name)
    return None if value is None else int(value)


def load_budgets() -> Budgets:
    """Resolve budgets from the environment, with the operator file as fallback."""
    from_file = _budget_file_values()

    def get(name: str) -> str | None:
        return os.environ.get(name) or from_file.get(name)

    lock = (get(_ENV_LOCK) or "").strip().lower()
    return Budgets(
        soft_usd=_as_float(get(_ENV_SOFT_USD), name=_ENV_SOFT_USD),
        hard_usd=_as_float(get(_ENV_HARD_USD), name=_ENV_HARD_USD),
        hard_tokens=_as_int(get(_ENV_HARD_TOKENS), name=_ENV_HARD_TOKENS),
        run_usd=_as_float(get(_ENV_RUN_USD), name=_ENV_RUN_USD),
        locked=lock in ("1", "true", "yes", "on"),
    )


_budgets: Budgets | None = None


def budgets() -> Budgets:
    """The process-wide budgets, resolved on first use."""
    global _budgets
    if _budgets is None:
        _budgets = load_budgets()
    return _budgets


# --- totals ----------------------------------------------------------------


@dataclass
class Totals:
    calls: int = 0
    ok_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    est_usd: float = 0.0
    unpriced_calls: int = 0
    models: dict[str, int] = field(default_factory=dict)

    def add(self, event: dict) -> None:
        if event.get("kind") not in (None, "completion"):
            return
        self.calls += 1
        if event.get("ok"):
            self.ok_calls += 1
        prompt = event.get("prompt_tokens") or 0
        completion = event.get("completion_tokens") or 0
        total = event.get("total_tokens")
        self.prompt_tokens += int(prompt)
        self.completion_tokens += int(completion)
        self.total_tokens += int(total if total is not None else prompt + completion)
        usd = event.get("est_usd")
        if usd is None:
            self.unpriced_calls += 1
        else:
            self.est_usd += float(usd)
        model = event.get("model")
        if model:
            self.models[model] = self.models.get(model, 0) + 1


def _iter_events(path: str) -> Iterator[dict]:
    """Yield the parsed events in one day file. Malformed lines are skipped."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                yield event


def read_events(days: int = 1) -> list[dict]:
    """Events from the last ``days`` UTC day files, oldest first."""
    start = datetime.now(timezone.utc)
    events: list[dict] = []
    for back in range(max(days, 1) - 1, -1, -1):
        day = (start - timedelta(days=back)).strftime("%Y-%m-%d")
        path = day_path(day)
        if not os.path.exists(path):
            continue
        events.extend(_iter_events(path))
    return events


def totals(days: int = 1) -> Totals:
    """Aggregate totals over the last ``days`` UTC day files."""
    out = Totals()
    for event in read_events(days):
        out.add(event)
    return out


# The running view of today's ledger. Kept as a byte cursor so a long batch
# folds in only what is new, including events other processes appended.
@dataclass
class _Cursor:
    day: str
    offset: int = 0
    day_totals: Totals = field(default_factory=Totals)
    run_totals: dict[str, Totals] = field(default_factory=dict)


_cursor: _Cursor | None = None


def _refresh_cursor() -> _Cursor:
    """Fold any new ledger lines into the cached totals. May raise OSError."""
    global _cursor
    day = today()
    if _cursor is None or _cursor.day != day:
        # A run that crosses midnight keeps its own total; the day resets.
        carried = _cursor.run_totals if _cursor is not None else {}
        _cursor = _Cursor(day=day, run_totals=carried)
    cursor = _cursor
    path = day_path(day)
    if not os.path.exists(path):
        cursor.offset = 0
        return cursor
    size = os.path.getsize(path)
    if size < cursor.offset:  # rotated or truncated underneath us
        cursor.offset = 0
        cursor.day_totals = Totals()
    if size == cursor.offset:
        return cursor
    with open(path, encoding="utf-8") as fh:
        fh.seek(cursor.offset)
        for line in fh:
            if not line.endswith("\n"):  # a partial append; re-read it next time
                break
            cursor.offset += len(line.encode("utf-8"))
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            cursor.day_totals.add(event)
            rid = event.get("run_id")
            if rid:
                cursor.run_totals.setdefault(str(rid), Totals()).add(event)
    return cursor


# --- the gate --------------------------------------------------------------

_soft_warned = False
_unpriced_warned: set[str] = set()
_ledger_warned = False


def _warn(message: str) -> None:
    print(f"pgrep usage: {message}", file=sys.stderr)


def check_budget(model: str = "") -> None:
    """Refuse the next paid call when a cap is already reached.

    Raises :class:`BudgetExceeded` (or :class:`LedgerUnavailable`) when the call
    must not proceed. Soft caps only warn, once per process.
    """
    global _soft_warned
    limits = budgets()
    if limits.locked:
        raise BudgetExceeded(
            f"{_ENV_LOCK} is set; paid model calls are disabled. "
            "Unset it to allow spending."
        )
    if not limits.configured:
        return
    with _lock:
        try:
            cursor = _refresh_cursor()
        except OSError as exc:
            if limits.any_hard:
                raise LedgerUnavailable(
                    f"cannot read the usage ledger at {day_path()} ({exc}); "
                    "refusing the call because a hard cap is set"
                ) from exc
            return
        spent = cursor.day_totals.est_usd
        tokens = cursor.day_totals.total_tokens
        rid = run_id()
        run_spent = cursor.run_totals[rid].est_usd if rid in cursor.run_totals else 0.0

    if limits.hard_usd is not None and spent >= limits.hard_usd:
        raise BudgetExceeded(
            f"daily estimated spend ${spent:.2f} has reached the "
            f"{_ENV_HARD_USD} cap of ${limits.hard_usd:.2f}"
        )
    if limits.hard_tokens is not None and tokens >= limits.hard_tokens:
        raise BudgetExceeded(
            f"daily token use {tokens} has reached the "
            f"{_ENV_HARD_TOKENS} cap of {limits.hard_tokens}"
        )
    if limits.run_usd is not None and run_spent >= limits.run_usd:
        raise BudgetExceeded(
            f"run {run_id()!r} estimated spend ${run_spent:.2f} has reached the "
            f"{_ENV_RUN_USD} cap of ${limits.run_usd:.2f}"
        )
    if limits.soft_usd is not None and spent >= limits.soft_usd and not _soft_warned:
        _soft_warned = True
        _warn(
            f"daily estimated spend ${spent:.2f} passed the soft cap of "
            f"${limits.soft_usd:.2f}; continuing"
        )
        _record_event({"kind": "budget_soft", "est_usd_to_date": round(spent, 6)})
    if limits.hard_usd is not None and model and family_for(model) is None:
        if model not in _unpriced_warned:
            _unpriced_warned.add(model)
            _warn(
                f"no price entry for {model!r}: its tokens are recorded but its "
                f"cost is not, so {_ENV_HARD_USD} cannot bound it. Add it to "
                f"usage_prices.PRICES or set {_ENV_HARD_TOKENS}."
            )


# --- recording -------------------------------------------------------------


def _record_event(extra: dict) -> None:
    """Append one event. Raises OSError when the ledger cannot be written."""
    event: dict = {
        "schema": LEDGER_SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "completion",
    }
    rid, tool = run_id(), tool_name()
    if rid:
        event["run_id"] = rid
    if tool:
        event["tool"] = tool
    event.update(extra)
    directory = ledger_dir()
    os.makedirs(directory, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    with open(day_path(), "a", encoding="utf-8") as fh:
        fh.write(line)


def _base_url_host() -> str | None:
    """Hostname of ``OPENAI_BASE_URL``, never the path or the key."""
    raw = os.environ.get("OPENAI_BASE_URL")
    if not raw:
        return None
    try:
        return urlparse(raw).hostname
    except ValueError:
        return None


def usage_from_response(resp: object) -> tuple[int | None, int | None, int | None]:
    """Prompt/completion/total tokens off an OpenAI-shaped response, if present."""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return (None, None, None)

    def field_value(name: str) -> int | None:
        value = getattr(usage, name, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(name)
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

    return (
        field_value("prompt_tokens"),
        field_value("completion_tokens"),
        field_value("total_tokens"),
    )


def record(
    *,
    model: str,
    ok: bool,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    pinned: bool | None = None,
    error: str | None = None,
) -> None:
    """Record one completion attempt.

    Never raises for an ordinary write failure -- a paid call that already
    happened should not also lose its result. The exception is the fail-closed
    rule: with a hard cap set, an unwritable ledger means the *next* call would
    run blind, so the failure is raised.
    """
    if total_tokens is None and (
        prompt_tokens is not None or completion_tokens is not None
    ):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
    event = {
        "model": model,
        "ok": ok,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "est_usd": estimate_usd(model, prompt_tokens, completion_tokens),
        "base_url_host": _base_url_host(),
    }
    if pinned is not None:
        event["pinned"] = pinned
    if error:
        event["error"] = error  # exception class name only, never a message
    global _ledger_warned
    try:
        with _lock:
            _record_event(event)
    except OSError as exc:
        if budgets().any_hard:
            raise LedgerUnavailable(
                f"cannot write the usage ledger at {day_path()} ({exc}); "
                "refusing to continue because a hard cap is set"
            ) from exc
        if not _ledger_warned:
            _ledger_warned = True
            _warn(f"cannot write the usage ledger at {day_path()} ({exc}); continuing")


def reset() -> None:
    """Drop cached budgets and ledger cursor. For tests and long-lived hosts."""
    global _budgets, _cursor, _soft_warned, _ledger_warned
    with _lock:
        _budgets = None
        _cursor = None
        _soft_warned = False
        _ledger_warned = False
        _unpriced_warned.clear()
