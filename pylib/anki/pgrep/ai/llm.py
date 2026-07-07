# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The pinned LLM client for generation (L4.0f).

One thin wrapper over the OpenAI client so every call is reproducible and
recorded: an exact dated model snapshot (never a floating alias), a low
temperature, a seed when the model supports it, and JSON-only responses. The
generator uses the strongest available snapshot; the judge (elsewhere) uses a
different one so it never grades its own output.

``openai`` is imported lazily, so an AI-off app never loads it and importing this
module stays cheap. Snapshot discovery is a helper for pinning at gate time; the
resolved IDs go straight into the run manifest.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

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


class LLMClient:
    """A pinned OpenAI chat client that returns JSON objects."""

    def __init__(self, model: str, *, temperature: float = 0.0, seed: int | None = 7):
        from openai import OpenAI  # type: ignore[import-not-found]

        if _is_floating_alias(model):
            raise ValueError(
                f"refusing a floating alias '{model}'; pin an exact dated snapshot"
            )
        self.model = model
        self.temperature = temperature
        self.seed = seed
        self._client = OpenAI()

    def complete_text(
        self, system: str, user: str, *, json_object: bool = False
    ) -> str:
        """One completion, returned as the raw response text.

        Reasoning and gpt-5 snapshots can reject a non-default ``temperature`` or
        ``seed``; on that error the call retries with the offending option
        dropped, so the strongest snapshot still works. Transient errors retry
        with a short backoff. Pass ``json_object=True`` to require a JSON-object
        reply (what ``complete_json`` uses).
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
                try:
                    resp = self._client.chat.completions.create(**kwargs)
                    return resp.choices[0].message.content
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
                    raise
        assert last_exc is not None
        raise last_exc

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
    ``gpt-5.5``) is resolved to the strongest dated snapshot on the account.
    """
    if _is_floating_alias(model):
        model = pick_generator_snapshot()
    return LLMClient(model)


def judge_client(model: str, exclude: str = "") -> LLMClient:
    """An ``LLMClient`` for a judge, pinned to a dated snapshot.

    A floating ``model`` is resolved to a dated snapshot different from
    ``exclude`` (the generator, when there is one).
    """
    if _is_floating_alias(model):
        model = pick_judge_snapshot(exclude)
    return LLMClient(model)


def load_api_key(env_file: str | None = None) -> None:
    """Ensure ``OPENAI_API_KEY`` is in the environment for the offline tools.

    If it is already set, do nothing. Otherwise read it from ``env_file`` (when
    given), then ``content/.env``, then ``.env`` at the repo root, and set it on
    ``os.environ`` so a plain ``OpenAI()`` (as ``LLMClient`` builds) picks it up.
    This is the one place that loads the key, replacing the per-tool copies.
    """
    if os.environ.get("OPENAI_API_KEY"):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    # llm.py -> ai -> pgrep -> anki -> pylib -> repo root
    repo = os.path.abspath(os.path.join(here, *([os.pardir] * 5)))
    bases = [os.getcwd(), repo]
    candidates: list[str] = [env_file] if env_file else []
    for base in bases:
        candidates.append(os.path.join(base, "content", ".env"))
        candidates.append(os.path.join(base, ".env"))
    for path in candidates:
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip().startswith("OPENAI_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        os.environ["OPENAI_API_KEY"] = val
                        return


def has_api_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))
