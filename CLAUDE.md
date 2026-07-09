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

Once a string is defined (for example `addons-you-have-count` in
`addons.ftl`), the generated API exposes it in each language:

- Python: `from aqt.utils import tr; msg = tr.addons_you_have_count(count=3)`
- TypeScript: `import * as tr from "@generated/ftl"; tr.addonsYouHaveCount({count: 3})`
- Rust: `collection.tr.addons_you_have_count(3)`

In Qt `.ui` files, a widget whose text is marked translatable and matches an
ftl key (for example a `QLabel` titled `addons_you_have_count`) automatically
uses the registered translation.

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

## Writing style

Aim for clear, sophisticated communication.

- Do not use em dashes. Rewrite the sentence, or use a comma, parentheses, or a period.
- Use colons and semicolons sparingly. Prefer separate sentences. A colon may introduce a genuine list.

Applies to everything you write, including docs, commit messages, PR text, code comments, and chat replies.

## Worktrees

Isolate feature and bugfix work in its own worktree and branch rather than working on `main` directly. `main` is the only integration branch and stays clean, so the primary checkout is always usable.

- Each piece of work gets its own branch off the latest `main`, checked out as a worktree. Name the branch for its single concern (for example `feat/attempt-log`).
- One concern per branch. Keep branches small and short lived.
- Do quick edits, questions, doc-only changes, and exploration in the primary checkout, not a worktree.
- Merge `main` in periodically so a branch does not drift. Finish by merging into `main` (a PR, or a fast-forward for solo work), then remove the worktree and delete the branch.
- Each tool manages worktrees its own way (Claude Code has native worktree tooling; otherwise create them manually with `git worktree`). Whatever the mechanism, keep the worktree directory out of version control.

## Documentation organization

Applies to documentation files (Markdown and related), not source code.

Placement:

- Put docs under the project's docs home (`docs_pgrep/`).
- Group by purpose: `plan/` (work not yet done), `reference/` (how things are
  or work), `design/` (design decisions), `working/` (loose scratch and
  transient coordination docs).

Naming:

- kebab-case for files and folders.
- No date prefixes. No phase or layer names in filenames (`l1`, `L2`, `l5.9`,
  `l6`); name a doc for its content. No numeric order prefix (`01-`) unless a
  folder is genuinely a reading sequence, and only when the user asks.

Creating a new doc:

- Prefer extending an existing doc over creating a new file; create one only
  when the topic is genuinely distinct. Name it for its content and link it
  from its parent or category index.
- Never invent a new top-level folder or drop a file at the repo root or docs
  root on a whim. If the right home is unclear, stop and ask.
- Transient coordination docs (handoffs, punchlists, orchestrators) usually
  should not become durable files; if needed they go in `working/` and are
  cleaned once the work lands.

Moving or renaming:

- Use `git mv` to preserve history. Find and update every inbound reference
  across the whole repo (code, tests, config, not just docs), recompute
  relative links in the moved file, and verify no broken links remain.

For bulk reorganization or an alignment audit, use the `organize-files` and
`audit-files` skills.

## Individual preferences

See @.claude/user.md
