set windows-shell := ["pwsh", "-NoLogo", "-NoProfileLoadTime", "-Command"]

mod release

# Show available commands (in lifecycle order: develop -> review -> preview -> verify -> ship)
default:
    @just --list --unsorted

# Back-compat aliases for renamed recipes. Muscle-memory bridge; removed once the
# rename settles (after the serve-* / dev-* code phases land).
alias stage := preview
alias fresh := preview-fresh
alias run-optimized := preview-optimized
alias sync-review := review-sync
alias review-loop := review-sync
alias fmt := format
alias fix-fmt := format-fix
alias fix-lint := lint-fix
alias pgrep-ai-deps := ai-deps
alias sync-server := serve-sync

# ---------------------------------------------------------------------------
# develop
# ---------------------------------------------------------------------------

# Headless dev serve on :40000 (no window); browse /pgrep or /pgrep-lab. AI on (--ai off to disable)
[group('develop')]
[unix]
dev *args:
    #!/usr/bin/env bash
    set -euo pipefail
    set -- {{ args }}
    ai="on"
    passthrough=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --ai) ai="${2:-on}"; shift 2 || shift;;
            --ai=*) ai="${1#--ai=}"; shift;;
            --no-ai) ai="off"; shift;;
            *) passthrough+=("$1"); shift;;
        esac
    done
    # Headless: serve the web, never show the desktop window. Exclusive so the
    # profile chooser is suppressed and a profile auto-loads without a GUI.
    export PGREP_HEADLESS=1
    export PGREP_SURFACE_MODE="${PGREP_SURFACE_MODE:-exclusive}"
    if [ "$ai" = "on" ]; then
        if [ -f content/.env ]; then set -a; . ./content/.env; set +a; fi
        if [ -n "${OPENAI_API_KEY:-}" ]; then
            export PGREP_AI_MODEL="${PGREP_AI_MODEL:-gpt-5.5-2026-04-23}"
            echo ">>> dev: headless serve on :40000, AI on (model ${PGREP_AI_MODEL})."
        else
            echo ">>> dev: headless serve on :40000. AI off: no OPENAI_API_KEY (add it to content/.env, and run 'just ai-deps' once)."
        fi
    else
        echo ">>> dev: headless serve on :40000, AI off (--ai off)."
    fi
    echo ">>> Open http://127.0.0.1:40000 (or /pgrep-lab) in your browser. Edits reload automatically. Ctrl-C to stop."
    # Bundle the web watcher: it rebuilds on save and browser/phone tabs reload
    # by polling the build token. Headless-aware, so it skips its initial build
    # (dev's own build covers it) and never runs ninja at the same time as dev.
    watch_pid=""
    cleanup() { [ -n "${watch_pid}" ] && kill "${watch_pid}" 2>/dev/null || true; }
    trap cleanup EXIT INT TERM
    ./tools/web-watch &
    watch_pid=$!
    # Expand safely even when empty (macOS bash 3.2 + set -u).
    ./run ${passthrough[@]+"${passthrough[@]}"}

# Show the product window onto a running `dev` serve (starts `dev` if needed)
[group('develop')]
[unix]
dev-window:
    #!/usr/bin/env bash
    set -euo pipefail
    port="${ANKI_API_PORT:-40000}"
    url="http://127.0.0.1:${port}/_anki/pgrepDevShowWindow"
    show() { curl -sf "$url"; }
    if show >/dev/null; then
        echo ">>> Window shown (same serve as http://127.0.0.1:${port})."
        exit 0
    fi
    echo ">>> No headless serve on :${port}. Starting \`just dev\` in the background..."
    # Detach so closing this terminal does not kill the serve. Logs go to out/.
    mkdir -p out
    nohup just dev >>out/dev.log 2>&1 &
    disown || true
    for _ in $(seq 1 180); do
        if show >/dev/null 2>&1; then
            echo ">>> Window shown. Serve log: out/dev.log. Stop later with: kill \$(lsof -t -iTCP:${port} -sTCP:LISTEN)"
            exit 0
        fi
        sleep 1
    done
    echo ">>> Timed out waiting for :${port}. Check out/dev.log." >&2
    exit 1

# Expose the running `dev` serve to your phone over Tailscale (no LAN bind)
[group('develop')]
[unix]
serve-tail:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v tailscale >/dev/null 2>&1; then
        echo "Install Tailscale first (macOS app is best):" >&2
        echo "  brew install --cask tailscale-app" >&2
        echo "Then open Tailscale from Applications, sign in, and re-run \`just serve-tail\`." >&2
        exit 1
    fi
    # Prefer the default system socket; fall back to a userspace-networking socket
    # used when the brew formula runs without root / without the Mac app.
    ts=(tailscale)
    if ! tailscale status >/dev/null 2>&1; then
        sock="${TS_SOCKET:-$HOME/Library/Application Support/Tailscale/tailscaled.sock}"
        if [ -S "$sock" ] && tailscale --socket="$sock" status >/dev/null 2>&1; then
            ts=(tailscale --socket="$sock")
        else
            echo ">>> Tailscale CLI is installed but not logged in / not running." >&2
            echo ">>> Open the Tailscale app and sign in, or run:" >&2
            echo ">>>   brew install --cask tailscale-app   # needs your password once" >&2
            echo ">>>   open -a Tailscale" >&2
            exit 1
        fi
    fi
    if ! "${ts[@]}" status 2>/dev/null | head -1 | grep -qiE 'offers|active|idle|online|tagged|logged'; then
        # status prints a node table when connected; "Logged out." when not
        if "${ts[@]}" status 2>&1 | grep -qi 'logged out'; then
            echo ">>> Tailscale is running but logged out. Open the app (or \`tailscale login\`) and sign in." >&2
            exit 1
        fi
    fi
    port="${ANKI_API_PORT:-40000}"
    if ! curl -sf "http://127.0.0.1:${port}/" >/dev/null; then
        echo ">>> No serve on :${port}. Start \`just dev\` in another terminal first." >&2
        exit 1
    fi
    mkdir -p out
    # Clear any previous serve config so we own the HTTPS endpoint cleanly.
    "${ts[@]}" serve reset >/dev/null 2>&1 || true
    echo ">>> Starting Tailscale Serve for :${port}..."
    if "${ts[@]}" serve --help 2>&1 | grep -q -- '--bg'; then
        "${ts[@]}" serve --bg "${port}"
    else
        nohup "${ts[@]}" serve "${port}" >>out/serve-tail.log 2>&1 &
        disown || true
        sleep 1
    fi
    origin=""
    for _ in $(seq 1 20); do
        status="$("${ts[@]}" serve status 2>/dev/null || true)"
        origin="$(printf '%s\n' "$status" | sed -nE 's#.*(https://[a-zA-Z0-9.-]+\.ts\.net).*#\1#p' | head -1)"
        if [ -n "$origin" ]; then
            break
        fi
        sleep 0.5
    done
    if [ -z "$origin" ]; then
        echo ">>> Tailscale Serve started but no *.ts.net URL found yet." >&2
        echo ">>> Run \`tailscale serve status\` and set PGREP_DEV_ALLOWED_ORIGIN to the https URL," >&2
        echo ">>> or write that URL into out/dev-allowed-origin." >&2
        exit 1
    fi
    printf '%s\n' "$origin" > out/dev-allowed-origin
    echo ">>> Phone preview: ${origin}"
    echo ">>> Origin allowlisted in out/dev-allowed-origin (dev-only; full API stays locked)."
    echo ">>> Open that URL on a phone on the same tailnet. When finished: \`tailscale serve reset\`."

# Self-hosted sync server for testing sync + demo data, port 8090
[group('develop')]
serve-sync user="pgrep:pgrep":
    {{ ninja }} pylib
    SYNC_USER1={{ user }} SYNC_PORT="${SYNC_PORT:-8090}" out/pyenv/bin/python tools/sync-server.py

# Rebuild and reload the web stack once, without restarting
[group('develop')]
rebuild-web:
    ./tools/rebuild-web

# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------

# Multi-branch review dashboard (http://127.0.0.1:40100): start/stop each worktree
[group('review')]
[unix]
review:
    ./tools/pgrep-review

# Merge mergeable branches into a combined `review` branch, looping on an interval
[group('review')]
[unix]
review-sync *branches:
    #!/usr/bin/env bash
    # PGREP_REVIEW_INTERVAL seconds between merges (default 600). Runs once now,
    # then loops; Ctrl-C to stop. Conflicting branches are skipped and reported.
    interval="${PGREP_REVIEW_INTERVAL:-600}"
    while true; do
        ./tools/pgrep-sync-review {{ branches }} || true
        echo "next sync in ${interval}s (Ctrl-C to stop)"
        sleep "$interval"
    done

# ---------------------------------------------------------------------------
# preview (faithful product: exclusive surface, dev mode OFF)
# ---------------------------------------------------------------------------

# Preview the product as users get it: exclusive surface, dev off, your profile
[group('preview')]
[unix]
preview *args:
    ANKIDEV= PGREP_SURFACE_MODE=exclusive {{ run_script }} {{ args }}

# Preview the product on a brand-new-user throwaway profile (set PGREP_FRESH_BASE)
[group('preview')]
[unix]
preview-fresh *args:
    ANKIDEV= ANKI_BASE="${PGREP_FRESH_BASE:-/tmp/pgrep-newuser}" PGREP_SURFACE_MODE=exclusive {{ run_script }} {{ args }}

# Preview the product release-compiled, to feel true performance
[group('preview')]
[unix]
preview-optimized *args:
    ANKIDEV= PGREP_SURFACE_MODE=exclusive RELEASE=1 {{ run_script }} {{ args }}

# ---------------------------------------------------------------------------
# verify (gates)
# ---------------------------------------------------------------------------

# Pre-ship gate: check (build + lint + unit) then the e2e suite
[group('verify')]
verify:
    just check
    just test-e2e

# Build + lint + unit tests (the fast gate)
[group('verify')]
check:
    {{ ninja }} pylib qt check

# Fastest sanity check: import smoke + Rust tests
[group('verify')]
smoke:
    {{ if os() == "windows" { "$env:SKIP_RUN='1'; " + run_script } else { "SKIP_RUN=1 " + run_script } }}
    just test-rust

# ---------------------------------------------------------------------------
# ship
# ---------------------------------------------------------------------------

# Build the real installer artifact (.dmg / .msi / .tar.zst); run `verify` first
[group('ship')]
ship:
    ./tools/build-installer

# ---------------------------------------------------------------------------
# quality (tests, lint, format, perf)
# ---------------------------------------------------------------------------

# Run all tests (Rust, Python, TypeScript). Pass --coverage and/or --html.
[group('quality')]
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test coverage='' html='':
    just {{ if coverage == "--coverage" { "coverage " + html } else { "_test" } }}

# Run Rust tests. Pass --coverage and/or --html.
[group('quality')]
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-rust coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-rust " + html } else { "_test-rust" } }}

# Run Python tests (pylib + qt). Pass --coverage and/or --html.
[group('quality')]
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-py coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-py " + html } else { "_test-py" } }}

# Run TypeScript/Svelte Vitest tests. Pass --coverage and/or --html.
[group('quality')]
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-ts coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-ts " + html } else { "_test-ts" } }}

# Run Playwright end-to-end tests. Pass --ui for the interactive UI.
[group('quality')]
[arg("ui", long="ui", value="--ui")]
test-e2e ui='': _install-playwright-browsers
    {{ ninja }} pyenv ts:generated pylib qt
    {{ playwright_env }} {{ yarn }} test:e2e {{ ui }}

# Run linting and type checking (requires build outputs)
[group('quality')]
lint:
    {{ ninja }} \
        check:clippy \
        check:mypy \
        check:ruff \
        check:eslint \
        check:svelte \
        check:typescript

# Auto-fix lint issues (ruff + eslint)
[group('quality')]
lint-fix:
    {{ ninja }} fix:ruff fix:eslint

# Check formatting (fast, no build needed)
[group('quality')]
format:
    {{ ninja }} check:format

# Apply formatting
[group('quality')]
format-fix:
    {{ ninja }} format

# Run coverage across all stacks. Pass --html for reports.
[group('quality')]
[arg("html", long="html", value="--html")]
coverage html='':
    just _coverage-rust {{ html }}
    just _coverage-py {{ html }}
    just _coverage-ts {{ html }}

# Benchmark engine latency (p50/p95/worst). Example: just bench --cards 50000
[group('quality')]
[unix]
bench *args:
    {{ ninja }} pylib
    out/pyenv/bin/python tools/pgrep_bench.py {{ args }}

# Crash/corruption test: mid-review SIGKILLs, then reopen + integrity check
[group('quality')]
[unix]
crash-test *args:
    {{ ninja }} pylib
    out/pyenv/bin/python tools/pgrep_crash_test.py {{ args }}

# ---------------------------------------------------------------------------
# content (AI + bundle tooling)
# ---------------------------------------------------------------------------

# Install optional AI runtime deps (needed only when AI is toggled on)
[group('content')]
ai-deps:
    {{ ninja }} pyenv
    {{ uv }} pip install --python out/pyenv/bin/python fastembed openai sympy sqlite-vec numpy

# Batch-generate gated decomposition tutor data into the bundle (needs content/ + key)
[group('content')]
[unix]
gen-decompositions *args:
    #!/usr/bin/env bash
    set -euo pipefail
    {{ ninja }} pyenv
    if [ -f content/.env ]; then set -a; . ./content/.env; set +a; fi
    if [ -z "${OPENAI_API_KEY:-}" ]; then
        echo "Set OPENAI_API_KEY (export it or add it to content/.env) to generate." >&2
        exit 1
    fi
    out/pyenv/bin/python content/tools/generate_decompositions.py {{ args }}

# Run the five AI content audits over the shipped bundle (pre-release scan)
[group('content')]
[unix]
audit-bundle-ai *args:
    #!/usr/bin/env bash
    set -euo pipefail
    {{ ninja }} pyenv
    if [ -f content/.env ]; then set -a; . ./content/.env; set +a; fi
    out/pyenv/bin/python content/tools/audit_bundle_ai.py {{ args }}

# Offline foundry smoke (no network): runs foundry.py --self-check. macOS/Linux.
[group('content')]
[unix]
foundry-dry *args:
    {{ ninja }} pyenv
    out/pyenv/bin/python content/tools/foundry.py --self-check {{ args }}

# Best-of-N content foundry. Example: `just foundry --dry-run --topic classical_mechanics --n 8`
[group('content')]
[unix]
foundry *args:
    #!/usr/bin/env bash
    set -euo pipefail
    {{ ninja }} pyenv
    if [ -f content/.env ]; then set -a; . ./content/.env; set +a; fi
    out/pyenv/bin/python content/tools/foundry.py {{ args }}

# Standing verifier evaluation over precomputed labels, entirely offline
[group('content')]
[unix]
eval-verifier *args:
    {{ ninja }} pyenv
    out/pyenv/bin/python content/tools/eval_verifier.py {{ args }}

# Reproduce the AI-eval methodology on a committed synthetic sample, offline
[group('content')]
[unix]
eval-public *args:
    {{ ninja }} pyenv
    out/pyenv/bin/python -c "import numpy" 2>/dev/null || {{ uv }} pip install --python out/pyenv/bin/python numpy
    out/pyenv/bin/python tools/pgrep_eval_public.py {{ args }}

# ---------------------------------------------------------------------------
# ios
# ---------------------------------------------------------------------------

# Build the iOS FFI xcframework (out/ios/AnkiFfi.xcframework); macOS-only
[group('ios')]
ios-xcframework:
    ./tools/build-xcframework.sh

# Bundle the 3D manifold webview asset for iOS Home; macOS-only
[group('ios')]
ios-manifold:
    ./tools/build-manifold-webview.sh

# Vendor the offline MathJax webview asset for iOS; macOS-only
[group('ios')]
ios-mathjax:
    ./tools/build-mathjax-webview.sh

# Build xcframework, regenerate the Xcode project, run the Simulator XCTest; macOS-only
[group('ios')]
ios-smoke:
    ./tools/ios-smoke.sh

# Build + launch the pgrep iOS app in the Simulator; macOS-only
[group('ios')]
ios-run:
    ./tools/ios-run.sh

# Prove the iOS FFI sync path end to end (phone -> server -> desktop); macOS-only
[group('ios')]
ios-sync-proof:
    ./tools/ios-sync-proof.sh

# ---------------------------------------------------------------------------
# build / misc
# ---------------------------------------------------------------------------

# Build the project (pylib + qt)
[group('build')]
build:
    {{ ninja }} pylib qt

# Sync translation files
[group('build')]
ftl-sync:
    {{ ninja }} ftl-sync

# Dispatch the CI workflow on a branch or tag
[group('build')]
ci branch:
    gh workflow run ci.yml --ref {{ branch }}

# Remove build outputs from out/ (pass keep-env to keep node_modules/pyenv)
[group('build')]
clean *args:
    ./tools/clean {{ args }}

# ---------------------------------------------------------------------------
# private plumbing (hidden from `just --list`)
# ---------------------------------------------------------------------------

# Plumbing: run one worktree as a numbered instance on offset ports (used by review).
# Bound to 127.0.0.1 (no ANKI_API_HOST=0.0.0.0), headless so no window pop-ups.
[private]
[unix]
_review-instance n *args:
    ANKI_SINGLE_INSTANCE_KEY="pgrep-inst-{{ n }}" PGREP_HEADLESS=1 PGREP_SURFACE_MODE="${PGREP_SURFACE_MODE:-exclusive}" ANKI_API_PORT="$((40000 + {{ n }}))" QTWEBENGINE_REMOTE_DEBUGGING="$((8080 + {{ n }}))" ANKI_BASE="${TMPDIR:-/tmp}/pgrep-inst-{{ n }}" {{ run_script }} {{ args }}

# Watch web sources and rebuild/reload on change (bundled into `dev`; kept for rare manual use)
[private]
web-watch:
    ./tools/web-watch

# Build wheels (needed for some platforms)
[private]
wheels:
    {{ ninja }} wheels

# Run minilints (copyright, contributors, licenses)
[private]
minilints:
    {{ ninja }} check:minilints

# Fix minilints (update licenses.json)
[private]
fix-minilints:
    {{ ninja }} fix:minilints

# Deprecate translation strings
[private]
ftl-deprecate:
    {{ ninja }} ftl-deprecate

# Run Complexipy in regression-only mode
[private]
complexipy-diff:
    {{ ninja }} check:complexipy-diff

# Build the Anki dev documentation site (upstream tooling, not the pgrep docs)
[private]
docs:
    {{ uv }} run --group docs sphinx-build -b html docs out/docs/html
    @echo "Docs built at out/docs/html/index.html"

# Build and serve the Anki dev documentation site (upstream tooling)
[private]
docs-serve:
    {{ uv }} run --group docs sphinx-autobuild docs out/docs/html --host 127.0.0.1 --port 8000

# Build Rust API docs (upstream tooling)
[private]
docs-rust:
    cargo doc --open

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

# Helpers to get the right commands for the platform

ninja := if os() == "windows" { "tools\\ninja" } else { "./ninja" }
run_script := if os() == "windows" { ".\\run.bat" } else { "./run" }
playwright_env := if os() == "windows" { "set PLAYWRIGHT_BROWSERS_PATH=out\\playwright-browsers&&" } else { "PLAYWRIGHT_BROWSERS_PATH=out/playwright-browsers" }
yarn := if os() == "windows" { "out\\extracted\\node\\yarn.cmd" } else { "out/extracted/node/bin/yarn" }
uv := env("UV_BINARY", if os() == "windows" { "out\\extracted\\uv\\uv" } else { "out/extracted/uv/uv" })
export UV_PROJECT_ENVIRONMENT := if os() == "windows" { "out\\pyenv" } else { "out/pyenv" }
