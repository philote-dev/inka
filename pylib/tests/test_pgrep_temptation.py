# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import json

from anki.pgrep.ai import temptation

_LETTERS = "ABCDE"


def _problem():
    return {
        "id": "p",
        "stem": "What is 2+2?",
        "choices": ["3", "4", "5", "6", "7"],
        "correct": "B",
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


def test_temptation_counts_weak_solver_picks_on_wrong_options():
    # Three weak solvers pick A, A, C. Correct is B.
    clients = [FakeClient("A"), FakeClient("A"), FakeClient("C")]
    report = temptation.score_distractors(_problem(), clients, seed=1)
    by_label = {s.label: s for s in report.scores}
    assert by_label["A"].temptation == 2 / 3
    assert by_label["C"].temptation == 1 / 3
    assert by_label["D"].temptation == 0.0
    assert "D" in report.free_elimination_labels
    assert "E" in report.free_elimination_labels
    assert "B" not in by_label  # correct option is not a distractor score


class FixedLetterClient:
    """Always returns one display letter, ignoring shuffle."""

    def __init__(self, letter: str):
        self.letter = letter

    def complete_text(self, system, user, *, json_object=False):
        return (
            f'{{"answer": "{self.letter}", "reasoning": "x", "confidence": 0.5}}'
        )


def test_out_of_range_display_letter_ignored():
    problem = {
        "id": "p",
        "stem": "Pick one.",
        "choices": ["a", "b", "c"],
        "correct": "B",
    }
    report = temptation.score_distractors(
        problem, [FixedLetterClient("E")], seed=1
    )
    assert all(s.selected_by == 0 and s.n_solvers == 0 for s in report.scores)


def test_select_distractors_keeps_most_tempting_wrong_options():
    # candidates are option dicts with label + text; correct excluded upstream
    cands = [
        {"label": "A", "text": "3"},
        {"label": "C", "text": "5"},
        {"label": "D", "text": "6"},
        {"label": "E", "text": "7"},
    ]
    # All weak solvers pick A -> A is most tempting
    clients = [FakeClient("A"), FakeClient("A")]
    problem = _problem()
    kept = temptation.select_distractors(
        cands, clients, k=2, seed=1, problem=problem
    )
    assert [d["label"] for d in kept][:1] == ["A"]
    assert len(kept) == 2
