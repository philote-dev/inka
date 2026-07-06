set windows-shell := ["pwsh", "-NoLogo", "-NoProfileLoadTime", "-Command"]

mod release

# Show available commands
default:
    @just --list

# Build the project
build:
    {{ ninja }} pylib qt

# Build and run Anki in development mode
run *args:
    {{ run_script }} {{ args }}

# Build and run Anki in optimized (release) mode
run-optimized *args:
    {{ if os() == "windows" { "$env:RELEASE='1'; .\\run.bat" } else { "RELEASE=1 ./run" } }} {{ args }}

# Run a self-hosted Anki sync server for pgrep (reuses Anki's sync unmodified). macOS/Linux.
# Defaults to port 8090 (8080 is taken by `just run`'s Qt remote-debug/hot-reload
# server). Auth via the user arg (SYNC_USER1); SYNC_HOST/SYNC_PORT/SYNC_BASE via env.
sync-server user="pgrep:pgrep":
    {{ ninja }} pylib
    SYNC_USER1={{ user }} SYNC_PORT="${SYNC_PORT:-8090}" out/pyenv/bin/python tools/sync-server.py

# Watch web sources and rebuild/reload Anki's web stack on change (macOS/Linux)
web-watch:
    ./tools/web-watch

# Rebuild and reload Anki's web stack without restarting (macOS/Linux)
rebuild-web:
    ./tools/rebuild-web

# Build wheels (needed for some platforms)
wheels:
    {{ ninja }} wheels

# Build and run all checks (lint + test) - lets ninja handle dependencies
check:
    {{ ninja }} pylib qt check

# Run all tests (Rust, Python, TypeScript). Pass --coverage to enforce coverage, and --html to include HTML reports.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test coverage='' html='':
    just {{ if coverage == "--coverage" { "coverage " + html } else { "_test" } }}

# Run coverage for all test stacks. Pass --html to also generate HTML reports.
[arg("html", long="html", value="--html")]
coverage html='':
    just _coverage-rust {{ html }}
    just _coverage-py {{ html }}
    just _coverage-ts {{ html }}

# Run Rust tests. Pass --coverage to enforce Rust coverage, and --html to include an HTML report.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-rust coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-rust " + html } else { "_test-rust" } }}

# Run Python tests (pylib + qt). Pass --coverage to enforce coverage, and --html to include HTML reports.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-py coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-py " + html } else { "_test-py" } }}

# Run TypeScript/Svelte Vitest tests. Pass --coverage to enforce coverage, and --html to include an HTML report.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-ts coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-ts " + html } else { "_test-ts" } }}

# Run Playwright end-to-end tests. Pass --ui to open the interactive UI.
[arg("ui", long="ui", value="--ui")]
test-e2e ui='': _install-playwright-browsers
    {{ ninja }} pyenv ts:generated pylib qt
    {{ playwright_env }} {{ yarn }} test:e2e {{ ui }}

# Fast desktop sanity check: import smoke (libs importable) + Rust tests
smoke:
    {{ if os() == "windows" { "$env:SKIP_RUN='1'; " + run_script } else { "SKIP_RUN=1 " + run_script } }}
    just test-rust

# Build the iOS FFI xcframework (out/ios/AnkiFfi.xcframework); macOS-only
ios-xcframework:
    ./tools/build-xcframework.sh

# Bundle the 3D knowledge manifold (Three.js + shared renderer) for the native
# Home's WKWebView, committed as an app resource. Re-run on manifold/three changes.
ios-manifold:
    ./tools/build-manifold-webview.sh

# Build xcframework, regenerate the Xcode project, and run the iOS Simulator XCTest; macOS-only
ios-smoke:
    ./tools/ios-smoke.sh

# Build + launch the pgrep iOS app in the Simulator (visible review UI); macOS-only
ios-run:
    ./tools/ios-run.sh

# Prove the iOS FFI sync path end to end (phone -> server -> desktop); macOS-only
ios-sync-proof:
    ./tools/ios-sync-proof.sh

# Prime + verify the shared demo account on a running sync server (real content +
# made-up stats + settings), then sync it down on desktop and iOS. Needs a server
# from `just sync-server` first. macOS/Linux. See docs_pgrep/reference/dev-harness.md.
pgrep-demo-sync:
    ./tools/pgrep-demo-sync.sh

# Install the optional AI runtime deps into out/pyenv so live generation and the
# tutor work when AI is toggled on. Not part of the default build; the app scores
# and studies with AI off and these absent. macOS/Linux.
pgrep-ai-deps:
    {{ ninja }} pyenv
    {{ uv }} pip install --python out/pyenv/bin/python fastembed openai sympy sqlite-vec numpy

# Build + run with the AI key loaded from the environment (or content/.env if
# present), so the in-app AI toggle can grade the ladder and generate live. Run
# `just pgrep-ai-deps` once first. macOS/Linux.
[unix]
run-ai *args:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f content/.env ]; then set -a; . ./content/.env; set +a; fi
    if [ -z "${OPENAI_API_KEY:-}" ]; then
        echo "Set OPENAI_API_KEY (export it or add it to content/.env) to run with AI." >&2
        exit 1
    fi
    # Pin a known-good dated chat snapshot. Without this the auto-picker can land
    # on a non-chat gpt-5 model on some accounts. Override with PGREP_AI_MODEL.
    export PGREP_AI_MODEL="${PGREP_AI_MODEL:-gpt-5.5-2026-04-23}"
    echo ">>> Launching pgrep with AI available (model ${PGREP_AI_MODEL}). Toggle it on in Settings."
    ./run {{ args }}

# Reproduce the AI-eval methodology on a committed synthetic sample, offline, with no
# API key and no private content/ tree, so anyone cloning the public repo gets the same
# result. Mirrors the gold-set gate: headline metrics with bootstrap CIs, a keyword
# (BM25) and an embedding-free (TF-IDF) baseline, the beat-baseline rule, and the
# leakage firewall. Exits non-zero on contamination. macOS/Linux.
[unix]
eval-public *args:
    {{ ninja }} pyenv
    out/pyenv/bin/python -c "import numpy" 2>/dev/null || {{ uv }} pip install --python out/pyenv/bin/python numpy
    out/pyenv/bin/python tools/pgrep_eval_public.py {{ args }}

# Benchmark pgrep engine latency (spec 7h/10): p50/p95/worst for next-card, answer, the
# three scores, coverage, and the dashboard, on up to 50k cards. macOS/Linux.
# Example: `just bench --cards 50000`.
[unix]
bench *args:
    {{ ninja }} pylib
    out/pyenv/bin/python tools/pgrep_bench.py {{ args }}

# Crash/corruption test (spec 7g): 20 mid-review SIGKILLs, reopen + integrity check,
# assert zero corruption and no lost committed reviews. macOS/Linux.
[unix]
crash-test *args:
    {{ ninja }} pylib
    out/pyenv/bin/python tools/pgrep_crash_test.py {{ args }}

[private]
_test:
    {{ ninja }} check:rust_test check:pytest check:vitest

[private]
_test-rust:
    {{ ninja }} check:rust_test

[private]
_test-py:
    {{ ninja }} check:pytest

[private]
_test-ts:
    {{ ninja }} check:vitest

[private]
_coverage-rust html='':
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-rust" } else { "tools/coverage/coverage-rust" } }} {{ html }}

[private]
_coverage-py html='':
    {{ ninja }} pylib qt
    just _coverage-py-pylib {{ html }}
    just _coverage-py-qt {{ html }}

[private]
_coverage-py-pylib html='':
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-py" } else { "tools/coverage/coverage-py" } }} pylib {{ html }}

[private]
_coverage-py-qt html='':
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-py" } else { "tools/coverage/coverage-py" } }} qt {{ html }}

[private]
_coverage-ts html='':
    {{ ninja }} node_modules ts:generated
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-ts" } else { "tools/coverage/coverage-ts" } }} {{ html }}

[private]
_install-playwright-browsers:
    {{ ninja }} node_modules
    {{ playwright_env }} {{ yarn }} playwright install chromium

# Check formatting (fast, no build needed)
fmt:
    {{ ninja }} check:format

# Fix formatting
fix-fmt:
    {{ ninja }} format

# Run linting and type checking (requires build outputs)
lint:
    {{ ninja }} \
        check:clippy \
        check:mypy \
        check:ruff \
        check:eslint \
        check:svelte \
        check:typescript

# Fix auto-fixable lint issues (ruff + eslint)
fix-lint:
    {{ ninja }} fix:ruff fix:eslint

# Run minilints (copyright, contributors, licenses)
minilints:
    {{ ninja }} check:minilints

# Fix minilints (update licenses.json)
fix-minilints:
    {{ ninja }} fix:minilints

# Sync translation files
ftl-sync:
    {{ ninja }} ftl-sync

# Deprecate translation strings
ftl-deprecate:
    {{ ninja }} ftl-deprecate

# Build documentation site
docs:
    {{ uv }} run --group docs sphinx-build -b html docs out/docs/html
    @echo "Docs built at out/docs/html/index.html"

# Build and serve documentation site
docs-serve:
    {{ uv }} run --group docs sphinx-autobuild docs out/docs/html --host 127.0.0.1 --port 8000

# Build Rust API docs
docs-rust:
    cargo doc --open

# Dispatch CI workflow on a given branch or tag
ci branch:
    gh workflow run ci.yml --ref {{ branch }}

# Run Complexipy in regression-only mode
complexipy-diff:
    {{ ninja }} check:complexipy-diff

# Remove build outputs from out/ (pass keep-env to keep node_modules/pyenv); macOS/Linux
clean *args:
    ./tools/clean {{ args }}

# Helpers to get the right commands for the platform

ninja := if os() == "windows" { "tools\\ninja" } else { "./ninja" }
run_script := if os() == "windows" { ".\\run.bat" } else { "./run" }
playwright_env := if os() == "windows" { "set PLAYWRIGHT_BROWSERS_PATH=out\\playwright-browsers&&" } else { "PLAYWRIGHT_BROWSERS_PATH=out/playwright-browsers" }
yarn := if os() == "windows" { "out\\extracted\\node\\yarn.cmd" } else { "out/extracted/node/bin/yarn" }
uv := env("UV_BINARY", if os() == "windows" { "out\\extracted\\uv\\uv" } else { "out/extracted/uv/uv" })
export UV_PROJECT_ENVIRONMENT := if os() == "windows" { "out\\pyenv" } else { "out/pyenv" }
