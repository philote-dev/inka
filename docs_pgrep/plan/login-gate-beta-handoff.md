# Handoff: first-run sign-in gate (beta) for another agent

Date: 2026-07-14. Status: page artifacts built; host hookup planned, not yet built.
This is the single source of truth for the sign-in page and its host hookup. The
Svelte artifacts are in the repo (see "Page design and artifacts"); the hookup is
specced in "Real app migration plan" and lands alongside the office beta, with the
first-run Anki chrome fixes.

## Goal

On first launch (and when the user is not signed in), show a **pgrep** sign-in
screen: username, password, sync server URL (advanced / prefilled), and
**Continue offline**. Signing in must hook the existing Anki sync account model
used by the office beta (`SYNC_USERn` on `just serve-sync`), not invent a new
auth stack.

Offline-first stays sacred: study and AI-off scoring work with no account.

## What is already true (do not rebuild)

| Piece | Where | Notes |
| --- | --- | --- |
| Exclusive product surface | `qt/aqt/pgrep_host.py` `_DEFAULT_MODE = "exclusive"` | Anki deck browser / profile chooser suppressed |
| Sync from Settings | `ts/routes/pgrep/settings/+page.svelte`, `qt/aqt/pgrep.py` `pgrep_sync` | URL + user/pass → Anki sync protocol |
| Sync server | `just serve-sync` / `tools/sync-server.py` | `SYNC_USER1=user:pass`, port **8090** |
| Office beta ops | `docs_pgrep/plan/office-beta.md` | Tailscale + unsigned DMG + cable iOS |
| Prior design | `shell-profiles-login-handoff.md` WI3, `structural-de-anki-design.md` WI3 | Model B login gate |

## Critical host fix (must stay true)

Fresh profiles used to open Anki's **language picker** (`qt/aqt/forms/setlang.ui`,
window title was literally `"Anki"`). That dialog is skipped in product modes:

- `qt/aqt/__init__.py`: on `firstTime`, if `PGREP_SURFACE_MODE` is not `off`,
  call `pm.setLang(system_default)` instead of `pm.setDefaultLang(...)`.
- Qt application name is `pgrep` unless mode is `off`.
- `setlang.ui` title is `pgrep` if the hatch ever shows it.

Verify with `just preview-fresh` (throwaway `ANKI_BASE`). You must **not** see a
language list or an Anki-titled dialog before Home.

Any Anki-named chrome that still appears on exclusive startup is a bug. Fix it
in the host; do not paper over it in the sign-in Svelte page.

## Account model the page must use

Three layers (keep them distinct in the UI copy):

1. **Tailscale** (ops): can the device reach Frank's Mac. Not part of this page.
2. **Sync account** (`username` + `password`): matches `SYNC_USERn` on the
   server. One human → one sync user → one server-side collection.
3. **Local profile**: implicit single profile in exclusive mode. Not choosable.

Beta provisioning (human, not this page): Frank creates
`SYNC_USER1`, `SYNC_USER2`, … on the laptop sync server and gives each tester
their user/pass plus `http://<tailscale-ip>:8090/`.

Later (out of scope for this page): Firebase / self-serve signup that provisions
a matching `SYNC_USER`. Same client fields; different credential source.

## Page requirements (Svelte, product chrome)

**Route:** a first-run gate in the pgrep SPA (suggested: `ts/routes/pgrep/login/`
or a blocking overlay owned by the shell). It must use pgrep tokens
(`ts/lib/sass/_pgrep.scss`), not Anki Qt dialogs.

**Fields:**

- Username  
- Password  
- Server URL (default from Settings / `http://127.0.0.1:8090/` in dev; beta
  build may prefills Tailscale URL via env or a small config endpoint)  
- Primary button: **Sign in**  
- Secondary: **Continue offline**

**Behavior:**

- **Sign in:** persist URL + credentials the same way Settings sync does today,
  then call the existing sync bridge (`pgrepSync` / equivalent). On success,
  mark the gate dismissed for this profile and navigate to Home. On failure,
  show a calm error (bad password, unreachable server). Do not block the UI
  >100 ms without a spinner.
- **Continue offline:** dismiss the gate, never call sync, land on Home. Study
  works. Settled: remember the skip in **profile meta** (per-device) so we do not
  nag on every cold start; signing in later resolves the gate everywhere via the
  stored sync key. (See the migration plan below.)
- **AI:** unrelated; leave off.

**Do not:**

- Show Anki profile manager, language picker, or "Anki" window titles.  
- Hardcode production URLs.  
- Require Tailscale install from this page (document in the tester brief).  
- Invent a second password store separate from the sync credentials Settings
  already uses.

## Page design and artifacts (built)

The page is built as a reusable presentational component plus a thin route, so the
office-beta hookup can mount it with no rework.

- `ts/lib/components/LoginGate.svelte` owns the two steps, states, and styling.
  Props: `initialUrl`, `onSignIn({url, username, password}) => Promise<{ok, error?}>`,
  `onContinueOffline()`, and `initialStep` (`"welcome" | "signin"`, so the hookup can
  open a returning-but-signed-out user straight on sign-in). Fixture seams: `busy`,
  `error`, `advancedOpen`, `initialUsername`, `initialPassword`. On an `ok` result the
  caller navigates; an `ok: false` (or a thrown error) shows a calm message in place.
- `ts/routes/pgrep/login/+page.svelte` is the thin wiring: it reads the saved URL
  (`pgrepSettingsGet.sync_url`), persists it (`pgrepSettingsSet`), calls `pgrepSync`,
  then lands on Home. It renders as a full-screen overlay so a standalone preview at
  `/pgrep/login` covers the shell rail.
- Review fixture: the "Login gate" section of `/pgrep-lab/gallery` shows Welcome in
  light and dark; the fixtures are height-capped and the sign-in step and its states
  link to the live route, because the gallery is one long page with a ~16384px browser
  paint ceiling (unbounded full-screen fixtures pushed the tail past it and it went
  blank).

Flow and visual: two steps that hand off from the opening splash (which owns the logo),
so neither step repeats the mark.

- **Welcome:** "Welcome to pgrep" with a filled **Beta** pill in the action (opposing)
  color, one line ("The honest way to prep for the Physics GRE."), a primary **Sign in**,
  a ghost **Continue offline**, and a reassurance line ("Everything works offline. Sign
  in to sync.").
- **Sign in:** a back chevron to the left of the title, the helper "Use the username and
  password we sent you.", Username, Password, the baked server URL under a closed
  **Advanced** disclosure, a primary Sign in with a spinner, and a calm inline error.

Chrome is monochrome per the token rule (amber/blue/lilac stay reserved for the scores),
with one calm load motion.

Known seam for the hookup: `pgrepSync` is fire-and-forget today (it returns "started" and
Anki's own progress/error dialog handles the rest), so the route resolves success
optimistically. The migration adds a sign-in call that returns the real login result and
persists the skip flag (see the plan below).

## Real app migration plan (host hookup)

Today the artifacts exist but nothing shows the gate on startup; `/pgrep/login` is only
reachable directly. This migration makes the app present the gate on first run and when
signed out, persists the choice, and returns a real sign-in result.

Decisions (settled): the "continue offline" skip is stored in **profile meta**
(per-device, not synced), and we **remember the skip** so a cold start does not nag.
Signing in on any device resolves the gate everywhere via the stored sync key.

**Phase 1, backend + bridge (`qt/aqt/pgrep.py`, `anki.pgrep`).**

- `pgrepAuthStatus` returns `{ signed_in, gate_dismissed }`. `signed_in` is
  `mw.pm.sync_auth() is not None`; `gate_dismissed` is `signed_in or skipped`, where
  `skipped` is a profile-meta flag (for example `pm.meta["pgrep_login_gate_skipped"]`).
- `pgrepSignIn` runs `col.sync_login(username, password, endpoint)` on a worker, stores
  the key and URL (`pm.set_custom_sync_url`, `pm.set_sync_key`, `pm.set_sync_username`),
  starts a sync, and returns `{ ok: true }` or `{ ok: false, error }`. This closes the
  fire-and-forget seam. Keep `pgrep_sync` for the Settings "Sync now" button.
- `pgrepGateSkip` sets the profile-meta skip flag.
- Tests: extend `qt/tests/test_pgrep_bridge.py` (auth status, sign-in success and
  failure via a fake, skip).

**Phase 2, shell wiring (`ts/routes/pgrep/+layout.svelte`).**

- After the splash, call `pgrepAuthStatus`; if `!signed_in && !gate_dismissed`, render
  `<LoginGate>` as a full overlay before the app, mirroring the existing `showLanding`
  pattern. Order: splash then gate (if needed) then app then the diagnostic Landing.
- Wire `onSignIn` to `pgrepSignIn` (on ok, mark dismissed for the session and go to
  Home), `onContinueOffline` to `pgrepGateSkip`, and `initialUrl` from
  `pgrepSettingsGet.sync_url`.
- Keep `/pgrep/login` as a thin wrapper for preview and e2e.

**Phase 3, beta URL prefill.** The beta build defaults `sync_url` to the Tailscale URL so
testers never type it (it sits under Advanced). Never hardcode a production URL in the
page.

**Phase 4, sign-out (small, optional).** A Settings "Sign out" clears the sync key and
the skip flag so the gate returns, handy for switching test accounts.

**Phase 5, testing.** The bridge tests above, plus a Playwright e2e (`ts/tests/e2e/`):
first run shows the gate; Continue offline lands on Home and study works; sign-in against
`just serve-sync` reaches Home and Settings shows the saved URL and user. Then
`just check` and `just verify`. Guard that offline-first still scores with AI off.

**Phase 6, iOS (later).** The same fields already live in iOS Settings; a native
first-run gate mirrors desktop in a follow-up.

## Beta acceptance

1. `just preview-fresh` → no language dialog, no "Anki" titled startup chrome.  
2. New user sees pgrep sign-in (or offline) before studying.  
3. Sign-in with a real `SYNC_USER` against `just serve-sync` syncs; Progress /
   attempts survive a second device.  
4. Continue offline studies with no server.  
5. Settings → Sync still shows the same URL/user the gate saved.

## Out of scope for the page agent

- Tailscale / launchd / DMG / cable iOS (see `office-beta.md`)  
- Notarization / Apple Developer  
- Firebase / self-serve signup  
- Webshell / PWA  
- Changing the Anki sync protocol
