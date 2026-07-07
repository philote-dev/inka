# Interface prune, design (remove Anki's UI, keep the engine)

Date: 2026-07-07. Status: draft for review. Author: pair session.

## Context

pgrep is a product built on the Anki engine. The vision is explicit: reuse the
engine, not the interface (`docs_pgrep/research/vision-and-structure.md`). This
spec removes Anki's user-facing interface from the shipped product while keeping
the engine as an invisible dependency.

This is the structural half of the de-Anki work. The branding string sweep is a
sibling effort (`2026-07-06-l6-production-de-anki-design.md`, parked in
`feat/l6-de-anki`), and the detailed grounding lives in
`2026-07-06-l6-shell-profiles-login-handoff.md`. Execution should land in a
dedicated worktree (`feat/l6-structural-de-anki` already exists).

## Principle

Keep `rslib`, `pylib`, and `proto` intact and upstream-mergeable. Delete or hide
Anki's interface, which lives in the `qt/aqt` shell and the `ts` surfaces. Nothing
here touches the engine.

## The map

Remove from the product: File, View, Tools, and Help menus and their actions
(Study Deck, Create Filtered Deck, Check Database, Check Media, Empty Cards,
Add-ons, Manage Note Types, Check for Updates, Import, Export), the deck browser,
the add-on system, the profile chooser, and File to Switch Profile.

Keep as the invisible engine: the collection, FSRS, sync, search, stats, note
types and decks as data, Undo and Redo, backups, and the web host (`mediasrv`,
`AnkiWebView`).

Replace with a pgrep equivalent: Preferences becomes pgrep Settings, the sync UI
is pgrep Settings then Sync, and profile identity becomes one implicit account
plus the login gate.

Dev-only, behind `ANKIDEV` or hosted mode: the dev lab, Open Anki screens, seed
content, and Check Database and Check Media for support.

## Work items

1. Exclusive mode stops presenting Anki's menus and actions, rather than only
   hiding them. Keep Edit (for text fields) plus pgrep's Go and Settings. Hosted
   and off remain the dev hatch.
2. Collapse profiles to one implicit local account. Remove the chooser and Switch
   Profile from the product; keep the profile mechanism under the hood as storage.
   Decide the handling of Anki's default deck and stock note types so a new
   account is not seeded with Anki defaults.
3. Add the model-B login gate: a first-launch pgrep sign-in with a continue
   offline escape, a configurable server URL and credential source, reusing the
   existing `pgrep_sync` path.

## Constraints

Do it in a worktree. No changes under `rslib/src/sync`. Respect engine invariants
(never mutate `due`, `interval`, `memory_state`; app still scores with AI off).
Copy rules: no em-dashes, short labels, no UI block over 100 ms. Finish with
`just check` green plus guard tests. Leave parked and uncommitted unless asked to
integrate.

## Exit gate

Launched in exclusive mode, the product shows zero Anki interface. The profile
chooser is gone and one implicit account opens straight in. The login gate works
offline-first. `just check` and `just test-e2e` are green.
