# L6 production readiness and de-Anki sweep, design

Date: 2026-07-06. Status: draft for review. Author: pair session.

This spec corrects the stale L6 section of `build-plan.md` to match today's repo, then
specifies the one piece of L6 we execute in this chat: removing every trace of Anki
from what a learner sees, while keeping Anki as the invisible engine and crediting it
only where the license requires. Packaging, hardening, and the submission recording are
re-scoped here as follow-ons, not built in this chat.

## Context

`build-plan.md` L6 ("Ship + harden") was written before a large run of L5.9 polish
landed. Several L6 tasks are already done on `main`, so the plan reads as further behind
than the code is. The product owner's directive for this track: the app presents as
**pgrep** everywhere a user looks, with Anki only underneath. The one legal constraint is
spec constraint 9 (AGPL-3.0-or-later, crediting Anki), which is satisfied by a single
licenses surface rather than by branding scattered through the UI.

## Corrected L6 reality (plan vs repo)

| `build-plan.md` L6 says | Repo reality today |
| --- | --- |
| L6.1 flip `_DEFAULT_MODE = "exclusive"` | Done. `qt/aqt/pgrep_host.py:39`. Deck browser redirects to pgrep (`redirect_state`), admin menus hidden (`apply_menu_chrome`). |
| L6.2 window and menu title | Done. Window title is "pgrep" (`qt/aqt/main.py:517`), pgrep window icon (`main.py:981`), macOS "About pgrep" label (`main.py:1475`), native pgrep menus (Settings, Go). |
| L6.2 remaining identity | Not done. The About dialog is pure Anki, sync and error dialogs still say "Anki" and "AnkiWeb". This is the de-Anki sweep below. |
| L6.2 packaging | Not done. Bundle name and id, `.dmg` name, phone build. Needs human signing. |
| L6.3 hardening | Not done. Crash test, benchmark. |
| L6.4 submission | Not done. Recording. Human-run. |

The genuine remainder of L6 is therefore: **(a) the de-Anki sweep** (this chat), and
**(b) re-planned follow-ons** (packaging, hardening, recording).

## Decisions locked with the product owner

- **Attribution home.** Anki is credited in exactly one user-facing place, an About and
  Open-Source Licenses surface, plus the `LICENSE` and AGPL files in the repo root.
  Nowhere else in the running app.
- **Repo internals untouched.** Per-file AGPL copyright headers, internal names
  (`AnkiWebView`, `aqt`, module paths), and git history stay as they are. They are not
  user-facing, so they are out of scope. A future rename is a separate call.
- **Approach A, reachability-first.** Rebrand only strings and assets a user can actually
  reach in the shipped exclusive surface, plus build the licenses home. No blind global
  find-replace across all of `ftl/` (that fights upstream merges and risks editing the
  license text itself).
- **Scope of this chat.** Rewrite the L6 plan (this doc plus a `build-plan.md` edit), then
  execute the de-Anki sweep. Packaging, hardening, and recording are re-planned only.

## Workstream 1: pgrep About and licenses (the credit home)

The About dialog (`qt/aqt/about.py`) is the linchpin. It is reachable in exclusive mode
(the macOS app menu keeps its About slot, `main.py:1474`), and it is currently pure Anki:
the Anki logo (`about.py:68`), the "Anki is a friendly, intelligent..." lede with "Anki®"
(`about.py:69`), plus version, trademark, and contributor links below.

- **Rebuild the About content as pgrep.** pgrep name, pgrep mark, the app version, a one
  line description in the calm instrument voice. Drop the Anki logo and the marketing
  lede.
- **Add an Open-Source Licenses and Credits block** inside that same dialog. It names Anki
  (Ankitects Pty Ltd) and the AGPL-3.0-or-later license, links to the source, and lists
  the other bundled open-source components. This is the one place Anki is named.
- **Add a Settings entry** (`ts/routes/pgrep/settings/+page.svelte`): a small "About and
  licenses" row so the credit is reachable and in-brand on every platform, not only via
  the macOS app menu. It shows the pgrep version and the same credit. Minimal surface, no
  new route needed.

Must-have: the rebranded Qt About dialog carrying the credit. The Settings row is the
in-brand, cross-platform discoverable path to the same information.

## Workstream 2: sync strings

Rebrand the reachable sync copy in `ftl/core/sync.ftl`. Sync is reachable from Settings,
so every string here can surface. This also fixes a correctness bug: the user self-hosts,
so "AnkiWeb" was never accurate.

Wording, locked to the neutral server scheme:

- Service noun: "AnkiWeb", "your sync server" (or "the server" where the possessive reads
  oddly).
- Conflict buttons: `sync-download-from-ankiweb`, "Download from server", and
  `sync-upload-to-ankiweb`, "Upload to server". These also render inside
  `sync-conflict-explanation2` and the empty-collection prompts, so the prose follows.
- App name: "Anki", "pgrep" (for example `sync-conflict`, "Only one copy of pgrep can sync
  at once", and `sync-must-wait-for-end`).
- Progress: `sync-downloading-from-ankiweb`, "Downloading from server...", and
  `sync-uploading-to-ankiweb`, "Uploading to server...".
- Errors and prompts: `sync-server-error`, "Your sync server encountered a problem. Please
  try again in a few minutes." `sync-confirm-empty-download`, "This device has no cards.
  Download from server?" `sync-confirm-empty-upload`, "The server has no cards. Replace it
  with this device's collection?"
- `sync-account-required` and the AnkiHub strings are for AnkiWeb and AnkiHub accounts,
  which a self-hosted pgrep never shows. Leave them unless the audit finds them reachable.

Rendered conflict dialog (the one currently seen):

> There is a conflict between this device and your sync server. You must choose which
> version to keep:
>
> - Select **Download from server** to replace the decks here with the server's version.
>   You will lose any changes made on this device since your last sync.
> - Select **Upload to server** to overwrite the server's version with the decks from this
>   device, and delete any changes stored there.
>
> Once the conflict is resolved, syncing will work as usual.

## Workstream 3: reachable error strings

`ftl/qt/errors.ftl` mixes two kinds of strings:

- **Generic user-facing errors** (for example "Anki encountered a problem", "restart
  Anki"), rebrand the app name to "pgrep".
- **Data-path and add-on strings** (for example the `Documents/Anki` folder, the Add-ons
  troubleshooting steps, the `help.ankiweb.net` support link). The folder name is tied to
  the on-disk data directory, so renaming it is a packaging decision with migration
  cost. Defer these to the packaging follow-on and only rebrand the app-name text now. The
  support link is repointed or dropped in the same follow-on.

## Workstream 4: reachability audit

Launch in exclusive mode and walk every reachable surface (Home, Study both doors,
Progress, Library, Diagnostic, Settings, Exam, the sync flow, and the error and About
dialogs). Note any stray "Anki" or "AnkiWeb" a user can reach. Rebrand what is reachable,
record what is not (so the follow-ons know about it). This is a sweep, not an
enumeration of all of `ftl/`.

## Bookkeeping: update build-plan.md

Rewrite the L6 section of `build-plan.md` so its status matches the table above: mark L6.1
and the title and icon work done, split the remainder into the de-Anki sweep (this chat)
and the packaging, hardening, and recording follow-ons. This keeps the single roadmap
honest.

## Re-planned follow-ons (not built in this chat)

- **Packaging.** Bundle display name and id, the `.dmg` name, the macOS app-menu name
  (`CFBundleName`), the data-folder and support-link cleanup from Workstream 3, and the
  phone build. Needs human signing and an Apple Developer decision.
- **Hardening.** Crash-test the review loop with zero corruption, and a one-command
  benchmark on a large collection reporting p50, p95, and worst.
- **Submission recording.** Clean-machine install capture and the demo, human-run.

## Constraints (inherited)

- Keep the AGPL credit, in the licenses surface only. Keep repo internals and per-file
  headers.
- The app still scores with AI off. Never mutate `due`, `interval`, or `memory_state`.
- No change under `rslib/src/sync`. This work is strings and assets only.
- Copy rule: no em-dashes, short labels, calm voice. No interaction blocks the UI over
  100ms.

## Exit gate (de-Anki sweep)

- Launched in exclusive mode, no "Anki" or "AnkiWeb" is visible on any reachable surface,
  except the Anki credit in the About and licenses surface.
- The sync conflict dialog reads in pgrep and server wording.
- The About dialog shows pgrep identity plus the license credit, reachable from Settings
  and the macOS app menu.
- `build-plan.md` L6 matches reality.
- `just lint` and `just test-py` are green.

## Aside: clearing the conflict you are seeing now

The dialog recurs because the desktop collection and the self-hosted server have diverged
and neither side has been chosen yet. Cancel leaves it unresolved, so it returns on the
next sync. Resolve it once: choose upload to push the desktop's current collection to the
server, or download to replace the desktop with the server's copy. After both devices
sync once, future reviews merge normally. This is engine behavior, not a bug, and the
rebrand in Workstream 2 only changes how the same dialog reads.
