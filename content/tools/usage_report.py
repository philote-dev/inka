# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Report what the AI pipeline has spent, from the local usage ledger (WS10).

Reads the JSONL day files under ``content/run/usage/`` that
:mod:`anki.pgrep.ai.usage` writes and summarises them by model, tool and run.
USD figures are local estimates from the hand-maintained price table, not
invoice numbers; the TrueFoundry dashboard remains the source of truth.

    python content/tools/usage_report.py --days 7
    python content/tools/usage_report.py --json
"""

from __future__ import annotations

import argparse
import json
import sys

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import usage  # type: ignore[import-not-found]  # noqa: E402


def _group(events: list[dict], key: str) -> dict[str, usage.Totals]:
    out: dict[str, usage.Totals] = {}
    for event in events:
        name = str(event.get(key) or "(unattributed)")
        out.setdefault(name, usage.Totals()).add(event)
    return out


def _usd(totals: usage.Totals) -> str:
    if totals.unpriced_calls and not totals.est_usd:
        return "unpriced"
    suffix = f" +{totals.unpriced_calls} unpriced" if totals.unpriced_calls else ""
    return f"${totals.est_usd:,.2f}{suffix}"


def _print_group(title: str, groups: dict[str, usage.Totals]) -> None:
    if not groups:
        return
    print(f"\n{title}")
    width = max(len(name) for name in groups)
    ranked = sorted(groups.items(), key=lambda kv: kv[1].est_usd, reverse=True)
    for name, totals in ranked:
        print(
            f"  {name:<{width}}  {totals.calls:>6} calls  "
            f"{totals.total_tokens:>12,} tok  {_usd(totals)}"
        )


def _as_dict(totals: usage.Totals) -> dict:
    return {
        "calls": totals.calls,
        "ok_calls": totals.ok_calls,
        "prompt_tokens": totals.prompt_tokens,
        "completion_tokens": totals.completion_tokens,
        "total_tokens": totals.total_tokens,
        "est_usd": round(totals.est_usd, 6),
        "unpriced_calls": totals.unpriced_calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=1, help="UTC days back to include (default today)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    events = usage.read_events(args.days)
    overall = usage.Totals()
    for event in events:
        overall.add(event)
    by_model = _group(events, "model")
    by_tool = _group(events, "tool")
    by_run = _group(events, "run_id")
    limits = usage.budgets()

    if args.json:
        print(
            json.dumps(
                {
                    "days": args.days,
                    "ledger_dir": usage.ledger_dir(),
                    "total": _as_dict(overall),
                    "by_model": {k: _as_dict(v) for k, v in by_model.items()},
                    "by_tool": {k: _as_dict(v) for k, v in by_tool.items()},
                    "by_run": {k: _as_dict(v) for k, v in by_run.items()},
                    "budgets": {
                        "soft_usd": limits.soft_usd,
                        "hard_usd": limits.hard_usd,
                        "hard_tokens": limits.hard_tokens,
                        "run_usd": limits.run_usd,
                        "locked": limits.locked,
                    },
                },
                indent=2,
            )
        )
        return 0

    span = "today" if args.days <= 1 else f"the last {args.days} days"
    print(f"pgrep AI usage over {span}  ({usage.ledger_dir()})")
    if not events:
        print("  no calls recorded")
        return 0
    print(
        f"  {overall.calls} calls ({overall.ok_calls} ok), "
        f"{overall.total_tokens:,} tokens, estimated {_usd(overall)}"
    )
    _print_group("by model", by_model)
    _print_group("by tool", by_tool)
    _print_group("by run", by_run)
    if limits.configured:
        print("\nbudgets in effect")
        for label, value in (
            ("soft daily USD", limits.soft_usd),
            ("hard daily USD", limits.hard_usd),
            ("hard daily tokens", limits.hard_tokens),
            ("per-run USD", limits.run_usd),
        ):
            if value is not None:
                print(f"  {label}: {value}")
        if limits.locked:
            print("  paid calls LOCKED OFF (PGREP_AI_SPEND_LOCK)")
    else:
        print("\nno budget caps set; export PGREP_BUDGET_HARD_USD before a paid batch")
    print("\nUSD figures are local estimates, not invoice numbers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
