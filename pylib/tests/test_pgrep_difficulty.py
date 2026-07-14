# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import json

from anki.pgrep.ai import difficulty

_LETTERS = "ABCDE"


def _problem(correct="B"):
    return {
        "stem": "q",
        "choices": ["a", "b", "c", "d", "e"],
        "correct": correct,
    }


class FakeClient:
    """Picks the display letter for a fixed original option after shuffle."""

    def __init__(self, letter: str, *, choices: list[str] | None = None):
        self.letter = letter
        self.choices = list(choices or _problem()["choices"])

    def complete_text(self, system, user, *, json_object=False):
        payload = json.loads(user)
        display_choices = list(payload.get("choices") or [])
        orig_i = _LETTERS.index(self.letter)
        orig_text = self.choices[orig_i]
        disp_i = display_choices.index(orig_text)
        display_letter = _LETTERS[disp_i]
        return (
            f'{{"answer": "{display_letter}", "reasoning": "x", "confidence": 0.5}}'
        )


def test_hard_band_when_weak_solvers_mostly_miss():
    clients = [FakeClient("A"), FakeClient("C"), FakeClient("D"), FakeClient("E")]
    est = difficulty.estimate_difficulty(_problem("B"), clients, seed=0)
    assert est.band == "hard"
    assert est.p_correct == 0.0
    assert est.out_of_band is True


def test_easy_band_when_weak_solvers_mostly_hit():
    clients = [FakeClient("B")] * 5
    est = difficulty.estimate_difficulty(_problem("B"), clients, seed=0)
    assert est.band == "easy"
    assert est.p_correct == 1.0
    assert est.out_of_band is True  # >= 0.95


def test_pearson_correlation_perfect_line():
    assert abs(difficulty.pearson_correlation([1, 2, 3], [2, 4, 6]) - 1.0) < 1e-9
