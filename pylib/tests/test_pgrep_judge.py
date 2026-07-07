# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the shared ``pgrep.ai.judge`` module.

The two offline audit judges (figure fidelity and technique giveaway) now live
behind one ``Judge`` with an injectable client. These tests drive it with a fake
client that returns canned JSON, so nothing touches the network. They assert that
each method builds the right typed verdict, that ``to_dict()`` reproduces the
legacy shape the offline tools emit, and that a malformed or failed reply yields
the safe default. Runs under pytest and directly as
``python3 pylib/tests/test_pgrep_judge.py``.
"""

from __future__ import annotations

import contextlib
import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The offline AI core imports as ``pgrep.ai.*`` with pylib/anki appended (never
# prepended: it holds stdlib-named modules).
_AI_CORE = REPO / "pylib" / "anki"
if _AI_CORE.is_dir() and str(_AI_CORE) not in sys.path:
    sys.path.append(str(_AI_CORE))

from pgrep.ai import judge, llm  # type: ignore[import-not-found]  # noqa: E402

_DATED = "gpt-judge-2026-01-01"


# --- fakes -----------------------------------------------------------------


class _FakeClient:
    """Injected through the judge's ``client`` seam; returns one canned reply."""

    model = "fake-2026-01-01"

    def __init__(self, text: str):
        self.text = text
        self.calls: list[tuple] = []

    def complete_text(self, system, user, *, json_object=False):
        self.calls.append((system, user, json_object))
        return self.text


class _RaisingClient:
    model = "fake-2026-01-01"

    def complete_text(self, *args, **kwargs):
        raise RuntimeError("boom")


@contextlib.contextmanager
def _fake_openai():
    mod = types.ModuleType("openai")
    mod.OpenAI = lambda *a, **k: None  # type: ignore[attr-defined]
    saved = sys.modules.get("openai")
    sys.modules["openai"] = mod
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = saved


# --- figure fidelity -------------------------------------------------------


def test_figure_fidelity_parses_typed_verdict():
    reply = {
        "matches": True,
        "missing": ["ramp"],
        "contradictions": [],
        "has_numbers": False,
        "notes": "ok",
    }
    fake = _FakeClient(json.dumps(reply))
    v = judge.Judge(_DATED, client=fake).figure_fidelity("A block on a ramp.", "<svg/>")
    assert isinstance(v, judge.FigureVerdict)
    assert v.matches is True
    assert v.missing == ["ramp"]
    assert v.contradictions == []
    assert v.has_numbers is False
    assert v.notes == "ok"
    # to_dict passes the parsed reply through verbatim (the legacy shape).
    assert v.to_dict() == reply
    # routed as a JSON-object request carrying the moved prompt and payload.
    system, user, json_object = fake.calls[0]
    assert json_object is True
    assert system == judge.FIGURE_SYSTEM
    assert user == "PROBLEM STEM:\nA block on a ramp.\n\nSVG SOURCE:\n<svg/>"


def test_figure_fidelity_brace_fallback():
    fake = _FakeClient('noise {"matches": false, "notes": "n"} trailing')
    v = judge.Judge(_DATED, client=fake).figure_fidelity("s", "<svg/>")
    assert v.matches is False
    assert v.notes == "n"
    assert v.to_dict() == {"matches": False, "notes": "n"}


def test_figure_fidelity_malformed_reply_is_safe_default():
    fake = _FakeClient("sorry, no diagram to check")
    v = judge.Judge(_DATED, client=fake).figure_fidelity("s", "<svg/>")
    assert v.matches is False
    assert v.to_dict() == {"matches": False, "notes": "unparseable judge reply"}


def test_figure_fidelity_blank_reply_defaults_to_empty_object():
    v = judge.Judge(_DATED, client=_FakeClient("")).figure_fidelity("s", "<svg/>")
    assert v.matches is False
    assert v.to_dict() == {}


def test_figure_fidelity_client_error_is_safe_default():
    v = judge.Judge(_DATED, client=_RaisingClient()).figure_fidelity("s", "<svg/>")
    assert v.matches is False
    assert v.to_dict() == {"matches": False, "notes": "judge call failed: boom"}


# --- technique giveaway ----------------------------------------------------


def test_technique_giveaway_parses_typed_verdict():
    reply = {"gives_away": True, "severity": "high", "what": "E=hf", "fix": "reword"}
    fake = _FakeClient(json.dumps(reply))
    problem = {
        "topic": "atomic",
        "stem": "Using E = hf, find the energy.",
        "choices": ["a", "b"],
        "correct": "A",
    }
    v = judge.Judge(_DATED, client=fake).technique_giveaway(problem)
    assert isinstance(v, judge.GiveawayVerdict)
    assert v.gives_away is True
    assert v.severity == "high"
    assert v.what == "E=hf"
    assert v.fix == "reword"
    assert v.to_dict() == reply
    system, user, json_object = fake.calls[0]
    assert json_object is True
    assert system == judge.GIVEAWAY_SYSTEM
    assert user == (
        "TOPIC: atomic\n\nSTEM:\nUsing E = hf, find the energy.\n\n"
        "CHOICES:\n  a\n  b\n\nCORRECT: A"
    )


def test_technique_giveaway_strips_figure_from_stem():
    fake = _FakeClient('{"gives_away": false}')
    problem = {
        "stem": 'Before <div class="pg-figure"><svg/></div> after',
        "choices": [],
    }
    judge.Judge(_DATED, client=fake).technique_giveaway(problem)
    _, user, _ = fake.calls[0]
    assert "pg-figure" not in user
    assert "STEM:\nBefore   after" in user


def test_technique_giveaway_malformed_reply_is_safe_default():
    fake = _FakeClient("no verdict here")
    v = judge.Judge(_DATED, client=fake).technique_giveaway({"stem": "x"})
    assert v.gives_away is False
    assert v.to_dict() == {"gives_away": False}


def test_technique_giveaway_client_error_is_safe_default():
    v = judge.Judge(_DATED, client=_RaisingClient()).technique_giveaway({"stem": "x"})
    assert v.gives_away is False
    assert v.to_dict() == {"gives_away": False, "what": "", "note": "judge call failed"}


# --- verdicts and the default seam -----------------------------------------


def test_verdict_to_dict_from_typed_fields_is_documented_shape():
    # A directly built verdict (no parsed reply) serializes its typed fields,
    # filling the documented defaults.
    fig = judge.FigureVerdict(matches=True, missing=["a"], has_numbers=True, notes="n")
    assert fig.to_dict() == {
        "matches": True,
        "missing": ["a"],
        "contradictions": [],
        "has_numbers": True,
        "notes": "n",
    }
    give = judge.GiveawayVerdict(gives_away=True, severity="low", what="w", fix="f")
    assert give.to_dict() == {
        "gives_away": True,
        "severity": "low",
        "what": "w",
        "fix": "f",
    }


def test_default_client_builds_pinned_llmclient():
    # No injected client: the seam builds a real pinned LLMClient for a dated
    # model (openai is faked, so no network and no package needed).
    with _fake_openai():
        j = judge.Judge(_DATED)
    assert isinstance(j.client, llm.LLMClient)
    assert j.model == _DATED


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
