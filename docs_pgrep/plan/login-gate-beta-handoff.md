# Handoff: first-run sign-in gate (beta) for another agent

Date: 2026-07-14. Status: page artifacts built; host hookup pending. This is the
single source of truth for the sign-in page. The Svelte artifacts are in the repo
(see "Page design and artifacts" below); the host plumbing and first-run Anki
chrome fixes land alongside the office beta.

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
  works. Gate may reappear next launch until they sign in once (product choice:
  prefer re-prompt until success, or remember "skipped" in collection config;
  default = remember skip for the session/profile so we do not nag every cold
  start during beta).
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

- `ts/lib/components/LoginGate.svelte` owns the UI, states, and styling. Props:
  `initialUrl`, `onSignIn({url, username, password}) => Promise<{ok, error?}>`, and
  `onContinueOffline()`. State seams for fixtures: `busy`, `error`, `serverOpen`,
  `initialUsername`, `initialPassword`. On an `ok` result the caller navigates; an
  `ok: false` (or a thrown error) shows a calm message in place.
- `ts/routes/pgrep/login/+page.svelte` is the thin wiring: it reads the saved URL
  (`pgrepSettingsGet.sync_url`), persists it (`pgrepSettingsSet`), calls `pgrepSync`,
  then lands on Home. It renders as a full-screen overlay so a standalone preview at
  `/pgrep/login` covers the shell rail.
- Review fixture: the "Login gate" section of `/pgrep-lab/gallery`, in light and dark,
  showing ready, signing in, and a failed attempt.

Visual: monochrome per the token rule (the amber/blue/lilac hues stay a reserved score
data language, never chrome), so the identity is the tri-lobe mark, a mono eyebrow, warm
canvas, a centered surface card, and one calm load motion. Fields are Username, Password,
a Server disclosure (prefilled, mono), a dark Sign in (with a spinner), and a Continue
offline ghost.

Known seam for the hookup: `pgrepSync` is fire-and-forget today (it returns "started" and
Anki's own progress/error dialog handles the rest), so the route resolves success
optimistically. The hookup should add a sign-in call that returns the real login result
and persist the gate-dismissed flag.

## Host / bridge hooks the implementer should use

Inspect and reuse (names may vary slightly; follow call sites in Settings):

- Read/write sync URL + stored auth used by `pgrep_sync` in `qt/aqt/pgrep.py`  
- Collection config or profile meta key for `login_gate_dismissed` /
  `login_gate_skipped` (pick one; document it in the PR)  
- Startup: after exclusive surface loads `/pgrep`, if gate not dismissed and not
  skipped, route to the login page before Home  

iOS: same fields in Settings today; a native login screen can wait. Desktop gate
first is enough for the DMG beta; mirror on iOS in a follow-up if time allows.

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
