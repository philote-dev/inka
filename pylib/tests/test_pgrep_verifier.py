# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from anki.pgrep.ai import verifier
from anki.pgrep.ai.consensus import KeyConsensus


class StubJudge:
    """Stands in for Judge; returns fixed verdicts (structurally a _Judge)."""

    def __init__(self, figure=None, giveaway=None, distractor=None):
        from anki.pgrep.ai.judge import (
            DistractorVerdict,
            FigureVerdict,
            GiveawayVerdict,
        )

        self._figure = figure or FigureVerdict(matches=True)
        self._giveaway = giveaway or GiveawayVerdict(gives_away=False)
        self._distractor = distractor or DistractorVerdict()

    def figure_fidelity(self, stem, svg):
        return self._figure

    def technique_giveaway(self, problem):
        return self._giveaway

    def distractor_plausibility(self, problem):
        return self._distractor


class StubConsensus:
    def __init__(self, kc):
        self.kc = kc

    def __call__(self, problem, clients, **kw):
        return self.kc


def _problem():
    return {
        "id": "p",
        "kind": "computational",
        "stem": "no figure here",
        "choices": ["a", "b", "c", "d", "e"],
        "correct": "D",
        "distractors": [],
    }


def _kc(accepted, conf):
    return KeyConsensus(
        accepted, "D", "D", 3, 3, True, None, None, conf, ["D", "D", "D"]
    )


def test_accepts_when_all_hard_checks_certain_pass():
    v = verifier.Verifier(
        judge=StubJudge(), key_consensus=StubConsensus(_kc(True, 0.95))
    )
    assert v.check(_problem()).decision == "accept"


def test_rejects_on_certain_key_failure():
    v = verifier.Verifier(
        judge=StubJudge(), key_consensus=StubConsensus(_kc(False, 0.95))
    )
    pv = v.check(_problem())
    assert pv.decision == "reject"
    assert any("key" in r for r in pv.reasons())


def test_escalates_on_uncertain_key():
    v = verifier.Verifier(
        judge=StubJudge(), key_consensus=StubConsensus(_kc(True, 0.66))
    )
    assert v.check(_problem()).decision == "escalate"


def test_soft_distractor_flag_annotates_but_does_not_reject():
    from anki.pgrep.ai.judge import DistractorVerdict

    j = StubJudge(distractor=DistractorVerdict(implausible_labels=["A"]))
    v = verifier.Verifier(judge=j, key_consensus=StubConsensus(_kc(True, 0.95)))
    pv = v.check(_problem())
    assert pv.decision == "accept"
    assert any(c.name == "distractor" and not c.passed for c in pv.checks)


def _figure_problem():
    return {
        "id": "pf",
        "kind": "computational",
        "stem": 'Look. <div class="pg-figure"><svg><line/></svg></div>',
        "choices": ["a", "b", "c", "d", "e"],
        "correct": "D",
        "distractors": [],
    }


def test_clean_figure_accepts():
    from anki.pgrep.ai.judge import FigureVerdict

    j = StubJudge(figure=FigureVerdict(matches=True))
    v = verifier.Verifier(judge=j, key_consensus=StubConsensus(_kc(True, 0.95)))
    pv = v.check(_figure_problem())
    assert pv.decision == "accept"
    assert any(c.name == "figure" and c.passed for c in pv.checks)


def test_single_gap_figure_escalates():
    from anki.pgrep.ai.judge import FigureVerdict

    j = StubJudge(figure=FigureVerdict(matches=False, missing=["a plane"]))
    v = verifier.Verifier(judge=j, key_consensus=StubConsensus(_kc(True, 0.95)))
    # one gap -> confidence 0.75 < certain (0.8) -> escalate, not reject
    assert v.check(_figure_problem()).decision == "escalate"


def test_multi_gap_figure_rejects():
    from anki.pgrep.ai.judge import FigureVerdict

    j = StubJudge(
        figure=FigureVerdict(matches=False, missing=["a plane"], contradictions=["b"])
    )
    v = verifier.Verifier(judge=j, key_consensus=StubConsensus(_kc(True, 0.95)))
    pv = v.check(_figure_problem())
    # two gaps -> confidence 0.9 >= certain -> reject
    assert pv.decision == "reject"
    assert any("figure" in r for r in pv.reasons())
