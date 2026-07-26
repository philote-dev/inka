# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Prove the usage ledger and the spend cap work against the real gateway (WS10).

Makes one deliberately tiny completion and checks that it landed in the ledger
with token counts. This is the network counterpart to the offline tests: it is
the check that the seam is really wired to the provider being billed.

    just usage-smoke                          # expect exit 0, one new event
    PGREP_BUDGET_HARD_USD=0 just usage-smoke  # expect nonzero, no call made

Needs a gateway credential; it spends a fraction of a cent.
"""

from __future__ import annotations

import argparse
import sys

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import llm, usage  # type: ignore[import-not-found]  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="gpt-5.4-mini",
        help="gateway model id to call (default: the cheap one)",
    )
    args = parser.parse_args()

    llm.load_api_key()
    if not llm.has_api_key():
        print(
            "no gateway credential; set up ~/.config/truefoundry/gateway.env",
            file=sys.stderr,
        )
        return 2

    before = len(usage.read_events(1))
    try:
        client = llm.LLMClient(args.model)
        text = client.complete_text("Reply with the single word ok.", "ok?")
    except usage.BudgetExceeded as exc:
        print(f"refused by the spend gate: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    events = usage.read_events(1)
    new = events[before:]
    if not new:
        print("call succeeded but nothing was recorded in the ledger", file=sys.stderr)
        return 1
    event = new[-1]
    print(f"reply: {text.strip()[:40]!r}")
    print(f"ledger: {usage.day_path()}")
    print(
        f"  model={event.get('model')} pinned={event.get('pinned')} "
        f"tokens={event.get('total_tokens')} est_usd={event.get('est_usd')} "
        f"host={event.get('base_url_host')}"
    )
    if event.get("total_tokens") is None:
        print(
            "  warning: the provider returned no usage object, so token counts "
            "and the USD cap cannot see this call",
            file=sys.stderr,
        )
    if event.get("est_usd") is None:
        print(
            f"  warning: no price entry for {event.get('model')!r}; add it to "
            "pylib/anki/pgrep/ai/usage_prices.py so the USD cap can bound it",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
