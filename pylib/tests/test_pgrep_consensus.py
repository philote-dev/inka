# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import re

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


class SolverFake:
    """A content-based fake solver: always picks the option whose text equals
    ``answer_text``, whatever display slot the shuffle puts it in. Simulates a
    position-robust solver, so the shuffle-stability check sees a stable answer.
    Reusable across calls (no reply queue)."""

    def __init__(self, answer_text, confidence=0.9):
        self.answer_text = answer_text
        self.confidence = confidence
        self.seen = []

    def complete_text(self, system, user, *, json_object=False):
        self.seen.append(user)
        letter = "A"
        for line in user.splitlines():
            m = re.match(r"([A-E])\.\s*(.*)", line.strip())
            if m and m.group(2).strip() == self.answer_text:
                letter = m.group(1)
                break
        return '{"answer": "%s", "reasoning": "r", "confidence": %s}' % (
            letter,
            self.confidence,
        )


def test_unanimous_agreement_accepts_with_high_confidence():
    clients = [SolverFake("h = 5R/2") for _ in range(3)]  # original D
    kc = consensus.key_consensus(_problem("D"), clients, seed=0)
    assert kc.accepted is True
    assert kc.confidence >= 0.9
    assert kc.stable is True


def test_majority_on_a_different_letter_rejects_the_key():
    clients = [SolverFake("h = R/2") for _ in range(3)]  # original A, key is D
    kc = consensus.key_consensus(_problem("D"), clients, seed=0)
    assert kc.accepted is False
    assert kc.predicted == "A"
    assert kc.confidence >= 0.9


def test_bare_majority_is_accepted_but_low_confidence():
    clients = [SolverFake("h = 5R/2"), SolverFake("h = 5R/2"), SolverFake("h = 3R/2")]
    kc = consensus.key_consensus(_problem("D"), clients, seed=0)
    assert kc.accepted is True
    assert kc.confidence < 0.8  # 2/3 -> escalation band


def test_sympy_disproof_rejects_even_if_models_agree():
    import pytest

    pytest.importorskip("sympy")
    prob = _problem("D")
    prob["answer_expr"] = "2*R"
    prob["answer_value"] = 3.0  # 2R == 3 is false for R == 1
    prob["answer_subs"] = {"R": 1.0}
    clients = [SolverFake("h = 5R/2") for _ in range(3)]
    kc = consensus.key_consensus(prob, clients, use_sympy=True, seed=0)
    assert kc.sympy_ok is False
    assert kc.accepted is False


def test_backward_check_recovers_masked_value():
    prob = {
        "id": "p",
        "kind": "computational",
        "stem": "A mass travels 12 meters in the field.",
        "choices": ["1 J", "2 J", "3 J", "4 J", "5 J"],
        "correct": "C",
    }
    assert consensus.backward_check(FakeClient(['{"value": 12}']), prob, "C") is True
    assert consensus.backward_check(FakeClient(['{"value": 99}']), prob, "C") is False


def test_blank_solves_do_not_inflate_a_reject():
    # One real solve disagreeing with the key plus four failed calls is weak
    # evidence: it must NOT become a confident reject (it should escalate).
    clients = [SolverFake("h = R/2")] + [FakeClient(["{}"]) for _ in range(4)]
    kc = consensus.key_consensus(_problem("D"), clients, seed=0)
    assert kc.accepted is False
    assert kc.confidence < 0.8


def test_no_valid_solves_escalates():
    clients = [FakeClient(["{}"]) for _ in range(3)]
    kc = consensus.key_consensus(_problem("D"), clients, seed=0)
    assert kc.accepted is False
    assert kc.confidence == 0.0


def test_backward_disproof_rejects_via_key_consensus():
    prob = {
        "id": "p",
        "kind": "computational",
        "stem": "A 3 kg mass is pushed once.",
        "choices": ["1 J", "2 J", "3 J", "4 J", "5 J"],
        "correct": "C",
    }
    clients = [SolverFake("3 J") for _ in range(3)]  # models agree with the key
    back = FakeClient(['{"value": 999}'])  # but backward disproves it
    kc = consensus.key_consensus(prob, clients, backward_client=back, seed=0)
    assert kc.backward_ok is False
    assert kc.accepted is False
    assert kc.confidence == 0.85


def test_sympy_confirmation_accepts():
    import pytest

    pytest.importorskip("sympy")
    prob = _problem("D")
    prob["answer_expr"] = "2*R"
    prob["answer_value"] = 2.0  # 2R == 2 for R == 1
    prob["answer_subs"] = {"R": 1.0}
    clients = [SolverFake("h = 5R/2") for _ in range(3)]
    kc = consensus.key_consensus(prob, clients, use_sympy=True, seed=0)
    assert kc.sympy_ok is True
    assert kc.accepted is True
    assert kc.confidence == 0.99
