# Claude Code Configuration

> **Note:** Every command you need — building, running, testing, linting,
> formatting — is defined as a recipe in the project `justfile`. Run
> `just --list` to see them. Do not invoke `./ninja`, `./run`, or scripts
> under `./tools` directly — use the `just` recipes instead.

## Project Overview

Anki is a spaced repetition flashcard program with a multi-layered architecture. Main components:

- Web frontend: Svelte/TypeScript in ts/
- PyQt GUI, which embeds the web components in aqt/
- Python library which wraps our rust Layer (pylib/, with Rust module in pylib/rsbridge)
- Core Rust layer in rslib/
- Protobuf definitions in proto/ that are used by the different layers to
  talk to each other.

## Running Anki

To build and run Anki in development mode:

```
just run
```

This builds pylib and qt, then launches Anki with debugging enabled. Web
views are served at http://localhost:40000/_anki/pages/ (e.g.,
deckconfig.html). Use `just run-optimized` for a release-optimized build.
For live-reloading during web development, run `just web-watch` in a
separate terminal — it monitors ts/, sass/, and qt/aqt/data/web/ and
auto-rebuilds on changes (`just rebuild-web` triggers a one-off rebuild).

## Building/checking

`just check` will format the code and run the main build & checks.
Please do this as a final step before marking a task as completed.

Run `just` (or `just --list`) to see all available commands.

## Quick iteration

During development, you can build/check subsections of our code:

- Rust: `cargo check`
- Python: `just lint` (runs mypy/ruff), and if wheel-related, `just wheels`
- TypeScript/Svelte: `just lint` (includes check:svelte and check:typescript)

Language-specific tests are also available: `just test-rust`, `just test-py`,
`just test-ts`. Use `just fmt` / `just fix-fmt` for formatting and
`just fix-lint` to auto-fix lint issues.

TypeScript/Svelte browser e2e tests live in `ts/tests/e2e/` and run with
`just test-e2e`. The harness launches a temporary Anki instance and drives
mediasrv pages with Playwright's Chromium.

Be mindful that some changes (such as modifications to .proto files) may
need a full build with `just check` first.

## Build tooling

`just` recipes wrap our build system (implemented in build/), which takes
care of downloading required deps and invoking our build steps. See the
project `justfile` for the full set of recipes.

## Translations

ftl/ contains our Fluent translation files. We have scripts in rslib/i18n
to auto-generate an API for Rust, TypeScript and Python so that our code can
access the translations in a type-safe manner. Changes should be made to
ftl/core or ftl/qt. Except for features specific to our Qt interface, prefer
the core module. When adding new strings, confirm the appropriate ftl file
first, and try to match the existing style.

## Protobuf and IPC

Our build scripts use the .proto files to define our Rust library's
non-Rust API. pylib/rsbridge exposes that API, and \_backend.py exposes
snake_case methods for each protobuf RPC that call into the API.
Similar tooling creates a @generated/backend TypeScript module for
communicating with the Rust backend (which happens over POST requests).

## Fixing errors

When dealing with build errors or failing tests, invoke 'check' or one
of the quick iteration commands regularly. This helps verify your changes
are correct. To locate other instances of a problem, run the check again -
don't attempt to grep the codebase.

## Ignores

The files in out/ are auto-generated. Mostly you should ignore that folder,
though you may sometimes find it useful to view out/{pylib/anki,qt/\_aqt,ts/lib/generated} when dealing with cross-language communication or our other generated sourcecode.

## Installer

The code for our Briefcase-based installer is in qt/installer, with
separate templates for each platform (mac-template/, linux-template/,
windows-template/).

## Rust dependencies

Prefer adding to the root workspace, and using dep.workspace = true in the individual Rust project.

## Rust utilities

rslib/{process,io} contain some helpers for file and process operations,
which provide better error messages/context and some ergonomics. Use them
when possible.

## Rust error handling

in rslib, use error/mod.rs's AnkiError/Result and snafu. In our other Rust modules, prefer anyhow + additional context where appropriate. Unwrapping
in build scripts/tests is fine.

## Individual preferences

See @.claude/user.md

## Cursor Cloud specific instructions

This repo builds and runs on the cloud Linux VM. Toolchains (Rust, `n2`, `just`,
system libs) are installed in the VM snapshot, and the startup update script runs
`./ninja node_modules pyenv` to refresh the JS and Python dependencies. The build
system downloads node, yarn, protoc and (when `UV_BINARY` is unset) `uv` itself
into `out/`, so the standard recipes work directly. Build/lint/test/run use the
normal `just` recipes documented above (`just build`, `just lint`, `just test`,
`just check`, `just run`).

Non-obvious caveats:

- Leave `UV_BINARY` unset. The build then downloads its own pinned `uv` into
  `out/extracted/uv`; hardcoding a different `uv` path just causes `pyenv` to be
  rebuilt unnecessarily.
- The desktop app is a PyQt6 GUI. It needs an X display (the cloud VM exposes
  `DISPLAY=:1`); drive and screenshot it through the desktop / computer-use, not
  headless. Launch it with `just run` (or `just fresh` for a throwaway first-run
  profile) and expect roughly 15-20s before the window appears.
- First launch shows a one-time language dialog, then a "Let's place your topics"
  diagnostic. Completing the diagnostic (answer the multiple-choice questions,
  then "See placement") is the quickest way to exercise the core study + scoring
  path end to end.
- Set `ANKI_BASE` to a throwaway dir (for example `ANKI_BASE=/tmp/pgrep-demo`) to
  get a clean profile; a profile left corrupt by a killed run makes the next
  start fail in `profiles.py` until the base dir is cleared.
- If the app aborts during `QApplication.__init__` (SIGABRT with no traceback),
  the Qt `xcb` platform plugin is missing libraries beyond the `setup-anki`
  action's list. Install `libxcb-cursor0 libxcb-icccm4 libxcb-image0
  libxcb-keysyms1 libxcb-render-util0` (see `docs/linux.md`, "Missing Libraries").
  These are already present in the VM snapshot.
- The embedded mediasrv (port 40000) and Qt remote-debug server (port 8080) bind
  to `127.0.0.1` only, and only after the window is up. They are not required for
  GUI testing.
