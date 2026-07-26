# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the AI usage ledger, budgets and kill switch (WS10).

Nothing here touches the network or needs ``openai`` installed: the ledger is
plain JSONL and the gate is pure arithmetic over it. Every test runs against a
temporary ledger directory so the repo's ``content/run/`` tree is never touched.

The file runs under pytest and also directly as a script
(``python3 pylib/tests/test_pgrep_usage.py``) for environments without a built
``anki``.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The offline AI core imports as ``pgrep.ai.*`` with pylib/anki appended (never
# prepended: it holds stdlib-named modules).
_AI_CORE = REPO / "pylib" / "anki"
if _AI_CORE.is_dir() and str(_AI_CORE) not in sys.path:
    sys.path.append(str(_AI_CORE))

from pgrep.ai import usage, usage_prices  # type: ignore[import-not-found]  # noqa: E402

_ENV_KEYS = (
    "PGREP_USAGE_DIR",
    "PGREP_USAGE_RUN_ID",
    "PGREP_USAGE_TOOL",
    "PGREP_BUDGET_SOFT_USD",
    "PGREP_BUDGET_HARD_USD",
    "PGREP_BUDGET_HARD_TOKENS",
    "PGREP_BUDGET_RUN_USD",
    "PGREP_AI_SPEND_LOCK",
    "OPENAI_BASE_URL",
)


@contextlib.contextmanager
def _sandbox(**env: object):
    """A temporary ledger directory and a clean budget environment."""
    saved = {key: os.environ.get(key) for key in _ENV_KEYS}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            for key in _ENV_KEYS:
                os.environ.pop(key, None)
            os.environ["PGREP_USAGE_DIR"] = tmp
            for key, value in env.items():
                os.environ[key] = str(value)
            usage.reset()
            yield tmp
        finally:
            usage.reset()
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


@contextlib.contextmanager
def _raises(exc):
    caught = False
    try:
        yield
    except exc:
        caught = True
    if not caught:
        raise AssertionError(f"expected {exc.__name__}")


def _events() -> list[dict]:
    path = usage.day_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _append_foreign_event(**fields: object) -> None:
    """Write a ledger line as if another process had produced it."""
    event = {"schema": usage.LEDGER_SCHEMA, "kind": "completion", "ok": True}
    event.update(fields)
    os.makedirs(usage.ledger_dir(), exist_ok=True)
    with open(usage.day_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def _block_ledger_file() -> None:
    """Make today's ledger path unusable for both reads and writes."""
    os.makedirs(usage.day_path(), exist_ok=True)  # a directory, not a file


# --- prices ----------------------------------------------------------------


def test_family_for_prefers_the_longest_prefix():
    assert usage_prices.family_for("gpt-5.4-mini-2026-02-02") == "gpt-5.4-mini"
    assert usage_prices.family_for("gpt-5.4-2026-02-02") == "gpt-5.4"
    assert usage_prices.family_for("claude-opus-4-8") == "claude-opus-4-8"


def test_family_for_returns_none_when_unpriced():
    assert usage_prices.family_for("some-unknown-model") is None
    assert usage_prices.family_for("") is None


def test_estimate_usd_splits_input_and_output_rates():
    # gpt-5.5 is $1.25/1M in and $10/1M out.
    assert usage_prices.estimate_usd("gpt-5.5", 1_000_000, 0) == 1.25
    assert usage_prices.estimate_usd("gpt-5.5", 0, 1_000_000) == 10.0
    assert usage_prices.estimate_usd("unknown-model", 1_000_000, 0) is None


def test_estimate_usd_treats_missing_counts_as_zero():
    assert usage_prices.estimate_usd("gpt-5.5", None, None) == 0.0


# --- recording -------------------------------------------------------------


def test_record_writes_one_priced_event():
    with _sandbox(OPENAI_BASE_URL="https://tfy.example/api/llm/v1"):
        os.environ["PGREP_USAGE_RUN_ID"] = "run-1"
        os.environ["PGREP_USAGE_TOOL"] = "foundry"
        usage.record(
            model="gpt-5.5", ok=True, prompt_tokens=1000, completion_tokens=500
        )
        events = _events()
    assert len(events) == 1
    event = events[0]
    assert event["model"] == "gpt-5.5"
    assert event["ok"] is True
    assert event["total_tokens"] == 1500
    assert event["run_id"] == "run-1"
    assert event["tool"] == "foundry"
    assert abs(event["est_usd"] - (1000 * 1.25 + 500 * 10.0) / 1e6) < 1e-12


def test_event_records_only_the_host_of_the_base_url():
    with _sandbox(OPENAI_BASE_URL="https://tfy.example/api/llm/v1?token=secret"):
        usage.record(model="gpt-5.5", ok=True, prompt_tokens=1, completion_tokens=1)
        event = _events()[0]
    assert event["base_url_host"] == "tfy.example"
    # no path, no query, nothing that could carry a credential
    assert "secret" not in json.dumps(event)
    assert "/api/" not in json.dumps(event)


def test_unpriced_model_records_tokens_with_a_null_estimate():
    with _sandbox():
        usage.record(
            model="mystery-model", ok=True, prompt_tokens=800, completion_tokens=200
        )
        event = _events()[0]
    assert event["est_usd"] is None
    assert event["total_tokens"] == 1000


def test_failure_event_records_the_error_class_only():
    with _sandbox():
        usage.record(model="gpt-5.5", ok=False, error="APIConnectionError")
        event = _events()[0]
    assert event["ok"] is False
    assert event["error"] == "APIConnectionError"
    assert event["total_tokens"] is None


def test_usage_from_response_reads_object_and_dict_shapes():
    import types

    resp = types.SimpleNamespace(
        usage=types.SimpleNamespace(
            prompt_tokens=11, completion_tokens=22, total_tokens=33
        )
    )
    assert usage.usage_from_response(resp) == (11, 22, 33)
    assert usage.usage_from_response(types.SimpleNamespace()) == (None, None, None)
    assert usage.usage_from_response(None) == (None, None, None)


# --- the gate --------------------------------------------------------------


def test_no_caps_configured_means_no_gate():
    with _sandbox():
        usage.check_budget("gpt-5.5")  # must not raise, must not need a ledger


def test_spend_lock_blocks_before_anything_else():
    with _sandbox(PGREP_AI_SPEND_LOCK="1"), _raises(usage.BudgetExceeded):
        usage.check_budget("gpt-5.5")


def test_hard_usd_cap_blocks_the_next_call():
    with _sandbox(PGREP_BUDGET_HARD_USD="1.00"):
        usage.check_budget("gpt-5.5")  # nothing spent yet
        # 200k output tokens on gpt-5.5 is $2.00, over the cap.
        usage.record(
            model="gpt-5.5", ok=True, prompt_tokens=0, completion_tokens=200_000
        )
        with _raises(usage.BudgetExceeded):
            usage.check_budget("gpt-5.5")


def test_hard_token_cap_bounds_an_unpriced_model():
    with _sandbox(PGREP_BUDGET_HARD_TOKENS="5000"):
        usage.record(
            model="mystery-model", ok=True, prompt_tokens=4000, completion_tokens=2000
        )
        with _raises(usage.BudgetExceeded):
            usage.check_budget("mystery-model")


def test_run_cap_is_scoped_to_one_run():
    with _sandbox(PGREP_BUDGET_RUN_USD="1.00"):
        os.environ["PGREP_USAGE_RUN_ID"] = "run-a"
        usage.record(
            model="gpt-5.5", ok=True, prompt_tokens=0, completion_tokens=200_000
        )
        with _raises(usage.BudgetExceeded):
            usage.check_budget("gpt-5.5")
        # a different run starts from zero
        os.environ["PGREP_USAGE_RUN_ID"] = "run-b"
        usage.check_budget("gpt-5.5")


def test_soft_cap_warns_but_does_not_block():
    with _sandbox(PGREP_BUDGET_SOFT_USD="0.50"):
        usage.record(
            model="gpt-5.5", ok=True, prompt_tokens=0, completion_tokens=200_000
        )
        usage.check_budget("gpt-5.5")  # must not raise
        kinds = [event.get("kind") for event in _events()]
    assert "budget_soft" in kinds


def test_gate_counts_spend_appended_by_another_process():
    with _sandbox(PGREP_BUDGET_HARD_USD="5.00"):
        usage.check_budget("gpt-5.5")
        _append_foreign_event(model="gpt-5.5", est_usd=6.0, total_tokens=10)
        with _raises(usage.BudgetExceeded):
            usage.check_budget("gpt-5.5")


def test_totals_accumulate_across_successive_appends():
    with _sandbox(PGREP_BUDGET_HARD_USD="100"):
        for _ in range(3):
            usage.record(
                model="gpt-5.5", ok=True, prompt_tokens=1000, completion_tokens=1000
            )
            usage.check_budget("gpt-5.5")
        totals = usage.totals(1)
    assert totals.calls == 3
    assert totals.total_tokens == 6000
    assert abs(totals.est_usd - 3 * (1000 * 1.25 + 1000 * 10.0) / 1e6) < 1e-12


def test_malformed_ledger_lines_are_skipped():
    with _sandbox():
        os.makedirs(usage.ledger_dir(), exist_ok=True)
        with open(usage.day_path(), "a", encoding="utf-8") as fh:
            fh.write("not json\n")
        _append_foreign_event(model="gpt-5.5", est_usd=1.0, total_tokens=5)
        totals = usage.totals(1)
    assert totals.calls == 1


# --- fail-closed -----------------------------------------------------------


def test_unreadable_ledger_with_a_hard_cap_fails_closed():
    with _sandbox(PGREP_BUDGET_HARD_USD="10"):
        _block_ledger_file()
        with _raises(usage.LedgerUnavailable):
            usage.check_budget("gpt-5.5")


def test_unwritable_ledger_with_a_hard_cap_fails_closed():
    with _sandbox(PGREP_BUDGET_HARD_USD="10"):
        _block_ledger_file()
        with _raises(usage.LedgerUnavailable):
            usage.record(model="gpt-5.5", ok=True, prompt_tokens=1, completion_tokens=1)


def test_unwritable_ledger_without_caps_only_warns():
    with _sandbox():
        _block_ledger_file()
        usage.record(model="gpt-5.5", ok=True, prompt_tokens=1, completion_tokens=1)
        usage.check_budget("gpt-5.5")


# --- budget resolution -----------------------------------------------------


def test_budget_file_supplies_caps_when_env_is_empty():
    with _sandbox() as tmp:
        with open(os.path.join(tmp, usage.BUDGET_FILE), "w", encoding="utf-8") as fh:
            fh.write('# operator caps\nPGREP_BUDGET_HARD_USD="7.50"\n')
        usage.reset()
        assert usage.budgets().hard_usd == 7.50


def test_environment_overrides_the_budget_file():
    with _sandbox(PGREP_BUDGET_HARD_USD="1.00") as tmp:
        with open(os.path.join(tmp, usage.BUDGET_FILE), "w", encoding="utf-8") as fh:
            fh.write("PGREP_BUDGET_HARD_USD=99\n")
        usage.reset()
        assert usage.budgets().hard_usd == 1.00


def test_a_malformed_cap_is_rejected_loudly():
    with _sandbox(PGREP_BUDGET_HARD_USD="lots"), _raises(ValueError):
        usage.budgets()


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
