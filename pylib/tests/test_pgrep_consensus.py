# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from anki.pgrep.ai import consensus


class FakeClient:
    """Returns queued JSON strings; records the payloads it was asked to solve."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.seen = []

    def complete_text(self, system, user, *, json_object=False):
        self.seen.append(user)
        return self._replies.pop(0)


def _problem(correct="D"):
    return {
        "id": "p",
        "kind": "computational",
        "stem": "A car rises to height above a loop of radius R.",
        "choices": ["h = R/2", "h = 3R/2", "h = 2R", "h = 5R/2", "h = 3R"],
        "correct": correct,
    }


def test_solve_once_maps_shuffled_letter_back_to_original():
    # Display order puts original index 3 (letter D) into display slot A.
    order = [3, 0, 1, 2, 4]
    client = FakeClient(
        ['{"answer": "A", "reasoning": "energy + contact", "confidence": 0.9}']
    )
    solve = consensus.solve_once(client, _problem(), order=order)
    assert solve.letter == "D"  # display A -> original D
    assert solve.confidence == 0.9
    payload = client.seen[0]
    assert "correct" not in payload  # the stored key is never shown to the solver
    assert "A. h = 5R/2" in payload  # original option D is presented in display slot A


def test_majority_picks_the_mode():
    assert consensus._majority(["D", "D", "B"]) == "D"
    assert consensus._majority([]) == ""
