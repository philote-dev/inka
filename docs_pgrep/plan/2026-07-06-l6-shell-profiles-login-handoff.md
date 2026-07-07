# Handoff: L6 structural de-Anki (shell, profiles, login) + production roadmap

Date: 2026-07-06. Status: handoff for the L6 production chat. Author: pair session (sibling chat).

Feed this to the L6 production / de-Anki chat. It continues that chat's mission. It does
not repeat the branding work that chat already finished.

## What is already done (do not redo)

The branding sweep (Workstreams 1 to 4 of `2026-07-06-l6-production-de-anki-design.md`) is
complete and parked, uncommitted, in the worktree `.worktrees/l6-de-anki` (branch
`feat/l6-de-anki`):

- About dialog rebuilt as pgrep with a single "Built on Anki" AGPL credit, plus an About
  row in pgrep Settings.
- Sync strings rebranded to pgrep and "your sync server" (Scheme C).
- Qt chrome (dialog and progress titles, crash modal, debug header, profile and downgrade
  messages) flipped from Anki to pgrep.
- Startup strings (`profiles.ftl`, `qt-misc.ftl`) rebranded.
- The on-launch update check to `apps.ankiweb.net` disabled.
- `build-plan.md` L6 corrected. Guard tests added. `just check` green (except the known
  pre-existing `test_installer` worktree flake).

Deferred by that chat to packaging (L6.2b), keep deferred: the macOS app-menu name
(`setApplicationName` / bundle `CFBundleName`, which is why dev still shows "python"), the
`help.ankiweb.net` and `apps.ankiweb.net` URLs, and the `Documents/Anki` data folder.

## The mission for this handoff

Remove Anki's **interface** from the product, keep Anki's **engine** as an invisible,
upstream-mergeable dependency. This is the structural half the branding spec deliberately
left out: menus, profiles, and login. Plus a costed production roadmap.

Guiding line, straight from the vision (`docs_pgrep/research/vision-and-structure.md`):
"reuse the engine, not the interface"; `aqt/` is a thin host with its screens replaced by
pgrep UI. The product is single-user (a post-undergraduate physics student, no cohort, no
instructors), offline-first, desktop plus phone, synced. pgrep is all a user ever sees.

## Grounding facts (verified in the repo)

- Surface modes: `qt/aqt/pgrep_host.py`. `_DEFAULT_MODE = "exclusive"` (the product).
  `hosted` keeps Anki reachable (dev hatch), `off` is stock Anki. `apply_menu_chrome`
  currently only **hides** Anki's menus in exclusive; `surface_mode` also reads a
  `PGREP_SURFACE_MODE` env override then the global meta `pgrep_surface_mode`.
- Menus: `qt/aqt/main.py` `setupMenus()` (around line 1458) builds File, Edit, View, Tools,
  Help from the shared `main.ui` form and appends the pgrep items. `_setup_pgrep_menus()`
  (around 1540) adds pgrep's own Go menu (Home/Study/Progress/Library, Cmd+1..4) and
  Settings (Cmd+,) in exclusive mode. The dev-lab menu item is gated by `dev_mode`
  (`ANKIDEV`), which `./run` sets.
- Profiles: three layers, base folder then profile then collection (`qt/aqt/profiles.py`).
  `setupProfile()` (around `main.py:302`) auto-opens when exactly one profile exists, else
  shows the chooser. `showProfileManager()` is the chooser. File to Switch Profile calls
  `unloadProfileAndShowProfileManager`. Surface mode lives in the global meta (`pm.meta`),
  shared across profiles, not per profile.
- Login today: the sync sign-in against the self-hosted server. `pgrep_sync` in
  `qt/aqt/pgrep.py` runs Anki's own main-thread sync against a custom URL (default
  `http://127.0.0.1:8090/`, account `pgrep`/`pgrep`), reachable from pgrep Settings to Sync.
  There is no login gate; study starts with no account.

## The removable-vs-load-bearing map

**Remove from the product (Anki-the-tool interface, currently only hidden):**

- The native menus File, View, Tools, Help and their actions: Study Deck, Create Filtered
  Deck, Check Database, Check Media, Empty Cards, Add-ons, Manage Note Types, Check for
  Updates, Import, Export.
- The deck browser and deck-based study (already redirected to pgrep, confirm no reachable
  path back in exclusive).
- The Add-ons system (third-party code, out of scope, a security surface).
- The Profile Manager chooser and File to Switch Profile (see profiles below).

**Keep as the invisible engine (load-bearing, never user-facing):**

- Collection, FSRS scheduler, sync, search, stats (all of `rslib`/`pylib`).
- Note types and decks as data (pgrep's Problem and card note types). Remove the management
  UI, keep the underlying types.
- Undo and Redo (needed by text fields and collection ops).
- Backups (keep running silently for data safety).
- The web host (`mediasrv`, `AnkiWebView`) that serves the whole UI.

**Keep but replace with a pgrep equivalent:**

- Preferences, already replaced by pgrep Settings (Cmd+,).
- Sync UI, already pgrep Settings to Sync.
- Profile identity, replaced by one implicit account plus the login gate below.
- Update check, disabled already; a pgrep updater is a later item.

**Dev-only, stays behind `ANKIDEV`/hosted, invisible to users:** the dev lab, Open Anki
screens, seed content, Check Database and Check Media for support.

## Work item 1: strip the Anki interface in exclusive mode

Go beyond hiding: in exclusive mode do not present the Anki menus or admin actions at all.
Keep Edit (Undo/Redo) for text fields, keep pgrep's Go and Settings. Keep every Anki screen
reachable in `hosted`/`off` so the dev hatch is intact. Verify no reachable route from any
pgrep surface back into an Anki screen while in exclusive.

## Work item 2: collapse profiles to one implicit local account

The product must never show Anki's Profile Manager or File to Switch Profile. Auto-create
and auto-open a single implicit profile (already the behavior for exactly one profile;
ensure the chooser cannot surface in exclusive, and hide Switch Profile). Keep the profile
and base-folder mechanism under the hood purely as the on-disk storage location.

Decision to raise with the user: a fresh collection is born with Anki's Default deck and the
stock Basic/Cloze note types. Decide whether to hide, rename, or scope the product to
pgrep's own deck and note types so a new account is not "polluted" by Anki defaults.

## Work item 3: the product login gate (model B)

First launch shows a pgrep sign-in screen (email or username plus password) with a "continue
offline" escape, so it feels like a real app you log into while offline-first still holds
(study and AI-off scoring must work with no account). Sign-in reuses the existing
`pgrep_sync` sign-in path.

Key design constraint: the gate must take a **configurable server URL and credential
source**, not a hardcoded address. Today it points at the self-hosted server
(`http://127.0.0.1:8090/`, `pgrep`/`pgrep`); in production it points at the hosted server
with a managed auth provider in front. The client code is identical either way.

## Work item 4: production infrastructure roadmap (document, do not build)

Recommended target stack (confirm with the user before finalizing; the client work is
identical across options):

- Host: Hetzner CPX22 (about $8/month, 20 TB bandwidth) or Fly.io (about $5/month,
  usage-based) if server management is unwanted.
- Sync server: the `anki-sync-server-enhanced` Docker image (built from official Anki
  source, multi-user `user-manager` CLI, hashed passwords, nightly backups with S3 upload,
  dashboard, metrics, fail2ban, TLS).
- TLS and proxy: Caddy (automatic HTTPS), or the image's built-in TLS.
- Backups: Cloudflare R2 (no egress fees), pennies a month for text and SVG collections.
- Auth for self-serve signup: Firebase Auth (free for email and social at scale, best mobile
  SDKs) with a small provisioning function that creates the matching sync account on first
  login. The heavy study data still syncs over Anki's protocol; auth only owns identity.

Auth maturity in two steps: (a) closed beta uses the server's built-in user-manager CLI, no
extra cost; (b) production adds Firebase Auth plus provisioning.

Costs: about $10/month to launch (tens of users), scaling to about $10 to $25/month into the
low thousands because local-first sync is small and intermittent and pgrep content is mostly
text and SVG. One-time or yearly: Apple Developer $99/year, Google Play $25 once, domain
about $12/year.

Deferred: a true browser (web) app. It needs the engine in WASM or server-side plus browser
storage, and is its own project. Desktop plus phone plus sync is the native, cheap path.
Park web in the roadmap.

## Constraints and house rules

- Do this in a fresh worktree off the latest `main` (for example
  `feat/l6-shell-profiles-login`). Do not tangle with `feat/l6-de-anki` or with `main`'s
  in-flight files. Merge `main` in as needed.
- No changes under `rslib/src/sync`. This is Qt host plus the TS surface plus docs.
- Engine invariants: never mutate `due`, `interval`, or `memory_state`; the app still scores
  with AI off.
- Copy rules: no em-dashes, short labels, calm voice, no interaction blocks the UI over
  100 ms.
- Attribution stays only in the About and licenses surface (already done).
- Finish green: `just check` on lint and unit tests, plus guard tests where wording or
  behavior could silently regress.
- Leave the work parked and uncommitted per the user's git rules. Do not commit or merge
  unless the user asks.

## Expected deliverables from that chat

1. A design doc in the repo house style covering work items 1 to 4, in `docs_pgrep/plan/`.
2. An implementation plan (waves and tasks) like the de-Anki plan.
3. The implementation in a worktree, verified green.
4. A short written decision on the first-run default-deck and note-type handling.

## Decisions to confirm with the user first

- The first-run login flow copy and the "continue offline" wording.
- The default-deck and stock note-type handling (hide, rename, or scope).
- The production stack above (or one of the noted alternatives) before the roadmap is final.

## Kickoff line

"Read `docs_pgrep/plan/2026-07-06-l6-shell-profiles-login-handoff.md`. Continue the L6
production mission. The branding sweep is done and parked in `.worktrees/l6-de-anki`, do not
redo it. Brainstorm and spec the structural de-Anki (menu removal), the profile collapse to
one implicit account, the model-B login gate with a configurable server URL, and the
production roadmap, then implement in a fresh worktree, verified with `just check`, left
uncommitted. Align with the vision: engine not interface, single-user, offline-first."
