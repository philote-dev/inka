# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the shared pinned LLM client and the three tools now routed
through it: the figure generator, the figure-fidelity judge, and the
technique-giveaway judge.

Nothing here touches the network or needs the ``openai`` package installed. The
client unit tests inject a fake ``openai`` module so ``LLMClient`` builds without
a real backend; the tool tests inject a fake client through each class's
``client=`` seam. The file runs under pytest and also directly as a script
(``python3 pylib/tests/test_pgrep_llm_client.py``) for environments without a
built ``anki``.
"""

from __future__ import annotations

import contextlib
import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The offline AI core imports as ``pgrep.ai.*`` with pylib/anki appended (never
# prepended: it holds stdlib-named modules). The routed tools live under tools/
# and content/tools/.
_AI_CORE = REPO / "pylib" / "anki"
if _AI_CORE.is_dir() and str(_AI_CORE) not in sys.path:
    sys.path.append(str(_AI_CORE))
for _tool_dir in (REPO / "tools", REPO / "content" / "tools"):
    if _tool_dir.is_dir() and str(_tool_dir) not in sys.path:
        sys.path.insert(0, str(_tool_dir))

import check_technique_giveaway as giveaway  # noqa: E402
import pgrep_figure_gen as figgen  # noqa: E402
import pgrep_figure_verify as figverify  # noqa: E402
from pgrep.ai import llm  # noqa: E402

_DATED = "gpt-test-2026-01-01"


# --- fakes -----------------------------------------------------------------


class _FakeOpenAI:
    """Stand-in for ``openai.OpenAI``; the real backend is swapped in per test."""

    def __init__(self, *args, **kwargs):
        pass


class _Resp:
    def __init__(self, content: str):
        self.choices = [
            types.SimpleNamespace(message=types.SimpleNamespace(content=content))
        ]


class _ScriptedBackend:
    """Fake ``chat.completions.create`` driven by a script of steps.

    Each step is ``("raise", "<ExceptionName>")`` or ``("return", "<content>")``.
    Every call's kwargs are recorded so tests can assert which options survived.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        action, payload = self.script.pop(0)
        if action == "raise":
            raise type(payload, (Exception,), {})()
        return _Resp(payload)


class _FakeClient:
    """A stand-in for ``LLMClient`` injected through the tools' ``client=`` seam."""

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
    mod.OpenAI = _FakeOpenAI
    saved = sys.modules.get("openai")
    sys.modules["openai"] = mod
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = saved


@contextlib.contextmanager
def _no_sleep():
    import time

    saved = time.sleep
    time.sleep = lambda *a, **k: None
    try:
        yield
    finally:
        time.sleep = saved


@contextlib.contextmanager
def _raises(exc):
    caught = False
    try:
        yield
    except exc:
        caught = True
    if not caught:
        raise AssertionError(f"expected {exc.__name__}")


# --- (a) the shared client -------------------------------------------------


def test_llmclient_refuses_floating_alias():
    with _fake_openai(), _raises(ValueError):
        llm.LLMClient("gpt-5.5")


def test_complete_text_drops_temperature_and_seed_on_bad_request():
    with _fake_openai():
        client = llm.LLMClient(_DATED)
        backend = _ScriptedBackend(
            [
                ("raise", "BadRequestError"),  # temperature + seed
                ("raise", "BadRequestError"),  # temperature
                ("raise", "BadRequestError"),  # seed
                ("return", '{"ok": true}'),  # no options
            ]
        )
        client._client = backend
        out = client.complete_text("sys", "usr", json_object=True)
    assert out == '{"ok": true}'
    assert len(backend.calls) == 4
    # richest options first, JSON response format on every attempt
    assert backend.calls[0].get("temperature") == 0.0
    assert backend.calls[0].get("seed") == 7
    assert backend.calls[0].get("response_format") == {"type": "json_object"}
    # the accepted attempt dropped both offending options, kept response_format
    assert "temperature" not in backend.calls[-1]
    assert "seed" not in backend.calls[-1]
    assert backend.calls[-1].get("response_format") == {"type": "json_object"}


def test_complete_text_without_json_object_sets_no_response_format():
    with _fake_openai():
        client = llm.LLMClient(_DATED)
        backend = _ScriptedBackend([("return", "plain text")])
        client._client = backend
        out = client.complete_text("sys", "usr")
    assert out == "plain text"
    assert "response_format" not in backend.calls[0]


def test_complete_json_parses_object():
    with _fake_openai():
        client = llm.LLMClient(_DATED)
        client._client = _ScriptedBackend([("return", '{"a": 1, "b": [2, 3]}')])
        assert client.complete_json("s", "u") == {"a": 1, "b": [2, 3]}


def test_complete_text_retries_transient_then_succeeds():
    with _fake_openai(), _no_sleep():
        client = llm.LLMClient(_DATED)
        backend = _ScriptedBackend(
            [
                ("raise", "RateLimitError"),
                ("return", '{"ok": true}'),
            ]
        )
        client._client = backend
        assert client.complete_json("s", "u") == {"ok": True}
    assert len(backend.calls) == 2


def test_complete_text_reraises_unknown_error():
    with _fake_openai(), _raises(Exception):
        client = llm.LLMClient(_DATED)
        client._client = _ScriptedBackend([("raise", "ValueError")])
        client.complete_text("s", "u")


# --- (b) the three tools, no network ---------------------------------------


def test_gen_parses_svg_from_json():
    svg = '<svg viewBox="0 0 10 10"><line/></svg>'
    fake = _FakeClient(json.dumps({"svg": svg}))
    gen = figgen.Gen("gpt-5.5", client=fake)  # floating model ok: client injected
    assert gen.svg_for("A block on an incline.", "mechanics setup") == svg
    # the tool asks the client for a JSON object
    assert fake.calls and fake.calls[0][2] is True


def test_gen_regex_fallback_for_bare_svg():
    fake = _FakeClient("sure, here it is: <svg><circle/></svg> hope that helps")
    gen = figgen.Gen(_DATED, client=fake)
    assert gen.svg_for("x", "y") == "<svg><circle/></svg>"


def test_gen_refine_short_circuits_non_svg():
    gen = figgen.Gen(_DATED, client=_FakeClient("unused"))
    assert gen.refine("plain text, not an svg") == "plain text, not an svg"


def test_gen_refine_cleans_svg():
    cleaned = '<svg><rect x="1"/></svg>'
    gen = figgen.Gen(_DATED, client=_FakeClient(json.dumps({"svg": cleaned})))
    assert gen.refine("<svg><rect/></svg>") == cleaned


def test_gen_returns_empty_on_client_error():
    gen = figgen.Gen(_DATED, client=_RaisingClient())
    assert gen.svg_for("s", "h") == ""


def test_gen_default_client_builds_llmclient_and_flows():
    # No injected client: the default seam builds a real (pinned) LLMClient for a
    # dated model, and a call flows through complete_text end to end (no network).
    with _fake_openai():
        gen = figgen.Gen(_DATED)
        assert isinstance(gen.client, llm.LLMClient)
        gen.client._client = _ScriptedBackend(
            [("return", json.dumps({"svg": "<svg/>"}))]
        )
        assert gen.svg_for("s", "h") == "<svg/>"


def test_figverify_judge_parses_json():
    verdict = {"matches": True, "missing": [], "has_numbers": False, "notes": "ok"}
    judge = figverify.Judge(
        "gpt-5.4-2026-03-05", client=_FakeClient(json.dumps(verdict))
    )
    assert judge.verify("stem", "<svg/>") == verdict


def test_figverify_judge_brace_fallback():
    fake = _FakeClient('noise {"matches": false, "notes": "n"} trailing')
    judge = figverify.Judge(_DATED, client=fake)
    v = judge.verify("s", "<svg/>")
    assert v["matches"] is False and v["notes"] == "n"


def test_figverify_returns_fallback_on_error():
    judge = figverify.Judge(_DATED, client=_RaisingClient())
    v = judge.verify("s", "<svg/>")
    assert v["matches"] is False and "judge call failed" in v["notes"]


def test_giveaway_judge_parses_json():
    verdict = {"gives_away": True, "severity": "high", "what": "E=hf", "fix": "reword"}
    judge = giveaway.Judge(_DATED, client=_FakeClient(json.dumps(verdict)))
    v = judge.judge(
        {
            "topic": "atomic",
            "stem": "Using E = hf, find the energy.",
            "choices": ["a", "b"],
            "correct": "a",
        }
    )
    assert v["gives_away"] is True and v["severity"] == "high"


def test_giveaway_judge_brace_fallback():
    fake = _FakeClient('junk {"gives_away": false} more')
    judge = giveaway.Judge(_DATED, client=fake)
    assert judge.judge({"stem": "x"})["gives_away"] is False


def test_giveaway_returns_fallback_on_error():
    judge = giveaway.Judge(_DATED, client=_RaisingClient())
    v = judge.judge({"stem": "x"})
    assert v["gives_away"] is False and v.get("note") == "judge call failed"


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
