# Multi-model shadow runner implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate quarantined, corpus-grounded Physics GRE candidates with Sol,
Opus, and Grok through a filesystem-sandboxed Cursor SDK runner, without
enabling acceptance, bundle landing, or preference-pair emission.

**Architecture:** Standard-library protocol types live in the shipped AI layer.
The optional Cursor SDK runs inside a disposable OCI image whose only host mount
is one request directory. A tracked content tool retrieves corpus excerpts,
allocates candidates across exact user-selected model IDs, cross-verifies each
candidate with the other two families, and atomically publishes a shadow run.

**Tech Stack:** Python 3.13, `cursor-sdk` in an isolated worker project, a
Docker-only local runtime for the first implementation, existing
`generation_core`, `retrieval`, `consensus`, `verify`, `provenance`, pytest,
and `just`.

## Global constraints

- Shadow output cannot enter `content_bundle.json`, `assemble_bundle.py`, or a
  preference JSONL file.
- No gold, held-out, human-label, or private-item path may enter a model request
  or request manifest.
- The runner must call `Cursor.models.list()` and require three explicit model
  IDs. It never uses `auto` or silently substitutes a model.
- Desired families are GPT-5.6 Sol, Claude Opus 4.8, and Grok 4.5.
- A candidate's originating family cannot be one of its two independent
  cross-verifiers.
- SymPy, provenance, schema, and leakage failures override model agreement.
- The Cursor SDK process runs inside a Docker container with only the request
  directory mounted. A host working-directory convention is not isolation.
- If a verified local Docker Unix socket, the requested models, the API key,
  or the mount boundary is unavailable, fail before the first candidate call.
  The first implementation does not claim or silently accept Podman or another
  runtime.
- All CI tests use fakes. No network, model, corpus index, Cursor key, or OCI
  runtime is required in CI.
- Raw artifacts live below git-ignored `content/run/shadow-foundry/`.
- No em dashes in code, comments, docs, commits, or chat.

---

## File structure

- Create `pylib/anki/pgrep/ai/model_backend.py`: request/result/model dataclasses
  and the provider-neutral backend protocol.
- Create `pylib/anki/pgrep/ai/shadow_portfolio.py`: deterministic model
  allocation, origin-excluding verifier assignment, strict response parsing,
  and pure run assembly.
- Create `content/tools/cursor_sandbox.py`: OCI command construction, request
  directory creation, subprocess execution, and response loading.
- Create `content/tools/shadow_foundry.py`: corpus retrieval, model probe,
  portfolio orchestration, firewall checks, and atomic run publication.
- Create `tools/shadow_worker/pyproject.toml`, `uv.lock`, `Dockerfile`, and
  `worker.py`: the minimal Cursor SDK process placed inside the OCI image.
- Create `pylib/tests/test_pgrep_model_backend.py`.
- Create `pylib/tests/test_pgrep_shadow_portfolio.py`.
- Create `content/tools/test_cursor_sandbox.py`.
- Create `content/tools/test_shadow_foundry.py`.
- Modify `justfile`: add `shadow-models`, `shadow-smoke`, and
  `shadow-foundry` recipes.
- Modify `docs_pgrep/reference/content-pipeline.md`: document shadow-only
  commands and artifacts.

---

### Task 1: Provider-neutral request and result contract

**Files:**

- Create: `pylib/anki/pgrep/ai/model_backend.py`
- Test: `pylib/tests/test_pgrep_model_backend.py`

**Interfaces:**

- Produces `ModelSpec`, `ModelRequest`, `ModelResult`, `ModelBackend`, and
  `request_hash()`.
- Later tasks serialize `ModelRequest.to_dict()` and validate
  `ModelResult.from_dict()`.

- [ ] **Step 1: Write the failing contract tests**

```python
# pylib/tests/test_pgrep_model_backend.py
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import pytest

from anki.pgrep.ai import model_backend


def _request() -> model_backend.ModelRequest:
    return model_backend.ModelRequest(
        request_id="req-1",
        role="generator",
        model=model_backend.ModelSpec(
            family="sol",
            model_id="gpt-5.6-sol-max",
            reasoning_effort="high",
        ),
        system="Return JSON.",
        user="CORPUS CONTEXT: x",
        prompt_version="shadow-problem-v1",
        schema_version="pgrep-shadow-problem/v1",
        seed=7,
        corpus_chunk_ids=("chunk-1",),
        source_refs=("OpenStax, p. 1",),
    )


def test_request_round_trip_and_hash_are_stable() -> None:
    request = _request()
    restored = model_backend.ModelRequest.from_dict(request.to_dict())
    assert restored == request
    assert model_backend.request_hash(restored) == model_backend.request_hash(request)


def test_request_rejects_private_markers() -> None:
    payload = _request().to_dict()
    payload["user"] = "content/tier3-private/items/form.json"
    with pytest.raises(ValueError, match="private marker"):
        model_backend.ModelRequest.from_dict(payload)


def test_result_requires_matching_request_and_model() -> None:
    request = _request()
    with pytest.raises(ValueError, match="request_id"):
        model_backend.ModelResult.from_dict(
            {
                "request_id": "other",
                "model_id": request.model.model_id,
                "status": "finished",
                "text": "{}",
            },
            expected=request,
        )
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PYTEST_ADDOPTS='-q pylib/tests/test_pgrep_model_backend.py' just test-py
```

Expected: import failure for `model_backend`.

- [ ] **Step 3: Implement the minimal standard-library contract**

```python
# pylib/anki/pgrep/ai/model_backend.py
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Protocol

_PRIVATE_MARKERS = (
    "content/gold",
    "content/heldout",
    "tier3-private",
    "gr9677",
    "gr1777",
)


@dataclass(frozen=True)
class ModelSpec:
    family: str
    model_id: str
    reasoning_effort: str


@dataclass(frozen=True)
class ModelRequest:
    request_id: str
    role: str
    model: ModelSpec
    system: str
    user: str
    prompt_version: str
    schema_version: str
    seed: int
    corpus_chunk_ids: tuple[str, ...]
    source_refs: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "ModelRequest":
        rendered = json.dumps(value, sort_keys=True).lower()
        if any(marker in rendered for marker in _PRIVATE_MARKERS):
            raise ValueError("model request contains a private marker")
        model = ModelSpec(**value["model"])
        return cls(
            request_id=value["request_id"],
            role=value["role"],
            model=model,
            system=value["system"],
            user=value["user"],
            prompt_version=value["prompt_version"],
            schema_version=value["schema_version"],
            seed=int(value["seed"]),
            corpus_chunk_ids=tuple(value["corpus_chunk_ids"]),
            source_refs=tuple(value["source_refs"]),
        )


@dataclass(frozen=True)
class ModelResult:
    request_id: str
    model_id: str
    status: str
    text: str
    agent_id: str = ""
    run_id: str = ""
    error: str = ""

    @classmethod
    def from_dict(cls, value: dict, *, expected: ModelRequest) -> "ModelResult":
        result = cls(**value)
        if result.request_id != expected.request_id:
            raise ValueError("result request_id does not match request")
        if result.model_id != expected.model.model_id:
            raise ValueError("result model_id does not match request")
        return result


class ModelBackend(Protocol):
    def complete(self, request: ModelRequest) -> ModelResult: ...


def request_hash(request: ModelRequest) -> str:
    raw = json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()
```

Add the standard AGPL header and validate non-empty strings, finite values, and
allowed role/reasoning values before GREEN.

- [ ] **Step 4: Run focused and neighboring tests**

```bash
PYTEST_ADDOPTS='-q pylib/tests/test_pgrep_model_backend.py pylib/tests/test_pgrep_llm_client.py' just test-py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/model_backend.py pylib/tests/test_pgrep_model_backend.py
git commit -m "feat(pgrep): add provider-neutral model request contract"
```

---

### Task 2: Cursor SDK worker and exact model probe

**Files:**

- Create: `tools/shadow_worker/pyproject.toml`
- Create: `tools/shadow_worker/uv.lock`
- Create: `tools/shadow_worker/Dockerfile`
- Create: `tools/shadow_worker/worker.py`
- Create: `content/tools/test_cursor_worker_protocol.py`

**Interfaces:**

- Worker reads `/work/request.json` and writes `/work/result.json`.
- Request actions are `models` and `prompt`.
- `models` returns account-valid IDs and parameter metadata.
- `prompt` requires one exact listed model ID.

- [ ] **Step 1: Create the isolated worker project with the package manager**

Run:

```bash
uv init --bare tools/shadow_worker
uv add --project tools/shadow_worker cursor-sdk
uv lock --project tools/shadow_worker
```

Expected: a worker-local `pyproject.toml` and `uv.lock`; no root dependency
change.

- [ ] **Step 2: Write failing worker-protocol tests**

```python
def test_models_action_serializes_account_ids(fake_cursor, tmp_path):
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text('{"action":"models"}')
    worker.run(request, result, cursor=fake_cursor)
    payload = json.loads(result.read_text())
    assert [m["id"] for m in payload["models"]] == [
        "claude-opus-4-8-thinking-high-fast",
        "cursor-grok-4.5-high-fast",
        "gpt-5.6-sol-max",
    ]


def test_prompt_rejects_unlisted_model(fake_cursor, tmp_path):
    with pytest.raises(ValueError, match="not available"):
        worker.run_prompt(
            {"model_id": "auto", "prompt": "x"},
            cursor=fake_cursor,
        )
```

Use an import loader so root tests do not import `cursor_sdk`.

- [ ] **Step 3: Implement `worker.py`**

The implementation must import the optional SDK lazily so root CI can load the
worker protocol without installing `cursor-sdk`:

```python
def list_models(*, sdk=None) -> list[dict]:
    if sdk is None:
        from cursor_sdk import Cursor
        sdk = Cursor
    return [
        {
            "id": model.id,
            "parameters": getattr(model, "parameters", {}),
            "presets": getattr(model, "presets", []),
        }
        for model in sdk.models.list()
    ]


def prompt(payload: dict, *, api_key: str, workdir: str, sdk=None) -> dict:
    if sdk is None:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    else:
        Agent = sdk.Agent
        AgentOptions = sdk.AgentOptions
        LocalAgentOptions = sdk.LocalAgentOptions
    available = {model["id"] for model in list_models(sdk=sdk)}
    model_id = payload["model_id"]
    if model_id not in available or model_id == "auto":
        raise ValueError(f"model {model_id!r} is not available")
    result = Agent.prompt(
        payload["prompt"],
        AgentOptions(
            api_key=api_key,
            model=model_id,
            local=LocalAgentOptions(cwd=workdir),
        ),
    )
    return {
        "status": result.status,
        "text": result.result or "",
        "agent_id": getattr(result, "agent_id", ""),
        "run_id": getattr(result, "id", ""),
        "model_id": model_id,
    }
```

The worker must distinguish startup exceptions from returned error statuses and
must never print the API key or prompt.

- [ ] **Step 4: Add the OCI image**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /worker
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY worker.py ./
ENTRYPOINT ["/worker/.venv/bin/python", "/worker/worker.py"]
```

- [ ] **Step 5: Run worker tests and lock validation**

```bash
out/pyenv/bin/pytest -q content/tools/test_cursor_worker_protocol.py
uv sync --project tools/shadow_worker --locked
```

Expected: PASS, no network after the locked environment is installed.

- [ ] **Step 6: Commit**

```bash
git add tools/shadow_worker content/tools/test_cursor_worker_protocol.py
git commit -m "feat(pgrep): add isolated Cursor model worker"
```

---

### Task 3: Host OCI sandbox adapter

**Files:**

- Create: `content/tools/cursor_sandbox.py`
- Test: `content/tools/test_cursor_sandbox.py`

**Interfaces:**

- Produces `SandboxConfig`, `detect_runtime()`, `build_image()`,
  `list_models()`, and `complete(request)`.
- Takes a command runner dependency so tests inspect commands without Docker.

- [ ] **Step 1: Write failing command-construction tests**

```python
def test_prompt_mounts_only_request_directory(tmp_path):
    runner = FakeRunner()
    sandbox = CursorSandbox(
        SandboxConfig(runtime="docker", image="pgrep-shadow-worker:test"),
        runner=runner,
        api_key="secret",
    )
    sandbox.complete(_request(), parent=tmp_path)
    command = runner.commands[-1]
    assert command[:3] == ["docker", "run", "--rm"]
    assert str(tmp_path.parent) not in " ".join(command)
    assert any(str(tmp_path) in arg and ":/work" in arg for arg in command)
    assert "secret" not in " ".join(command)


def test_missing_runtime_fails_before_request(tmp_path):
    with pytest.raises(RuntimeError, match="Docker"):
        detect_runtime(which=lambda _: None)
```

- [ ] **Step 2: Implement minimal adapter**

Use `subprocess.run()` with an explicit argument list, `check=False`, captured
output, and a timeout. Build each environment from scratch with only a verified
local `DOCKER_HOST=unix://...`; add `CURSOR_API_KEY` only after the per-request
mount proof succeeds. Pass the secret with `--env CURSOR_API_KEY`, never as an
argument value. Reject symlinks in the request directory.

- [ ] **Step 3: Test failure boundaries**

Add tests for:

- nonzero OCI exit;
- missing `result.json`;
- malformed result;
- model mismatch;
- timeout;
- request directory cleanup;
- private marker rejection before subprocess.

- [ ] **Step 4: Run tests**

```bash
out/pyenv/bin/pytest -q content/tools/test_cursor_sandbox.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add content/tools/cursor_sandbox.py content/tools/test_cursor_sandbox.py
git commit -m "feat(pgrep): sandbox Cursor model calls in OCI"
```

---

### Task 4: Portfolio allocation and cross-verification

**Files:**

- Create: `pylib/anki/pgrep/ai/shadow_portfolio.py`
- Test: `pylib/tests/test_pgrep_shadow_portfolio.py`

**Interfaces:**

- Produces `ModelRoles`, `allocate_families()`, `verification_families()`,
  `parse_candidate()`, and `run_candidate()`.
- Consumes `ModelBackend`, `generation_core.generate_problem`, and existing
  deterministic verification.

- [ ] **Step 1: Write allocation and origin-exclusion tests**

```python
def test_allocation_is_14_13_13_and_deterministic():
    first = shadow_portfolio.allocate_families(40, seed=7)
    second = shadow_portfolio.allocate_families(40, seed=7)
    assert first == second
    assert {family: first.count(family) for family in set(first)} == {
        "sol": 14,
        "opus": 13,
        "grok": 13,
    }


@pytest.mark.parametrize(
    ("origin", "judges"),
    [
        ("sol", ("opus", "grok")),
        ("opus", ("sol", "grok")),
        ("grok", ("sol", "opus")),
    ],
)
def test_origin_never_judges_its_candidate(origin, judges):
    assert shadow_portfolio.verification_families(origin) == judges
```

- [ ] **Step 2: Write strict parsing tests**

Cover exactly one JSON object, five strings, A-E key, known fields only,
finite difficulty/confidence, decomposition leak, and retry count.

- [ ] **Step 3: Implement portfolio types**

```python
@dataclass(frozen=True)
class ModelRoles:
    sol: ModelSpec
    opus: ModelSpec
    grok: ModelSpec

    def by_family(self, family: str) -> ModelSpec:
        return {"sol": self.sol, "opus": self.opus, "grok": self.grok}[family]


def verification_families(origin: str) -> tuple[str, str]:
    mapping = {
        "sol": ("opus", "grok"),
        "opus": ("sol", "grok"),
        "grok": ("sol", "opus"),
    }
    return mapping[origin]
```

`run_candidate()` must generate once through the origin backend, then ask the
two other backends to solve with independent choice permutations. It records
opinions but does not accept, reject, or emit preferences.

- [ ] **Step 4: Run focused tests**

```bash
PYTEST_ADDOPTS='-q pylib/tests/test_pgrep_shadow_portfolio.py pylib/tests/test_pgrep_consensus.py' just test-py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pylib/anki/pgrep/ai/shadow_portfolio.py pylib/tests/test_pgrep_shadow_portfolio.py
git commit -m "feat(pgrep): add origin-blind shadow portfolio"
```

---

### Task 5: Shadow-foundry CLI and atomic manifests

**Files:**

- Create: `content/tools/shadow_foundry.py`
- Create: `content/tools/test_shadow_foundry.py`
- Modify: `justfile`

**Interfaces:**

- CLI actions: `--self-check`, `--probe-models`, and real `--shadow`.
- Real mode requires `--sol-model`, `--opus-model`, and `--grok-model`.
- Publishes `manifest.json`, `candidates.json`, `failures.json`, and `_SUCCESS`
  under `content/run/shadow-foundry/<run-id>/`.

- [ ] **Step 1: Write failing self-check and publication tests**

```python
def test_shadow_run_is_atomic_and_has_no_training_artifacts(tmp_path):
    run_dir = shadow_foundry.publish_run(
        tmp_path,
        "run-1",
        candidates=[_candidate()],
        failures=[],
        manifest=_manifest(),
    )
    assert (run_dir / "_SUCCESS").exists()
    assert not (run_dir / "preferences.jsonl").exists()
    assert not (run_dir / "accepted.json").exists()


def test_partial_portfolio_never_publishes_success(tmp_path):
    with pytest.raises(RuntimeError, match="all three model families"):
        shadow_foundry.run_shadow(
            roles=_roles(),
            backend=MissingGrokBackend(),
            output_root=tmp_path,
        )
    assert not list(tmp_path.glob("*/_SUCCESS"))
```

- [ ] **Step 2: Implement host-side retrieval**

For each slot:

```python
chunks = retrieval.search(topic_query, k=generation_core.CONTEXT_CHUNKS)
request = build_request(
    chunks=chunks,
    model=role,
    prompt_version=generation_core.PROBLEM_PROMPT_VERSION,
)
```

Pass only `RetrievedChunk.text`, `chunk_id`, and `source_ref` into the sandbox
request. Fail if a source path or private marker appears.

- [ ] **Step 3: Implement model probe and exact role validation**

The probe writes a human-readable list and JSON. Real mode checks that all three
requested IDs appear and are distinct before retrieval or generation.

- [ ] **Step 4: Implement atomic publication**

Use the finalized-run pattern from `content/tools/foundry.py`: exclusive lock,
temporary sibling directory, strict JSON, `_SUCCESS`, atomic rename, and cleanup
on failure.

- [ ] **Step 5: Add recipes**

```just
# List account-available Cursor models without generating content.
[unix]
shadow-models *args:
    {{ ninja }} pyenv
    out/pyenv/bin/python content/tools/shadow_foundry.py --probe-models {{ args }}

# Offline fake-client smoke.
[unix]
shadow-smoke:
    {{ ninja }} pyenv
    out/pyenv/bin/python content/tools/shadow_foundry.py --self-check

# Quarantined multi-model generation. Never lands content or preference pairs.
[unix]
shadow-foundry *args:
    {{ ninja }} pyenv
    out/pyenv/bin/python content/tools/shadow_foundry.py --shadow {{ args }}
```

- [ ] **Step 6: Run focused tests and offline smoke**

```bash
out/pyenv/bin/pytest -q content/tools/test_cursor_sandbox.py content/tools/test_shadow_foundry.py
just shadow-smoke
PYTEST_ADDOPTS='--ignore=qt/tests/test_installer.py' just test-py
```

Expected: PASS, no network.

- [ ] **Step 7: Commit**

```bash
git add content/tools/shadow_foundry.py content/tools/test_shadow_foundry.py justfile
git commit -m "feat(pgrep): add quarantined multi-model shadow CLI"
```

---

### Task 6: Documentation, dependency gate, and account smoke

**Files:**

- Modify: `docs_pgrep/reference/content-pipeline.md`
- Modify: `docs_pgrep/plan/shadow-foundry-calibration-design.md` only if actual
  SDK behavior requires a documented correction.

- [ ] **Step 1: Document commands and artifact contract**

Document model probing, required exact IDs, OCI prerequisite, private output
paths, manifest fields, and the explicit absence of acceptance/landing/pairing.

- [ ] **Step 2: Run full offline verification**

```bash
just check
just shadow-smoke
```

Expected: PASS.

- [ ] **Step 3: Run the on-demand account probe**

```bash
just shadow-models
```

Expected: output includes one usable Sol, Opus, and Grok ID. If any family is
missing, stop. Do not substitute.

- [ ] **Step 4: Run one synthetic-context candidate per family**

Use a synthetic request fixture, not private corpus. Confirm each manifest names
the requested exact model and that the other two families cross-solved it.

- [ ] **Step 5: Commit docs**

```bash
git add docs_pgrep/reference/content-pipeline.md docs_pgrep/plan/shadow-foundry-calibration-design.md
git commit -m "docs(pgrep): document sandboxed shadow generation"
```

---

## Plan self-review

- Spec coverage: provider seam (Task 1), SDK probe/worker (Task 2), enforced OCI
  boundary (Task 3), model diversity and origin exclusion (Task 4), quarantined
  runner and manifests (Task 5), on-demand proof (Task 6).
- This plan does not build human sheets. That is the dependent
  `blind-calibration-ruler-plan.md`.
- No real corpus call occurs before all fake tests, full checks, model probe, and
  synthetic-context smoke pass.
- Fine-tuning, acceptance unlock, bundle landing, and preference emission remain
  out of scope.
