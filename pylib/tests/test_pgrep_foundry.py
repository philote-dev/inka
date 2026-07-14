# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from anki.pgrep.ai import foundry_loop


class FakeVerdict:
    def __init__(self, decision):
        self.decision = decision

    def to_dict(self):
        return {"decision": self.decision, "checks": []}

    def reasons(self):
        return ["key: disagree"] if self.decision == "reject" else []


class FakePanel:
    def __init__(self, decisions):
        self._decisions = list(decisions)

    def check(self, problem):
        return FakeVerdict(self._decisions.pop(0))


def test_run_slot_partitions_accept_reject_escalate():
    items = [
        {"id": "1", "key": "A", "choices": ["a"] * 5, "stem": "s"},
        {"id": "2", "key": "B", "choices": ["a"] * 5, "stem": "s"},
        {"id": "3", "key": "C", "choices": ["a"] * 5, "stem": "s"},
    ]
    generated = iter(items)

    result = foundry_loop.run_slot(
        {"topic": "classical_mechanics"},
        generate_fn=lambda slot: next(generated),
        verifier=FakePanel(["accept", "reject", "escalate"]),
        n=3,
        seed=0,
    )

    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert len(result.escalated) == 1
    assert result.accepted[0]["correct"] == "A"
    assert result.rejected[0]["panel"]["decision"] == "reject"
    assert result.rejected[0]["reason"] == "key: disagree"
    assert result.escalated[0]["panel"]["decision"] == "escalate"
    assert result.yield_rate == 1 / 3


def test_run_slot_rejects_refusal_without_calling_panel():
    result = foundry_loop.run_slot(
        {"topic": "optics"},
        generate_fn=lambda slot: {
            "refused": True,
            "refusal_reason": "missing source",
        },
        verifier=FakePanel([]),
        n=1,
    )

    assert result.rejected == [
        {
            "refused": True,
            "refusal_reason": "missing source",
            "panel": {"decision": "reject", "checks": []},
            "reason": "missing source",
        }
    ]
    assert result.yield_rate == 0.0


def test_max_n_caps_by_verifier_accuracy():
    assert foundry_loop.max_n_for_accuracy(0.5) == 2
    assert foundry_loop.max_n_for_accuracy(0.9) >= 4
    assert foundry_loop.max_n_for_accuracy(0.99) == 8
