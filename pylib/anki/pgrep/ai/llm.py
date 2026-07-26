# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The pinned LLM client for generation (L4.0f).

One thin wrapper over the OpenAI client so every call is reproducible and
recorded: an exact dated model snapshot (never a floating alias), a low
temperature, a seed when the model supports it, and JSON-only responses. The
generator uses the strongest available snapshot; the judge (elsewhere) uses a
different one so it never grades its own output.

Two things wrap every call, in :mod:`anki.pgrep.ai.usage`: the spend gate runs
before it (refusing the call when a configured cap is already reached) and the
ledger records its token counts after it. This is the one seam paid calls go
through, so it is the one place those controls have to live.

The TrueFoundry gateway is the exception to the dated-snapshot rule. It exposes
floating ids (``gpt-5.5``) rather than dated OpenAI snapshots, so an id on
:data:`GATEWAY_MODELS` is accepted when a gateway base URL is configured. Those
clients report ``pinned = False`` and the ledger records it, so a run manifest
can still say whether the exact model was reproducible.

``openai`` is imported lazily, so an AI-off app never loads it and importing this
module stays cheap. Snapshot discovery is a helper for pinning at gate time; the
resolved IDs go straight into the run manifest.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import usage

# Ranking hints for "strongest" chat snapshot, high to low. Matched as substrings
# against the account's available model ids; the newest matching family wins, and
# an explicit dated snapshot always beats a floating alias.
_FAMILY_RANK = ("gpt-5", "gpt-4.1", "gpt-4o", "o4", "o3", "gpt-4")
_SNAPSHOT_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
# Substrings that mark a model id as NOT a chat-completions model even though it
# carries a chat family token (for example gpt-4o-audio, gpt-4o-realtime,
# gpt-4o-search). A floating alias must never resolve to one of these, or the
# chat-completions call 404s.
_NON_CHAT_MARKERS = (
    "audio",
    "realtime",
    "image",
    "tts",
    "transcribe",
    "embedding",
    "search",
    "moderation",
    "whisper",
    "dall-e",
    "instruct",
)


@dataclass
class LLMResult:
    text: str
    model: str
    raw: dict = field(default_factory=dict)


# TrueFoundry gateway credentials (one token for every model). Lives outside
# the repo so it is never committed or Dropbox-synced with content/.
_TFY_GATEWAY_ENV = os.path.expanduser("~/.config/truefoundry/gateway.env")
_TFY_GATEWAY_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "TFY_API_KEY",
)

# Gateway model ids allowed to skip the dated-snapshot pin, but only when a
# gateway base URL is configured. These are the locked model roles from
# docs_pgrep/plan/content-foundry-and-verifier-design.md; extend for one run
# with PGREP_GATEWAY_MODELS as a comma-separated list.
GATEWAY_MODELS = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "claude-opus-4-8",
    "claude-haiku-4-5",
    "grok-4.5",
)


def _gateway_models() -> tuple[str, ...]:
    extra = os.environ.get("PGREP_GATEWAY_MODELS", "")
    names = [n.strip() for n in extra.split(",") if n.strip()]
    return GATEWAY_MODELS + tuple(names)


def gateway_alias_allowed(model: str) -> bool:
    """True when ``model`` is an allowlisted floating id on a configured gateway."""
    if not os.environ.get("OPENAI_BASE_URL"):
        return False
    return model in _gateway_models()


class LLMClient:
    """A pinned OpenAI-compatible chat client that returns JSON objects."""

    def __init__(self, model: str, *, temperature: float = 0.0, seed: int | None = 7):
        from openai import OpenAI  # type: ignore[import-not-found]

        self.pinned = not _is_floating_alias(model)
        if not self.pinned and not gateway_alias_allowed(model):
            raise ValueError(
                f"refusing a floating alias '{model}'; pin an exact dated snapshot, "
                f"or route through the gateway (OPENAI_BASE_URL) with an id on "
                f"GATEWAY_MODELS / PGREP_GATEWAY_MODELS"
            )
        self.model = model
        self.temperature = temperature
        self.seed = seed
        # Route through TrueFoundry when OPENAI_BASE_URL is set (gateway.env).
        kwargs: dict[str, str] = {}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    def complete_text(
        self, system: str, user: str, *, json_object: bool = False
    ) -> str:
        """One completion, returned as the raw response text.

        Reasoning and gpt-5 snapshots can reject a non-default ``temperature`` or
        ``seed``; on that error the call retries with the offending option
        dropped, so the strongest snapshot still works. Transient errors retry
        with a short backoff. Pass ``json_object=True`` to require a JSON-object
        reply (what ``complete_json`` uses).

        The spend gate runs before every network attempt and raises
        :class:`anki.pgrep.ai.usage.BudgetExceeded` rather than spending past a
        configured cap. Retries that eventually succeed record one event; a call
        that fails outright records one failure event, so a batch's error rate
        stays visible without counting a retry as spend.
        """
        import time

        base: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_object:
            base["response_format"] = {"type": "json_object"}
        # Try richest options first, then progressively drop unsupported ones.
        option_sets: list[dict[str, float | int | None]] = [
            {"temperature": self.temperature, "seed": self.seed},
            {"temperature": self.temperature},
            {"seed": self.seed},
            {},
        ]
        last_exc: Exception | None = None
        for options in option_sets:
            kwargs = dict(base)
            kwargs.update({k: v for k, v in options.items() if v is not None})
            for attempt in range(3):
                usage.check_budget(self.model)
                try:
                    resp = self._client.chat.completions.create(**kwargs)
                except Exception as exc:  # noqa: BLE001
                    name = type(exc).__name__
                    if name in ("BadRequestError", "UnprocessableEntityError"):
                        last_exc = exc
                        break  # option unsupported; try the next option set
                    if name in (
                        "RateLimitError",
                        "APITimeoutError",
                        "APIConnectionError",
                        "InternalServerError",
                    ):
                        last_exc = exc
                        time.sleep(2 * (attempt + 1))
                        continue
                    self._record(None, ok=False, error=name)
                    raise
                self._record(resp, ok=True)
                return resp.choices[0].message.content
        assert last_exc is not None
        self._record(None, ok=False, error=type(last_exc).__name__)
        raise last_exc

    def _record(
        self, resp: object | None, *, ok: bool, error: str | None = None
    ) -> None:
        prompt, completion, total = usage.usage_from_response(resp)
        usage.record(
            model=self.model,
            ok=ok,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            pinned=self.pinned,
            error=error,
        )

    def complete_json(self, system: str, user: str) -> dict:
        """One JSON-object completion, parsed. Uses ``complete_text``'s retries."""
        import json

        return json.loads(self.complete_text(system, user, json_object=True))


def _is_floating_alias(model: str) -> bool:
    """A model id with no dated snapshot suffix is a floating alias."""
    return _SNAPSHOT_RE.search(model) is None


def list_models() -> list[str]:
    """Model ids available on the account (needs the API key)."""
    from openai import OpenAI  # type: ignore[import-not-found]

    client = OpenAI()
    return sorted(m.id for m in client.models.list().data)


def _rank(model_id: str) -> tuple:
    for i, fam in enumerate(_FAMILY_RANK):
        if fam in model_id:
            dated = 1 if _SNAPSHOT_RE.search(model_id) else 0
            return (-i, dated, model_id)
    return (-len(_FAMILY_RANK), 0, model_id)


def _is_chat_snapshot(model_id: str) -> bool:
    """A chat-family model id that is not one of the non-chat variants."""
    m = model_id.lower()
    return any(f in m for f in _FAMILY_RANK) and not any(
        k in m for k in _NON_CHAT_MARKERS
    )


def pick_generator_snapshot(available: list[str] | None = None) -> str:
    """The strongest dated chat snapshot on the account, for the generator."""
    models = available if available is not None else list_models()
    dated = [m for m in models if _SNAPSHOT_RE.search(m) and _is_chat_snapshot(m)]
    pool = dated or [m for m in models if _is_chat_snapshot(m)]
    if not pool:
        raise RuntimeError("no suitable chat model found on the account")
    return sorted(pool, key=_rank, reverse=True)[0]


def pick_judge_snapshot(exclude: str, available: list[str] | None = None) -> str:
    """A dated chat snapshot different from ``exclude``, for the judge."""
    models = available if available is not None else list_models()
    pool = [
        m
        for m in models
        if m != exclude and _SNAPSHOT_RE.search(m) and _is_chat_snapshot(m)
    ]
    if not pool:
        # Fall back to any chat model that is not the generator.
        pool = [m for m in models if m != exclude and _is_chat_snapshot(m)]
    if not pool:
        raise RuntimeError("no distinct judge model found on the account")
    return sorted(pool, key=_rank, reverse=True)[0]


def generator_client(model: str) -> LLMClient:
    """An ``LLMClient`` for the generator, pinned to a dated snapshot.

    ``LLMClient`` refuses floating aliases, so a floating ``model`` (for example
    ``gpt-5.5``) is resolved to the strongest dated snapshot on the account --
    unless it is an allowlisted id on a configured gateway, which is used as is.
    """
    if _is_floating_alias(model) and not gateway_alias_allowed(model):
        model = pick_generator_snapshot()
    return LLMClient(model)


def judge_client(model: str, exclude: str = "") -> LLMClient:
    """An ``LLMClient`` for a judge, pinned to a dated snapshot.

    A floating ``model`` is resolved to a dated snapshot different from
    ``exclude`` (the generator, when there is one). An allowlisted gateway id is
    used as is, so the judge still has to be named a different model than the
    generator by the caller.
    """
    if _is_floating_alias(model) and not gateway_alias_allowed(model):
        model = pick_judge_snapshot(exclude)
    return LLMClient(model)


def _apply_env_file(path: str, *, keys: tuple[str, ...] | None = None) -> bool:
    """Load ``KEY=value`` lines from ``path`` into ``os.environ``.

    When ``keys`` is set, only those names are applied. Returns True if the file
    existed and was read. Values overwrite existing env entries so the TrueFoundry
    gateway file wins over stale direct provider keys left in a shell.
    """
    if not path or not os.path.isfile(path):
        return False
    wanted = frozenset(keys) if keys is not None else None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, val = stripped.split("=", 1)
            key = key.strip()
            if wanted is not None and key not in wanted:
                continue
            os.environ[key] = val.strip().strip('"').strip("'")
    return True


def load_api_key(env_file: str | None = None) -> None:
    """Ensure gateway credentials are in the environment for offline tools.

    Source of truth is ``~/.config/truefoundry/gateway.env`` (one TrueFoundry
    token + ``OPENAI_BASE_URL``). An explicit ``env_file`` is applied next for
    tests/overrides. ``content/.env`` / repo-root ``.env`` are last-resort
    fallbacks for non-gateway setups and must not hold direct provider keys.

    This is the one place that loads credentials, replacing per-tool copies.
    """
    if _apply_env_file(_TFY_GATEWAY_ENV, keys=_TFY_GATEWAY_VARS):
        if os.environ.get("OPENAI_API_KEY"):
            return
    if env_file:
        _apply_env_file(env_file)
        if os.environ.get("OPENAI_API_KEY"):
            return
    here = os.path.dirname(os.path.abspath(__file__))
    # llm.py -> ai -> pgrep -> anki -> pylib -> repo root
    repo = os.path.abspath(os.path.join(here, *([os.pardir] * 5)))
    for base in (os.getcwd(), repo):
        for rel in ("content/.env", ".env"):
            path = os.path.join(base, *rel.split("/"))
            if _apply_env_file(path, keys=("OPENAI_API_KEY", "OPENAI_BASE_URL")):
                if os.environ.get("OPENAI_API_KEY"):
                    return


def has_api_key() -> bool:
    """True when an OpenAI-compatible key is available (loads the gateway once)."""
    if os.environ.get("OPENAI_API_KEY"):
        return True
    load_api_key()
    return bool(os.environ.get("OPENAI_API_KEY"))
