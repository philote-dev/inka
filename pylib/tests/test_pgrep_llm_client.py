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
import os
import sys
import tempfile
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

import check_technique_giveaway as giveaway  # type: ignore[import-not-found]  # noqa: E402
import pgrep_figure_gen as figgen  # type: ignore[import-not-found]  # noqa: E402
import pgrep_figure_verify as figverify  # type: ignore[import-not-found]  # noqa: E402
from pgrep.ai import llm  # type: ignore[import-not-found]  # noqa: E402
from pgrep.ai.batch_safety import (  # type: ignore[import-not-found]  # noqa: E402
    BatchCounters,
    BatchLimits,
    BatchState,
    BatchStatus,
    BatchStopped,
    BatchStopReason,
    GenerationManager,
)

_DATED = "gpt-test-2026-01-01"


# --- fakes -----------------------------------------------------------------


class _FakeOpenAI:
    """Stand-in for ``openai.OpenAI``; the real backend is swapped in per test."""

    last_kwargs: dict = {}
    model_ids: list[str] = []

    def __init__(self, *args, **kwargs):
        type(self).last_kwargs = dict(kwargs)
        self.models = types.SimpleNamespace(
            list=lambda: types.SimpleNamespace(
                data=[types.SimpleNamespace(id=model_id) for model_id in self.model_ids]
            )
        )


class _Resp:
    def __init__(
        self,
        content: str,
        *,
        model: str = _DATED,
        response_id: str = "chatcmpl-test-1",
    ):
        self.id = response_id
        self.model = model
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
        if isinstance(payload, _Resp):
            return payload
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
    mod.OpenAI = _FakeOpenAI  # type: ignore[attr-defined]
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


@contextlib.contextmanager
def _batch_run_dir(path: Path | None):
    name = "PGREP_BATCH_RUN_DIR"
    present = name in os.environ
    previous = os.environ.get(name)
    if path is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = str(path)
    try:
        yield
    finally:
        if present:
            assert previous is not None
            os.environ[name] = previous
        else:
            os.environ.pop(name, None)


@contextlib.contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _initialize_batch(
    run_dir: Path,
    *,
    max_calls: int = 12,
    max_retries: int = 3,
) -> GenerationManager:
    manager = GenerationManager(
        run_id="llm-integration-run",
        tool="llm-client",
        run_dir=run_dir,
        limits=BatchLimits(
            max_calls=max_calls,
            max_concurrency=1,
            max_retries=max_retries,
            max_minutes=15,
        ),
        stop_path=run_dir / "STOP_GENERATION",
    )
    manager.initialize()
    return manager


def _batch_state(manager: GenerationManager) -> BatchState:
    return BatchState.from_dict(
        json.loads(manager.state_path.read_text(encoding="utf8"))
    )


# --- (a) the shared client -------------------------------------------------


def test_llmclient_refuses_floating_alias():
    old = os.environ.pop("OPENAI_BASE_URL", None)
    try:
        with _fake_openai(), _raises(ValueError):
            llm.LLMClient("gpt-5.5")
    finally:
        if old is not None:
            os.environ["OPENAI_BASE_URL"] = old


def test_llmclient_passes_openai_base_url():
    with _fake_openai():
        old = os.environ.get("OPENAI_BASE_URL")
        os.environ["OPENAI_BASE_URL"] = "https://example.test/llm"
        try:
            llm.LLMClient(_DATED)
        finally:
            if old is None:
                os.environ.pop("OPENAI_BASE_URL", None)
            else:
                os.environ["OPENAI_BASE_URL"] = old
    assert _FakeOpenAI.last_kwargs.get("base_url") == "https://example.test/llm"


def test_llmclient_accepts_arbitrary_gateway_model_id():
    with _fake_openai():
        old = os.environ.get("OPENAI_BASE_URL")
        os.environ["OPENAI_BASE_URL"] = "https://tfy.example/v1"
        try:
            client = llm.LLMClient("gateway/claude-opus-4-8")
        finally:
            if old is None:
                os.environ.pop("OPENAI_BASE_URL", None)
            else:
                os.environ["OPENAI_BASE_URL"] = old

    assert client.model == "gateway/claude-opus-4-8"


def test_list_models_uses_configured_gateway_client_and_sorts_exact_ids():
    with _fake_openai():
        old_base_url = os.environ.get("OPENAI_BASE_URL")
        old_key = os.environ.get("OPENAI_API_KEY")
        old_load_api_key = llm.load_api_key
        os.environ["OPENAI_BASE_URL"] = "https://tfy.example/v1"
        os.environ["OPENAI_API_KEY"] = "tfy_test_token"
        llm.load_api_key = lambda: None
        _FakeOpenAI.model_ids = ["grok-4.5", "gateway/claude-opus-4-8", "gpt-5.5"]
        try:
            models = llm.list_models()
        finally:
            _FakeOpenAI.model_ids = []
            llm.load_api_key = old_load_api_key
            if old_base_url is None:
                os.environ.pop("OPENAI_BASE_URL", None)
            else:
                os.environ["OPENAI_BASE_URL"] = old_base_url
            if old_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old_key

    assert models == ["gateway/claude-opus-4-8", "gpt-5.5", "grok-4.5"]
    assert _FakeOpenAI.last_kwargs == {
        "api_key": "tfy_test_token",
        "base_url": "https://tfy.example/v1",
    }


def test_load_api_key_prefers_truefoundry_gateway():
    import tempfile

    saved = {
        key: os.environ.get(key)
        for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "TFY_API_KEY")
    }
    old_gateway = llm._TFY_GATEWAY_ENV
    try:
        with tempfile.TemporaryDirectory() as tmp:
            gateway = Path(tmp) / "gateway.env"
            gateway.write_text(
                "OPENAI_API_KEY=tfy_test_token\n"
                "OPENAI_BASE_URL=https://tfy.example/api/llm\n"
                "TFY_API_KEY=tfy_test_token\n"
            )
            llm._TFY_GATEWAY_ENV = str(gateway)
            for key in saved:
                os.environ.pop(key, None)
            llm.load_api_key()
            assert os.environ["OPENAI_API_KEY"] == "tfy_test_token"
            assert os.environ["OPENAI_BASE_URL"] == "https://tfy.example/api/llm"
            assert os.environ["TFY_API_KEY"] == "tfy_test_token"
    finally:
        llm._TFY_GATEWAY_ENV = old_gateway
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


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


def test_complete_json_retries_without_response_format_after_option_fallbacks():
    with _fake_openai():
        client = llm.LLMClient(_DATED)
        backend = _ScriptedBackend(
            [
                ("raise", "BadRequestError"),
                ("raise", "BadRequestError"),
                ("raise", "BadRequestError"),
                ("raise", "BadRequestError"),
                ("return", '{"instruction_only": true}'),
            ]
        )
        client._client = backend

        assert client.complete_json("Return one JSON object.", "user") == {
            "instruction_only": True
        }

    assert len(backend.calls) == 5
    assert all(
        call.get("response_format") == {"type": "json_object"}
        for call in backend.calls[:4]
    )
    assert "response_format" not in backend.calls[4]


def test_complete_json_strictly_rejects_malformed_instruction_only_fallback():
    with _fake_openai():
        client = llm.LLMClient(_DATED)
        backend = _ScriptedBackend(
            [
                ("raise", "BadRequestError"),
                ("raise", "BadRequestError"),
                ("raise", "BadRequestError"),
                ("raise", "BadRequestError"),
                ("return", "not JSON"),
            ]
        )
        client._client = backend

        with _raises(json.JSONDecodeError):
            client.complete_json("Return one JSON object.", "user")

    assert len(backend.calls) == 5
    assert "response_format" not in backend.calls[-1]


def test_complete_text_without_json_object_sets_no_response_format():
    with _fake_openai():
        client = llm.LLMClient(_DATED)
        backend = _ScriptedBackend([("return", "plain text")])
        client._client = backend
        out = client.complete_text("sys", "usr")
    assert out == "plain text"
    assert "response_format" not in backend.calls[0]


def test_complete_result_retains_exact_response_metadata():
    with _fake_openai():
        client = llm.LLMClient(_DATED)
        response = _Resp(
            '{"ok":true}',
            model=_DATED,
            response_id="chatcmpl-tfy-metadata",
        )
        client._client = _ScriptedBackend([("return", response)])
        result = client.complete_result("system", "user", json_object=True)

    assert result.text == '{"ok":true}'
    assert result.model == _DATED
    assert result.response_id == "chatcmpl-tfy-metadata"


def test_complete_result_treats_missing_response_id_as_empty():
    with _fake_openai():
        client = llm.LLMClient(_DATED)
        response = _Resp("{}", response_id=None)  # type: ignore[arg-type]
        client._client = _ScriptedBackend([("return", response)])
        result = client.complete_result("system", "user")

    assert result.response_id == ""


def test_complete_json_parses_object():
    with _fake_openai():
        client = llm.LLMClient(_DATED)
        client._client = _ScriptedBackend([("return", '{"a": 1, "b": [2, 3]}')])
        assert client.complete_json("s", "u") == {"a": 1, "b": [2, 3]}


def test_complete_text_retries_transient_then_succeeds():
    with _fake_openai(), _no_sleep():
        client = llm.LLMClient(_DATED, seed=41)
        backend = _ScriptedBackend(
            [
                ("raise", "RateLimitError"),
                ("return", '{"ok": true}'),
            ]
        )
        client._client = backend
        assert client.complete_json("s", "u") == {"ok": True}
    assert len(backend.calls) == 2
    assert [call["seed"] for call in backend.calls] == [41, 41]


def test_complete_text_reraises_unknown_error():
    with _fake_openai(), _raises(Exception):
        client = llm.LLMClient(_DATED)
        client._client = _ScriptedBackend([("raise", "ValueError")])
        client.complete_text("s", "u")


def test_complete_text_without_batch_env_preserves_calls_and_touches_no_safety():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        backend = _ScriptedBackend(
            [
                ("raise", "RateLimitError"),
                ("return", "unchanged result"),
            ]
        )
        with (
            _fake_openai(),
            _no_sleep(),
            _batch_run_dir(None),
            _working_directory(root),
        ):
            client = llm.LLMClient(_DATED)
            client._client = backend
            result = client.complete_text(
                "unchanged system",
                "unchanged user",
                json_object=True,
            )

        expected_kwargs = {
            "model": _DATED,
            "messages": [
                {"role": "system", "content": "unchanged system"},
                {"role": "user", "content": "unchanged user"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "seed": 7,
        }
        assert result == "unchanged result"
        assert backend.calls == [expected_kwargs, expected_kwargs]
        assert not list(root.rglob("safety.json"))
        assert list(root.iterdir()) == []


def test_complete_text_protected_success_and_failure_update_safe_counters():
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary) / "run"
        manager = _initialize_batch(run_dir)
        with _fake_openai(), _batch_run_dir(run_dir):
            client = llm.LLMClient(_DATED)
            client._client = _ScriptedBackend(
                [("return", "PRIVATE_RESPONSE_MUST_NOT_PERSIST")]
            )
            assert (
                client.complete_text(
                    "PRIVATE_PROMPT_MUST_NOT_PERSIST",
                    "PRIVATE_SOURCE_TEXT_MUST_NOT_PERSIST",
                )
                == "PRIVATE_RESPONSE_MUST_NOT_PERSIST"
            )

            client._client = _ScriptedBackend([("raise", "ValueError")])
            with _raises(Exception):
                client.complete_text("second private prompt", "second private source")

        state = _batch_state(manager)
        assert state.status is BatchStatus.RUNNING
        assert state.counters == BatchCounters(
            calls_started=2,
            calls_completed=1,
            calls_failed=1,
            peak_concurrency=1,
        )
        serialized = manager.state_path.read_text(encoding="utf8")
        for private_value in (
            "PRIVATE_PROMPT_MUST_NOT_PERSIST",
            "PRIVATE_SOURCE_TEXT_MUST_NOT_PERSIST",
            "PRIVATE_RESPONSE_MUST_NOT_PERSIST",
            "second private prompt",
            "second private source",
            _DATED,
        ):
            assert private_value not in serialized


def test_complete_text_call_limit_stops_before_backend_invocation():
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary) / "run"
        manager = _initialize_batch(run_dir, max_calls=1)
        with _fake_openai(), _batch_run_dir(run_dir):
            client = llm.LLMClient(_DATED)
            client._client = _ScriptedBackend([("return", "first")])
            assert client.complete_text("system", "user") == "first"

            denied_backend = _ScriptedBackend([("return", "must not run")])
            client._client = denied_backend
            try:
                client.complete_text("system", "user")
            except BatchStopped as error:
                assert error.reason is BatchStopReason.CALL_LIMIT
            else:
                raise AssertionError("expected the call limit to stop generation")

        assert denied_backend.calls == []
        state = _batch_state(manager)
        assert state.status is BatchStatus.STOPPED
        assert state.stop_reason is BatchStopReason.CALL_LIMIT
        assert state.counters.calls_started == 1


def test_complete_text_option_fallback_and_transient_retry_use_global_attempts():
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary) / "run"
        manager = _initialize_batch(run_dir, max_retries=2)
        backend = _ScriptedBackend(
            [
                ("raise", "BadRequestError"),
                ("raise", "RateLimitError"),
                ("return", "recovered"),
            ]
        )
        with (
            _fake_openai(),
            _no_sleep(),
            _batch_run_dir(run_dir),
        ):
            client = llm.LLMClient(_DATED, seed=41)
            client._client = backend
            assert client.complete_text("system", "user") == "recovered"

        assert len(backend.calls) == 3
        assert backend.calls[0]["seed"] == 41
        assert "seed" not in backend.calls[1]
        assert backend.calls[1] == backend.calls[2]
        assert _batch_state(manager).counters == BatchCounters(
            calls_started=3,
            calls_completed=1,
            calls_failed=2,
            peak_concurrency=1,
            retries=2,
        )


def test_external_retry_offsets_bound_corrections_and_provider_fallbacks():
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary) / "run"
        manager = _initialize_batch(run_dir, max_calls=10, max_retries=3)
        with _fake_openai(), _batch_run_dir(run_dir):
            client = llm.LLMClient(_DATED)

            client._client = _ScriptedBackend([("return", "{}")])
            client.complete_result(
                "system",
                "initial",
                json_object=True,
                batch_operation_id="tfy-shadow-initial",
                batch_retry_offset=0,
            )

            correction_one = _ScriptedBackend(
                [
                    ("raise", "BadRequestError"),
                    ("return", "{}"),
                ]
            )
            client._client = correction_one
            client.complete_result(
                "system",
                "correction one",
                json_object=True,
                batch_operation_id="tfy-shadow-correction-1",
                batch_retry_offset=1,
            )

            client._client = _ScriptedBackend([("return", "{}")])
            client.complete_result(
                "system",
                "correction two",
                json_object=True,
                batch_operation_id="tfy-shadow-correction-2",
                batch_retry_offset=2,
            )

            denied_backend = _ScriptedBackend([("return", "must not run")])
            client._client = denied_backend
            with _raises(BatchStopped):
                client.complete_result(
                    "system",
                    "correction three",
                    json_object=True,
                    batch_operation_id="tfy-shadow-correction-3",
                    batch_retry_offset=3,
                )

        assert len(correction_one.calls) == 2
        assert denied_backend.calls == []
        state = _batch_state(manager)
        assert state.status is BatchStatus.STOPPED
        assert state.stop_reason is BatchStopReason.RETRY_LIMIT
        assert state.counters == BatchCounters(
            calls_started=4,
            calls_completed=3,
            calls_failed=1,
            peak_concurrency=1,
            retries=3,
        )


def test_complete_text_retry_limit_stops_before_next_backend_attempt():
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary) / "run"
        manager = _initialize_batch(run_dir, max_retries=1)
        backend = _ScriptedBackend(
            [
                ("raise", "RateLimitError"),
                ("raise", "RateLimitError"),
                ("return", "must not run"),
            ]
        )
        with _fake_openai(), _no_sleep(), _batch_run_dir(run_dir):
            client = llm.LLMClient(_DATED)
            client._client = backend
            try:
                client.complete_text("system", "user")
            except BatchStopped as error:
                assert error.reason is BatchStopReason.RETRY_LIMIT
            else:
                raise AssertionError("expected the retry limit to stop generation")

        assert len(backend.calls) == 2
        state = _batch_state(manager)
        assert state.status is BatchStatus.STOPPED
        assert state.stop_reason is BatchStopReason.RETRY_LIMIT
        assert state.counters == BatchCounters(
            calls_started=2,
            calls_failed=2,
            peak_concurrency=1,
            retries=1,
        )


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


def test_pick_generator_snapshot_excludes_non_chat():
    # A non-chat variant (audio) carries a chat family token but must never win,
    # or the chat-completions call 404s. This is the regression the figure run hit.
    models = [
        "gpt-5.5-audio-2026-04-23",
        "gpt-5.5-2026-04-23",
        "text-embedding-3-large",
    ]
    assert llm.pick_generator_snapshot(models) == "gpt-5.5-2026-04-23"


def test_pick_judge_snapshot_excludes_non_chat_and_generator():
    models = [
        "gpt-5.5-2026-04-23",
        "gpt-4o-realtime-2026-01-01",
        "gpt-4.1-2026-02-02",
    ]
    got = llm.pick_judge_snapshot("gpt-5.5-2026-04-23", models)
    assert got == "gpt-4.1-2026-02-02"


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
