# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Quarantined multi-model shadow-foundry CLI.

Retrieves corpus excerpts on the host, runs Sol/Opus/Grok candidates through an
injectable backend (fake in CI, Cursor sandbox in real mode), and atomically
publishes non-training artifacts under ``content/run/shadow-foundry/``.

Shadow runs never write ``accepted.json``, ``preferences.jsonl``, mutate the
bundle, call assemble, or mark candidates training-eligible.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import (  # type: ignore[import-not-found]  # noqa: E402
    generation_core,
    model_backend,
    shadow_portfolio,
)

SUCCESS_MARKER = "_SUCCESS"
DEFAULT_OUTPUT_ROOT = Path("content/run/shadow-foundry")
DEFAULT_N = 3
DEFAULT_TOPIC = "mechanics/circular-motion"
DEFAULT_SEED = 7
DEFAULT_REASONING = "high"

_PRIVATE_MARKER = re.compile(
    r"(?i)(?<![a-z0-9])(?:"
    r"(?:gold|ets|gr9677|gr1777)(?=$|[-_/:\\])"
    r"|held[\s_-]*out(?=$|[\s_/:\\-])"
    r"|tier[\s_-]*3(?=$|[\s_/:\\-])"
    r")"
)
_SOURCE_PATH_MARKER = re.compile(
    r"(?i)(?:^|[\s\"'=])(?:/|\\\\|[A-Za-z]:\\)"
    r"|content/(?:gold|heldout|tier3-private|corpus|index)/"
    r"|\.(?:pdf|json|jsonl|db)\b"
)

SearchFn = Callable[..., Sequence[object]]


def _reject_private_markers(value: object, path: str = "$") -> None:
    if type(value) is str:
        if match := _PRIVATE_MARKER.search(value):
            raise ValueError(
                f"{path}: private marker {match.group(0)!r} is not allowed"
            )
        return
    if type(value) is dict:
        mapping = cast(dict[str, object], value)
        for key, nested in mapping.items():
            child = f"{path}.{key}" if path != "$" else str(key)
            if type(key) is str and (match := _PRIVATE_MARKER.search(key)):
                raise ValueError(
                    f"{child} (key): private marker {match.group(0)!r} is not allowed"
                )
            _reject_private_markers(nested, child)
        return
    if type(value) is list or type(value) is tuple:
        for index, nested in enumerate(value):
            _reject_private_markers(nested, f"{path}[{index}]")


def _non_empty_string(value: object, *, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_run_id(run_id: str) -> None:
    if (
        not run_id.strip()
        or Path(run_id).name != run_id
        or run_id in {".", ".."}
        or "\\" in run_id
    ):
        raise ValueError("run ID must be a non-empty directory name")
    _reject_private_markers(run_id, "run_id")


def resolve_code_sha() -> str:
    """Return the current repository HEAD SHA, or ``unknown`` offline."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    sha = completed.stdout.strip()
    return sha or "unknown"


def sanitize_retrieved(chunks: Sequence[object]) -> list[dict[str, str]]:
    """Keep only sandbox-safe chunk fields and reject private markers/paths."""
    if not chunks:
        raise ValueError("retrieved context must be non-empty")
    sanitized: list[dict[str, str]] = []
    for index, item in enumerate(chunks):
        if (
            hasattr(item, "chunk_id")
            and hasattr(item, "source_ref")
            and hasattr(item, "text")
        ):
            chunk_id = getattr(item, "chunk_id")
            source_ref = getattr(item, "source_ref")
            text = getattr(item, "text")
        elif isinstance(item, Mapping):
            chunk_id = item.get("chunk_id")
            source_ref = item.get("source_ref")
            text = item.get("text")
        else:
            raise ValueError(f"retrieved[{index}] must expose chunk fields")
        chunk_id_s = _non_empty_string(chunk_id, name=f"retrieved[{index}].chunk_id")
        source_ref_s = _non_empty_string(
            source_ref, name=f"retrieved[{index}].source_ref"
        )
        text_s = _non_empty_string(text, name=f"retrieved[{index}].text")
        for label, value in (
            ("chunk_id", chunk_id_s),
            ("source_ref", source_ref_s),
            ("text", text_s),
        ):
            _reject_private_markers(value, f"retrieved[{index}].{label}")
            if _SOURCE_PATH_MARKER.search(value):
                raise ValueError(
                    f"retrieved[{index}].{label}: source path is not allowed in "
                    "sandbox context"
                )
        sanitized.append(
            {
                "chunk_id": chunk_id_s,
                "source_ref": source_ref_s,
                "text": text_s,
            }
        )
    _reject_private_markers(sanitized, "retrieved")
    return sanitized


def validate_exact_roles(
    roles: shadow_portfolio.ModelRoles,
    probe_models: Sequence[Mapping[str, object]] | Sequence[object],
) -> list[str]:
    """Require exact, distinct, non-auto IDs present in the account probe."""
    if type(roles) is not shadow_portfolio.ModelRoles:
        raise TypeError("roles must be ModelRoles")
    available: set[str] = set()
    for index, entry in enumerate(probe_models):
        if isinstance(entry, Mapping):
            model_id = entry.get("id") or entry.get("model_id")
        else:
            model_id = entry
        model_id_s = _non_empty_string(model_id, name=f"probe_models[{index}].id")
        available.add(model_id_s)

    requested = {
        "sol": roles.sol.model_id,
        "opus": roles.opus.model_id,
        "grok": roles.grok.model_id,
    }
    if len(set(requested.values())) != 3:
        raise ValueError("exact model roles must use distinct model IDs")
    for family, model_id in requested.items():
        lowered = model_id.strip().lower()
        if lowered == "auto" or lowered.startswith("auto/"):
            raise ValueError(
                f"{family} model {model_id!r} rejects auto/substitution; "
                "pass an exact probed model ID"
            )
        if model_id not in available:
            raise ValueError(
                f"exact model {model_id!r} for {family} is not in the account probe"
            )
    return [requested["sol"], requested["opus"], requested["grok"]]


def format_probe(
    models: Sequence[Mapping[str, object]] | Sequence[object],
) -> tuple[str, dict[str, object]]:
    """Render a human-readable probe list and a JSON payload."""
    rows: list[dict[str, object]] = []
    lines = ["Available Cursor models:"]
    for index, entry in enumerate(models):
        if isinstance(entry, Mapping):
            model_id = entry.get("id") or entry.get("model_id") or ""
            name = entry.get("name") or ""
            row = {str(key): value for key, value in entry.items()}
        else:
            model_id = str(entry)
            name = ""
            row = {"id": model_id}
        model_id_s = _non_empty_string(model_id, name=f"models[{index}].id")
        row["id"] = model_id_s
        rows.append(row)
        suffix = f" ({name})" if name else ""
        lines.append(f"  - {model_id_s}{suffix}")
    payload: dict[str, object] = {"models": rows, "count": len(rows)}
    return "\n".join(lines) + "\n", payload


def _write_shadow_files(temporary: Path, rendered: Mapping[str, str]) -> None:
    for filename, content in rendered.items():
        (temporary / filename).write_text(content, encoding="utf-8")
    for name in ("preferences.jsonl", "accepted.json"):
        if (temporary / name).exists():
            raise ValueError(f"shadow runs must not emit {name}")
    (temporary / SUCCESS_MARKER).write_text("ok\n", encoding="utf-8")


def publish_run(
    output_root: Path | str,
    run_id: str,
    *,
    candidates: Sequence[object],
    failures: Sequence[object],
    manifest: Mapping[str, object],
) -> Path:
    """Atomically publish a complete shadow run with a ``_SUCCESS`` marker."""
    _validate_run_id(run_id)
    out_dir = Path(output_root)
    run_dir = out_dir / run_id
    if run_dir.exists():
        raise ValueError(f"shadow run directory already exists: {run_dir}")

    payloads: dict[str, object] = {
        "manifest.json": dict(manifest),
        "candidates.json": list(candidates),
        "failures.json": list(failures),
    }
    for name, payload in payloads.items():
        _reject_private_markers(payload, name)

    if payloads["manifest.json"].get("training_eligible", False):
        raise ValueError("shadow manifests must set training_eligible to false")

    rendered = {
        filename: json.dumps(payload, indent=2, allow_nan=False) + "\n"
        for filename, payload in payloads.items()
    }

    temporary: Path | None = None
    lock_path = out_dir / f".{run_id}.lock"
    lock_fd: int | None = None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as error:
            raise ValueError(
                f"shadow run publication lock already exists: {lock_path}"
            ) from error
        os.write(lock_fd, f"pid={os.getpid()}\n".encode())
        if run_dir.exists():
            raise ValueError(f"shadow run directory already exists: {run_dir}")
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{run_id}.", suffix=".tmp", dir=out_dir)
        )
        _write_shadow_files(temporary, rendered)
        if run_dir.exists():
            raise ValueError(f"shadow run directory already exists: {run_dir}")
        os.rename(temporary, run_dir)
        temporary = None
    except OSError as error:
        raise ValueError(f"could not persist shadow run {run_id!r}: {error}") from error
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        if lock_fd is not None:
            os.close(lock_fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
    return run_dir


def _append_trace_hashes(hashes: list[str], traces: object) -> None:
    if not isinstance(traces, list):
        return
    for trace in traces:
        if isinstance(trace, Mapping) and type(trace.get("request_hash")) is str:
            hashes.append(str(trace["request_hash"]))


def _collect_request_hashes(candidates: Sequence[Mapping[str, object]]) -> list[str]:
    hashes: list[str] = []
    for candidate in candidates:
        generator = candidate.get("generator")
        if isinstance(generator, Mapping):
            _append_trace_hashes(hashes, generator.get("traces"))
        for verifier in candidate.get("verifiers", []) or []:
            if not isinstance(verifier, Mapping):
                continue
            trace = verifier.get("trace")
            if isinstance(trace, Mapping) and type(trace.get("request_hash")) is str:
                hashes.append(str(trace["request_hash"]))
            _append_trace_hashes(hashes, verifier.get("traces"))
    return hashes


def _family_coverage(candidates: Sequence[Mapping[str, object]]) -> set[str]:
    return {
        str(item["origin_family"])
        for item in candidates
        if isinstance(item, Mapping) and "origin_family" in item
    }


def _trace_run_ids(traces: object) -> list[object]:
    if not isinstance(traces, list):
        return []
    run_ids: list[object] = []
    for trace in traces:
        if not isinstance(trace, Mapping):
            continue
        result = trace.get("result")
        if isinstance(result, Mapping):
            run_ids.append(result.get("run_id"))
    return run_ids


def run_shadow(
    *,
    roles: shadow_portfolio.ModelRoles,
    backend: model_backend.ModelBackend,
    output_root: Path | str,
    search_fn: SearchFn,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    topic: str = DEFAULT_TOPIC,
    run_id: str | None = None,
    probe_models: Sequence[Mapping[str, object]] | Sequence[object] | None = None,
    code_sha: str | None = None,
) -> Path:
    """Allocate, generate, cross-solve, and publish one complete shadow run."""
    if n < 3:
        raise ValueError("shadow runs require n >= 3 so all three families allocate")
    probe = list(probe_models or [])
    validate_exact_roles(roles, probe)

    allocations = shadow_portfolio.allocate_families(n, seed=seed)
    if set(allocations) != {"sol", "opus", "grok"}:
        raise RuntimeError("allocation must cover all three model families")

    resolved_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    sha = resolve_code_sha() if code_sha is None else code_sha
    candidates: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []

    for index, origin in enumerate(allocations):
        slot_seed = seed + index
        try:
            raw_chunks = search_fn(topic, k=generation_core.CONTEXT_CHUNKS)
            chunks = sanitize_retrieved(raw_chunks)
            _reject_private_markers(chunks, f"slot[{index}].retrieved")
            record = shadow_portfolio.run_candidate(
                topic=topic,
                retrieved=chunks,
                origin=origin,
                roles=roles,
                backend=backend,
                seed=slot_seed,
            )
            _reject_private_markers(record, f"slot[{index}].candidate")
            candidates.append(record)
        except Exception as err:  # noqa: BLE001
            failures.append(
                {
                    "slot": index,
                    "origin_family": origin,
                    "seed": slot_seed,
                    "error": f"{type(err).__name__}: {err}",
                    "traces": list(getattr(err, "traces", ()) or ()),
                }
            )

    covered = _family_coverage(candidates)
    if covered != {"sol", "opus", "grok"} or failures:
        raise RuntimeError(
            "shadow run must complete all three model families before publication; "
            f"completed={sorted(covered)}; failures={len(failures)}"
        )

    _text, probe_payload = format_probe(probe)
    del _text
    manifest: dict[str, object] = {
        "run_id": resolved_run_id,
        "schema_version": shadow_portfolio.SCHEMA_VERSION,
        "prompt_versions": {
            "generator": shadow_portfolio.GENERATOR_PROMPT_VERSION,
            "correction": shadow_portfolio.CORRECTION_PROMPT_VERSION,
            "verifier": shadow_portfolio.VERIFIER_PROMPT_VERSION,
            "generation_core_problem": generation_core.PROBLEM_PROMPT_VERSION,
        },
        "schema_versions": {
            "problem": shadow_portfolio.SCHEMA_VERSION,
            "solve": shadow_portfolio.VERIFIER_SCHEMA_VERSION,
        },
        "roles": {
            "sol": roles.sol.model_id,
            "opus": roles.opus.model_id,
            "grok": roles.grok.model_id,
        },
        "seed": seed,
        "n": n,
        "topic": topic,
        "allocation": allocations,
        "code_sha": sha,
        "probe": probe_payload,
        "request_hashes": _collect_request_hashes(candidates),
        "sdk_run_ids": [
            {
                "origin_family": item.get("origin_family"),
                "generator_run_ids": _trace_run_ids(
                    cast(Mapping[str, object], item.get("generator", {})).get("traces")
                ),
                "verifier_run_ids": [
                    cast(Mapping[str, object], verifier.get("trace", {})).get("run_id")
                    if isinstance(verifier.get("trace"), Mapping)
                    else None
                    for verifier in item.get("verifiers", []) or []
                    if isinstance(verifier, Mapping)
                ],
            }
            for item in candidates
        ],
        "retry_parser_outcomes": [
            {
                "origin_family": item.get("origin_family"),
                "generator_phases": [
                    cast(Mapping[str, object], trace).get("phase")
                    for trace in cast(
                        Mapping[str, object], item.get("generator", {})
                    ).get("traces", [])
                    or []
                    if isinstance(trace, Mapping)
                ],
                "generator_parse_errors": [
                    cast(Mapping[str, object], trace).get("parse_error")
                    for trace in cast(
                        Mapping[str, object], item.get("generator", {})
                    ).get("traces", [])
                    or []
                    if isinstance(trace, Mapping)
                ],
            }
            for item in candidates
        ],
        "training_eligible": False,
        "artifacts": {
            "accepted.json": False,
            "preferences.jsonl": False,
            "assemble_bundle": False,
        },
    }
    _reject_private_markers(manifest, "manifest")
    _reject_private_markers(candidates, "candidates")
    _reject_private_markers(failures, "failures")
    return publish_run(
        output_root,
        resolved_run_id,
        candidates=candidates,
        failures=failures,
        manifest=manifest,
    )


def _offline_search(query: str, k: int = 6, **_kwargs: object) -> list[dict[str, str]]:
    del query, k
    return [
        {
            "chunk_id": "chunk-self-check-1",
            "source_ref": "OpenStax University Physics, p. 1",
            "text": (
                "Uniform circular motion keeps speed constant while the velocity "
                "vector changes direction."
            ),
        }
    ]


def _offline_candidate() -> dict[str, object]:
    return {
        "stem": "A particle moves in a circle. Which statement is correct?",
        "choices": [
            "The speed is constant.",
            "The velocity is constant.",
            "The acceleration is zero.",
            "The momentum is zero.",
            "The radius must increase.",
        ],
        "key": "A",
        "distractors": [
            {
                "label": "B",
                "misconception_tag": "speed-is-velocity",
                "rationale": "Confuses constant speed with constant velocity.",
            },
            {
                "label": "C",
                "misconception_tag": "no-tangential-change",
                "rationale": "Ignores centripetal acceleration.",
            },
            {
                "label": "D",
                "misconception_tag": "vector-cancellation",
                "rationale": "Treats changing momentum as zero momentum.",
            },
            {
                "label": "E",
                "misconception_tag": "radius-drift",
                "rationale": "Assumes circular motion cannot stay bounded.",
            },
        ],
        "solution_decomposition": [
            {
                "subgoal": "Separate speed from velocity.",
                "rubric": "Identifies velocity as a vector.",
            },
            {
                "subgoal": "Identify the invariant scalar.",
                "rubric": "Uses the definition of uniform circular motion.",
            },
        ],
        "problem_kind": "conceptual",
        "difficulty": 0.4,
        "confidence": 0.8,
        "computational": None,
        "refuse": False,
    }


class _SelfCheckBackend:
    def __init__(self) -> None:
        self.requests: list[model_backend.ModelRequest] = []
        self._payload = json.dumps(_offline_candidate())

    def complete(
        self,
        request: model_backend.ModelRequest,
    ) -> model_backend.ModelResult:
        self.requests.append(request)
        if request.role == "generator":
            text = self._payload
        else:
            text = json.dumps(
                {
                    "answer": "A",
                    "reasoning": f"{request.model.family} independent solve",
                    "confidence": 0.75,
                }
            )
        call = len(self.requests)
        return model_backend.ModelResult(
            request_id=request.request_id,
            model_id=request.model.model_id,
            status="finished",
            text=text,
            agent_id=f"self-check-agent-{call}",
            run_id=f"self-check-run-{call}",
        )


def self_check(*, output_root: Path | str | None = None) -> int:
    """Run a fully offline fake-client shadow publication smoke."""
    root = Path(output_root) if output_root is not None else Path(DEFAULT_OUTPUT_ROOT)
    roles = shadow_portfolio.ModelRoles(
        sol=model_backend.ModelSpec("sol", "gpt-5.6-sol-max", DEFAULT_REASONING),
        opus=model_backend.ModelSpec(
            "opus",
            "claude-opus-4-8-thinking-high-fast",
            DEFAULT_REASONING,
        ),
        grok=model_backend.ModelSpec(
            "grok",
            "cursor-grok-4.5-high-fast",
            DEFAULT_REASONING,
        ),
    )
    probe = [
        {"id": "gpt-5.6-sol-max"},
        {"id": "claude-opus-4-8-thinking-high-fast"},
        {"id": "cursor-grok-4.5-high-fast"},
    ]
    run_dir = run_shadow(
        roles=roles,
        backend=_SelfCheckBackend(),
        output_root=root,
        search_fn=_offline_search,
        n=3,
        seed=DEFAULT_SEED,
        topic=DEFAULT_TOPIC,
        run_id=f"self-check-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}",
        probe_models=probe,
        code_sha="self-check",
    )
    if not (run_dir / SUCCESS_MARKER).exists():
        raise RuntimeError("self-check did not publish _SUCCESS")
    if (run_dir / "preferences.jsonl").exists() or (run_dir / "accepted.json").exists():
        raise RuntimeError("self-check emitted training artifacts")
    print(f"[ok] shadow-foundry self-check passed; wrote {run_dir}")
    return 0


def _load_api_key() -> str:
    key = os.environ.get("CURSOR_API_KEY", "").strip()
    if key:
        return key
    for candidate in (Path("content/.env"), Path(".env")):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.startswith("CURSOR_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _real_probe_models() -> list[dict[str, object]]:
    import cursor_sandbox

    api_key = _load_api_key()
    if not api_key:
        raise RuntimeError("CURSOR_API_KEY is required for --probe-models / --shadow")
    sandbox = cursor_sandbox.CursorSandbox(
        cursor_sandbox.SandboxConfig(),
        api_key=api_key,
    )
    models = sandbox.list_models()
    return [dict(model) for model in models]


def _real_backend() -> model_backend.ModelBackend:
    import cursor_sandbox

    api_key = _load_api_key()
    if not api_key:
        raise RuntimeError("CURSOR_API_KEY is required for --shadow")
    sandbox = cursor_sandbox.CursorSandbox(
        cursor_sandbox.SandboxConfig(),
        api_key=api_key,
    )

    class _SandboxBackend:
        def complete(
            self,
            request: model_backend.ModelRequest,
        ) -> model_backend.ModelResult:
            _reject_private_markers(request.to_dict(), "request")
            return sandbox.complete(request)

    return _SandboxBackend()


def _real_search(query: str, k: int = 6, **_kwargs: object) -> Sequence[object]:
    from pgrep.ai import retrieval  # type: ignore[import-not-found]

    return retrieval.search(query, k=k)


def _build_roles(
    *,
    sol_model: str,
    opus_model: str,
    grok_model: str,
) -> shadow_portfolio.ModelRoles:
    return shadow_portfolio.ModelRoles(
        sol=model_backend.ModelSpec("sol", sol_model, DEFAULT_REASONING),
        opus=model_backend.ModelSpec("opus", opus_model, DEFAULT_REASONING),
        grok=model_backend.ModelSpec("grok", grok_model, DEFAULT_REASONING),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Quarantined multi-model shadow foundry. Never lands content or "
            "preference pairs."
        )
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run a fully offline fake-client smoke and exit",
    )
    parser.add_argument(
        "--probe-models",
        action="store_true",
        help="list account-available Cursor models without generating content",
    )
    parser.add_argument(
        "--shadow",
        action="store_true",
        help="run quarantined multi-model generation and publish a shadow run",
    )
    parser.add_argument("--sol-model", help="exact Sol model ID from the account probe")
    parser.add_argument(
        "--opus-model", help="exact Opus model ID from the account probe"
    )
    parser.add_argument(
        "--grok-model", help="exact Grok model ID from the account probe"
    )
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument(
        "--run",
        help="new run directory name under --out (default: UTC timestamp)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    selected = sum(
        bool(flag) for flag in (args.self_check, args.probe_models, args.shadow)
    )
    if selected != 1:
        parser.error("choose exactly one of --self-check, --probe-models, or --shadow")

    if args.self_check:
        return self_check(output_root=args.out)

    if args.probe_models:
        models = _real_probe_models()
        text, payload = format_probe(models)
        print(text, end="")
        print(json.dumps(payload, indent=2, allow_nan=False))
        return 0

    if not args.sol_model or not args.opus_model or not args.grok_model:
        parser.error(
            "--shadow requires --sol-model, --opus-model, and --grok-model "
            "(exact IDs from --probe-models)"
        )
    if args.n < 3:
        parser.error("--n must be at least 3 so all three families allocate")

    roles = _build_roles(
        sol_model=args.sol_model,
        opus_model=args.opus_model,
        grok_model=args.grok_model,
    )
    probe = _real_probe_models()
    validate_exact_roles(roles, probe)
    run_dir = run_shadow(
        roles=roles,
        backend=_real_backend(),
        output_root=args.out,
        search_fn=_real_search,
        n=args.n,
        seed=args.seed,
        topic=args.topic,
        run_id=args.run,
        probe_models=probe,
    )
    print(f"wrote quarantined shadow run {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
