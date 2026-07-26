# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Approximate token prices for the models the content pipeline calls (WS10).

These rates drive the *local* USD estimate in :mod:`anki.pgrep.ai.usage`. They
are hand-maintained and deliberately approximate: the TrueFoundry dashboard
remains the invoice source of truth, and the ledger never claims to match it.
Their job is to make a runaway batch visible and stoppable while it runs.

Rates are USD per one million tokens, keyed by model *family*. A concrete model
id is matched to a family by longest-prefix match, so a dated snapshot
(``gpt-5.5-2026-04-23``) and the floating gateway id (``gpt-5.5``) price the
same. A model with no entry is not an error: the ledger records its tokens with
a null estimate, and only a token cap can bound it.

Operators should recalibrate ``PRICES`` against a real invoice; treat the
shipped numbers as placeholders good enough for a kill switch, not accounting.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens, split by direction."""

    input_usd: float
    output_usd: float


# Longest-prefix wins, so put families here in any order.
PRICES: dict[str, Price] = {
    # TrueFoundry portfolio (the locked model roles in the foundry design).
    "gpt-5.5": Price(1.25, 10.0),
    "gpt-5.4": Price(1.25, 10.0),
    "gpt-5.4-mini": Price(0.25, 2.0),
    "gpt-5": Price(1.25, 10.0),
    "claude-opus-4-8": Price(15.0, 75.0),
    "claude-haiku-4-5": Price(1.0, 5.0),
    "grok-4.5": Price(3.0, 15.0),
    # Older snapshots still referenced by archived run manifests.
    "gpt-4.1": Price(2.0, 8.0),
    "gpt-4o": Price(2.5, 10.0),
    "gpt-4o-mini": Price(0.15, 0.6),
}


def family_for(model: str) -> str | None:
    """The priced family a model id belongs to, or None when unpriced."""
    if not model:
        return None
    lowered = model.lower()
    best: str | None = None
    for family in PRICES:
        if lowered.startswith(family) and (best is None or len(family) > len(best)):
            best = family
    return best


def estimate_usd(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    """Estimated USD for one call, or None when the model has no price entry.

    Missing token counts are treated as zero so a half-reported response still
    produces a usable lower bound rather than nothing.
    """
    family = family_for(model)
    if family is None:
        return None
    price = PRICES[family]
    prompt = float(prompt_tokens or 0)
    completion = float(completion_tokens or 0)
    return (prompt * price.input_usd + completion * price.output_usd) / 1_000_000.0
