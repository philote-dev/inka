# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for forced card generation (L4.1).

Covers the AI-off invariant (author a seed, no heavy deps) and the AI-on
orchestration with retrieval and the LLM faked, so the whole flow runs under
``just test-py`` without fastembed, openai, or an index.
"""

from __future__ import annotations

from anki.pgrep import ai_config, generation
from anki.pgrep.ai import llm as llm_module
from tests.shared import getEmptyCol

_GROUNDED = [
    {"score": 0.82,
     "text": "The photon energy is E = h c / lambda, with hc about 1240 eV nm.",
     "source_ref": "OpenStax University Physics Volume 3, p. 254",
     "chunk_id": "openstax-vol3#p0254#c001",
     "source_title": "OpenStax University Physics Volume 3"}]


class _FakeLLM:
    def __init__(self, model, **_kw):
        self.model = model
        self.response = {
            "front": "Photon energy for wavelength lambda?",
            "back": "E = h c / lambda, with hc = 1240 eV nm and lambda in nm.",
            "card_kind": "conceptual", "difficulty": 0.4, "confidence": 0.9,
            "computational": None, "refuse": False}

    def complete_json(self, system, user):
        return dict(self.response)


def test_ai_off_by_default():
    col = getEmptyCol()
    assert ai_config.ai_enabled(col) is False
    status = ai_config.ai_status(col)
    assert status["enabled"] is False and status["ready"] is False


def test_author_seed_adds_card_ai_off():
    col = getEmptyCol()
    res = generation.author_seed(col, "What is angular momentum?", "L = r x p", "topic::mechanics::rotation")
    assert res["added"] and res["note_id"]
    note = col.get_note(res["note_id"])
    assert note["Front"] == "What is angular momentum?"
    assert "topic::mechanics::rotation" in note.tags
    assert generation.SEED_TAG in note.tags


def test_generate_ai_off_authors_seed_only():
    col = getEmptyCol()
    res = generation.generate(col, mode="gap_fill", topic="topic::atomic",
                              seed_front="Photon energy?", seed_back="E = hf", n=3)
    assert res["seed"]["added"]
    assert res["ai"] == "off"
    assert res["added"] == [] and res["review"] == []


def test_gap_fill_ai_on_adds_grounded_card(monkeypatch):
    col = getEmptyCol()
    ai_config.set_ai_enabled(col, True)
    ai_config.set_ai_model(col, "gpt-x-2026-01-01")  # avoid snapshot discovery
    monkeypatch.setattr(generation, "_retrieve", lambda col, query: list(_GROUNDED))
    monkeypatch.setattr(llm_module, "LLMClient", _FakeLLM)

    res = generation.gap_fill(col, "topic::atomic", "Photon energy?", "E = hf", n=1)
    assert res["ai"] == "on"
    assert len(res["added"]) == 1
    added = res["added"][0]
    assert added["source_ref"] and added["note_id"]
    note = col.get_note(added["note_id"])
    assert "Source:" in note["Back"]
    assert generation.GENERATED_TAG in note.tags


def test_gap_fill_routes_low_confidence_to_review(monkeypatch):
    col = getEmptyCol()
    ai_config.set_ai_enabled(col, True)
    ai_config.set_ai_model(col, "gpt-x-2026-01-01")

    class _LowConf(_FakeLLM):
        def __init__(self, model, **kw):
            super().__init__(model, **kw)
            self.response["confidence"] = 0.3

    monkeypatch.setattr(generation, "_retrieve", lambda col, query: list(_GROUNDED))
    monkeypatch.setattr(llm_module, "LLMClient", _LowConf)

    res = generation.gap_fill(col, "topic::atomic", "Photon energy?", "E = hf", n=1)
    assert res["added"] == []
    assert len(res["review"]) == 1
    assert "confidence" in res["review"][0]["review_reason"]
