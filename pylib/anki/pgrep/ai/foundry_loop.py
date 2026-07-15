# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Best-of-N foundry partition helpers (WS7). Pure; no network."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class _Verifier(Protocol):
    def check(self, problem: dict) -> Any: ...


@dataclass
class SlotResult:
    accepted: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    escalated: list[dict] = field(default_factory=list)

    @property
    def yield_rate(self) -> float:
        total = len(self.accepted) + len(self.rejected) + len(self.escalated)
        return len(self.accepted) / total if total else 0.0


def summarize_runs(results: list[SlotResult]) -> dict:
    """Aggregate foundry partitions into counts and operator-facing rates."""
    accepted = sum(len(result.accepted) for result in results)
    rejected = sum(len(result.rejected) for result in results)
    escalated = sum(len(result.escalated) for result in results)
    candidates = accepted + rejected + escalated
    return {
        "candidates": candidates,
        "accepted": accepted,
        "rejected": rejected,
        "escalated": escalated,
        "yield_rate": accepted / candidates if candidates else 0.0,
        "escalation_rate": escalated / candidates if candidates else 0.0,
    }


def max_n_for_accuracy(accuracy: float, *, floor: int = 2, ceiling: int = 8) -> int:
    """Cap N so a weak verifier cannot over-prune a large candidate set."""
    if accuracy < 0.6:
        return floor
    if accuracy < 0.8:
        return max(floor, min(ceiling, 4))
    if accuracy < 0.95:
        return max(floor, min(ceiling, 6))
    return ceiling


def _normalize(item: dict) -> dict:
    normalized = dict(item)
    if "correct" not in normalized and normalized.get("key"):
        normalized["correct"] = normalized["key"]
    return normalized


def run_slot(
    slot: dict,
    *,
    generate_fn: Callable[[dict], dict],
    verifier: _Verifier,
    n: int,
    seed: int = 0,
) -> SlotResult:
    result = SlotResult()
    for index in range(max(0, n)):
        raw = generate_fn(slot)
        if raw.get("refused"):
            reason = raw.get("refusal_reason", "refused")
            result.rejected.append(
                {
                    **raw,
                    "refused": True,
                    "panel": {
                        "decision": "reject",
                        "checks": [],
                        "refusal": True,
                    },
                    "reason": reason,
                    "preference_exclusion_reason": f"panel refusal: {reason}",
                }
            )
            continue

        item = _normalize(raw)
        item["_foundry_seed"] = seed + index
        verdict = verifier.check(item)
        decision = getattr(verdict, "decision", "escalate")
        panel = (
            verdict.to_dict() if hasattr(verdict, "to_dict") else {"decision": decision}
        )
        reasons = verdict.reasons() if hasattr(verdict, "reasons") else []
        payload = {**item, "panel": panel, "reason": "; ".join(reasons)}
        if decision == "accept":
            result.accepted.append(payload)
        elif decision == "reject":
            result.rejected.append(payload)
        else:
            result.escalated.append(payload)
    return result
