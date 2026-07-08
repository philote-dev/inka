# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The verifier panel (WS1).

Composes the answer-key consensus with the existing single-check judges into one
accept / reject / escalate decision. A hard check that fails with confidence at
or above ``certain`` rejects; any hard check below ``certain`` escalates;
otherwise the panel accepts. Soft checks annotate the verdict but never change
the decision in Phase 1. The panel is fully injectable, so tests pass stubs and
nothing here calls a model directly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from . import consensus as consensus_mod
from .judge import (
    DistractorVerdict,
    FigureVerdict,
    GiveawayVerdict,
    _extract_svg,
    _strip_figure,
)

_HARD = "hard"
_SOFT = "soft"


class _Judge(Protocol):
    def figure_fidelity(self, stem: str, svg: str) -> FigureVerdict: ...
    def technique_giveaway(self, problem: dict) -> GiveawayVerdict: ...
    def distractor_plausibility(self, problem: dict) -> DistractorVerdict: ...


@dataclass
class CheckVerdict:
    name: str
    severity: str
    passed: bool
    confidence: float
    evidence: str = ""


@dataclass
class Thresholds:
    certain: float = 0.8

    @classmethod
    def from_dict(cls, d: dict) -> Thresholds:
        return cls(certain=float(d.get("certain", 0.8)))

    def to_dict(self) -> dict:
        return {"certain": self.certain}


@dataclass
class PanelVerdict:
    decision: str
    checks: list[CheckVerdict] = field(default_factory=list)

    def hard_failures(self) -> list[CheckVerdict]:
        return [c for c in self.checks if c.severity == _HARD and not c.passed]

    def reasons(self) -> list[str]:
        return [f"{c.name}: {c.evidence}" for c in self.hard_failures()]

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "checks": [c.__dict__ for c in self.checks],
        }


class Verifier:
    """Runs the check panel over one problem and renders accept/reject/escalate."""

    def __init__(
        self,
        *,
        judge: _Judge,
        solve_clients: Sequence[consensus_mod._Client] | None = None,
        backward_client: consensus_mod._Client | None = None,
        key_consensus: Callable[..., consensus_mod.KeyConsensus] | None = None,
        thresholds: Thresholds | None = None,
    ) -> None:
        self.judge = judge
        self.solve_clients: Sequence[consensus_mod._Client] = solve_clients or []
        self.backward_client = backward_client
        self._key_consensus = key_consensus or consensus_mod.key_consensus
        self.thresholds = thresholds or Thresholds()

    def check(self, problem: dict) -> PanelVerdict:
        checks = [self._key_check(problem)]
        svg = _extract_svg(problem.get("stem", ""))
        if svg:
            checks.append(self._figure_check(problem, svg))
        checks.append(self._giveaway_check(problem))
        checks.append(self._distractor_check(problem))
        return PanelVerdict(self._decide(checks), checks)

    def _decide(self, checks: list[CheckVerdict]) -> str:
        hard = [c for c in checks if c.severity == _HARD]
        if any(
            (not c.passed) and c.confidence >= self.thresholds.certain for c in hard
        ):
            return "reject"
        if any(c.confidence < self.thresholds.certain for c in hard):
            return "escalate"
        return "accept"

    def _key_check(self, problem: dict) -> CheckVerdict:
        kc = self._key_consensus(
            problem, self.solve_clients, backward_client=self.backward_client
        )
        ev = (
            ""
            if kc.accepted
            else (
                f"solves say {kc.predicted or '?'} vs stored {kc.stored} "
                f"({kc.agree_count}/{kc.n}, stable={kc.stable}, "
                f"sympy={kc.sympy_ok}, backward={kc.backward_ok})"
            )
        )
        return CheckVerdict("key", _HARD, kc.accepted, kc.confidence, ev)

    def _figure_check(self, problem: dict, svg: str) -> CheckVerdict:
        v = self.judge.figure_fidelity(_strip_figure(problem.get("stem", "")), svg)
        passed = v.matches and not v.has_numbers
        gaps = len(v.missing) + len(v.contradictions) + (1 if v.has_numbers else 0)
        confidence = 0.9 if gaps == 0 else min(0.95, 0.6 + 0.15 * gaps)
        ev = "; ".join(v.missing + v.contradictions) or (
            "numbers in figure" if v.has_numbers else ""
        )
        return CheckVerdict("figure", _HARD, passed, confidence, ev)

    def _giveaway_check(self, problem: dict) -> CheckVerdict:
        v = self.judge.technique_giveaway(problem)
        confidence = 0.9 if v.severity == "high" else 0.6
        return CheckVerdict("giveaway", _SOFT, not v.gives_away, confidence, v.what)

    def _distractor_check(self, problem: dict) -> CheckVerdict:
        v = self.judge.distractor_plausibility(problem)
        passed = not v.implausible_labels
        return CheckVerdict(
            "distractor", _SOFT, passed, 0.7, ",".join(v.implausible_labels)
        )
