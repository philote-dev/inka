# Design: L6 structural de-Anki (menus, profiles, window chrome) + hosting roadmap

Date: 2026-07-06. Status: design, awaiting spec review before the implementation plan.
Continues `shell-profiles-login-handoff.md`. The branding sweep it refers to is
already done and merged; this is the structural half.

## Goal

Remove Anki's interface from the shipped (exclusive) product so pgrep reads as its own app,
and keep Anki's engine as an invisible, upstream-mergeable dependency. The guiding line from
the vision is "reuse the engine, not the interface." The product is single-user, offline-first,
desktop plus phone, synced. pgrep is all a user ever sees.

## Scope

In scope this pass:

- **WI1** Purpose-built exclusive menu bar (build pgrep's own menus, do not build Anki's).
- **WI2** Collapse profiles to one implicit local account (the chooser can never surface).
- **WI5** macOS unified, transparent window title bar in exclusive mode.
- **WI4** Hosting roadmap doc (self-host on the author's Mac now, cloud later). Write-only.

Deferred (each its own later cycle):

- **WI3** The first-run login gate. Better once the hosting decision is made; the local server
  path already works today.
- **pgrep's own card template.** Today pgrep reuses Anki's stock `Basic` note type. Migrating
  off it touches the seeder, card sets, and generation, so it is its own project.

Untouched this pass:

- The stock collection defaults (the empty `Default` deck, the `Basic` and `Cloze` note types).
  No user ever sees them in exclusive mode, and `Basic` is load-bearing for pgrep.

## Grounding facts (verified in the repo)

- **Surface modes** live in `qt/aqt/pgrep_host.py`. `_DEFAULT_MODE = "exclusive"` is the product.
  `hosted` keeps Anki reachable (the dev hatch), `off` is stock Anki. `surface_mode()` reads the
  `PGREP_SURFACE_MODE` env override, then the profile meta, then the default.
- **Menus** are built in `qt/aqt/main.py` `setupMenus()` (around line 1472) from the shared
  `main.ui` form (`menuCol`, `menuEdit`, `menuqt_accel_view`, `menuTools`, `menuHelp`).
  `apply_menu_chrome()` today only _hides_ `menuCol`, `menuqt_accel_view`, `menuTools`, `menuHelp`
  in exclusive and drops Preferences from the app menu. The actions and their keyboard shortcuts
  are still created and connected, so keyboard routes into Anki's admin actions still fire.
  `_setup_pgrep_menus()` (around 1554) then adds a Go menu and a Settings item in exclusive.
- **Profiles**: `setupProfile()` (around `main.py:302`) already calls
  `pgrep_host.profile_to_autoload()` so exclusive auto-opens one profile and never shows the
  chooser on the normal path. `showProfileManager()` (`main.py:341`) still exists and draws
  Anki's chooser. `unloadProfileAndShowProfileManager()` (`main.py:616`) is wired to
  `actionSwitchProfile`. Both are the remaining ways the chooser could still surface.
- **The deck browser** is already redirected to pgrep in exclusive via
  `pgrep_host.redirect_state`, and Anki's in-window toolbar and bottom bar are hidden on every
  pgrep screen via `pgrep_host.sync_central_surface`.
- **pgrep uses the stock `Basic` note type.** `pylib/anki/pgrep/seed.py` calls
  `col.models.by_name("Basic")` and `card_sets.py` queries `note:Basic`. pgrep seeds into its own
  `PGRE::Sample` and `PGRE::Generated` decks, never the `Default` deck. So `Basic` cannot be
  renamed or deleted, and the leftover `Default` deck and `Cloze` type are simply unused.
- **The macOS native helper is a prebuilt wheel.** `qt/aqt/_macos_helper.py` does
  `from anki_mac_helper import macos_helper`. The dev env installs `anki_mac_helper` 0.1.1 into
  `out/pyenv`, shipping a compiled `libankihelper.dylib`. `qt/mac/theme.swift` and
  `qt/mac/anki_mac_helper/__init__.py` are the source of that wheel. `theme.swift` uses AppKit and
  exposes `@_cdecl` functions. There is no `pyobjc` in the environment.

## WI1: purpose-built exclusive menu bar (Approach C)

`setupMenus()` forks at the top on surface mode:

- **exclusive**: call a new `_setup_exclusive_menubar()` and return. Anki's admin actions are
  never created or connected, so there is genuinely no route to them, including keyboard
  shortcuts.
- **hosted / off**: run the existing Anki wiring unchanged. The dev hatch (full menus, Open Anki
  screens, dev lab, seed sample) is intact.

The exclusive menu bar holds only:

- **App menu** (macOS, via Qt menu roles so Qt relocates them): About pgrep (AboutRole),
  Settings (PreferencesRole, Cmd+,), Quit (QuitRole, Cmd+Q). macOS adds Hide and Services itself.
- **Edit**: Undo (Cmd+Z) and Redo (Shift+Cmd+Z) wired to the collection undo, plus Cut, Copy,
  Paste, and Select All (standard keys) for text fields.
- **Go**: Home (Cmd+1), Study (Cmd+2), Progress (Cmd+3), Library (Cmd+4) wired to
  `pgrep_navigate`, plus Enter Full Screen and Zoom In/Out/Reset.

There is no File, Tools, Help, Preferences duplicate, Open Anki screens, or Switch Profile.

Cross-platform: on macOS the top menu bar is mandatory for the focused app, so it stays but holds
only the above. On Windows and Linux the menu bar is in-window; in exclusive it is hidden entirely
(`menuBar().setVisible(False)`) because the left rail is the navigation, and the shortcuts still
fire.

This supersedes the current hide-then-add pair. `_setup_pgrep_menus()` folds into
`_setup_exclusive_menubar()`. `apply_menu_chrome()` is no longer needed for menu hiding in
exclusive (nothing to hide) and is removed or reduced to a no-op. `redirect_state` and
`sync_central_surface` are unchanged.

## WI2: one implicit local account

Approach C already removes the Switch Profile route, because exclusive has no File menu.
`profile_to_autoload` already auto-opens the single profile on the normal path. The remaining work
is to close the two failure-path routes so Anki's chooser can never surface in exclusive:

- Guard `showProfileManager()`: in exclusive, do not draw Anki's chooser. Auto-recover instead
  (open or create the single implicit profile). If the collection is genuinely unopenable, show a
  plain pgrep error and quit rather than the Anki manager.
- Make `unloadProfileAndShowProfileManager()` inert in exclusive (it has no menu entry there, but
  guard the method too so no future caller can reopen the chooser).

The profile and base-folder mechanism stays exactly as is, purely as the on-disk storage location.
Surface mode continues to live in the shared global meta, not per profile.

## WI5: macOS unified, transparent title bar (exclusive only)

Route: the official native one, matching how Anki already does macOS native work. Extend the Swift
helper rather than a runtime `ctypes` hack.

- Add an `@_cdecl` function to `qt/mac/theme.swift`, for example `set_titlebar_transparent`, that
  takes the window's native view pointer, resolves its `NSWindow`, and sets
  `titlebarAppearsTransparent = true`, `titleVisibility = .hidden`, and inserts
  `.fullSizeContentView` into the style mask. Add the matching wrapper in
  `qt/mac/anki_mac_helper/__init__.py`.
- Because the dev env consumes the pinned `anki_mac_helper` wheel, the app must load our built
  helper instead of 0.1.1. The implementation plan chooses the least-divergent wiring (build the
  helper from `qt/mac` into `out/pyenv`, overriding the wheel on macOS builds, is the leading
  candidate). This build wiring is the main risk and cost of WI5 and is called out for the plan.
- Call the helper from `qt/aqt/main.py` only in exclusive mode on macOS, after the main window is
  shown, passing `int(self.winId())`.
- The web rail needs a top-left safe area so it clears the traffic lights. The host tags the pgrep
  webview with a class (for example `pgrep-native-titlebar`) only when it applies the transparent
  bar. The rail keys its top padding off that class, so iOS and hosted mode are unaffected.

Reversible and macOS-only. Windows and Linux keep their standard window frames this pass.

## WI4: hosting roadmap doc (write-only, no servers built)

A new `docs_pgrep/plan/hosting-roadmap.md`:

- **Part 1, self-host on your Mac (now).** What `just sync-server` actually runs (Anki's built-in
  sync server via `tools/sync-server.py`, single user `pgrep:pgrep`, plain HTTP, bound to
  `0.0.0.0:8090`). How to keep it alive across reboots (a launchd LaunchAgent). Where the sync data
  lives and how to back it up. How the phone reaches it: on the LAN today (`your-mac-ip:8090`), or
  over the internet through a tunnel such as Tailscale or Cloudflare Tunnel plus TLS. Security
  caveats (single shared credential, HTTP on the LAN) and the honest limits of running the server
  on a personal machine.
- **Part 2, cloud (later, delegated).** The VPS options (Hetzner or Fly.io) plus
  `anki-sync-server-enhanced`, Caddy for TLS, Cloudflare R2 for backups, and auth phased from the
  built-in user-manager CLI to Firebase. Trade-offs and rough costs. The final pick is delegated,
  since the client work is identical across options.
- **Deferred**: a browser or web app. It needs the engine in WASM or server-side and is its own
  project.

## Testing

- A reachability test for exclusive mode: the menu bar exposes only the app, Edit, and Go menus;
  there is no route (menu or shortcut) to any Anki admin action or screen; the profile chooser
  cannot surface.
- A guard test that no pgrep surface lists the stock `Default` deck or `Cloze` note type.
- WI5 has no headless unit test (native window chrome). It is verified by a manual macOS check plus
  a screenshot in the review notes.
- `just check` green on lint and unit tests.

## House rules

- Fresh worktree `feat/l6-structural-de-anki` off the latest `main`. Merge `main` in as needed.
  (Named for scope; the login gate from the handoff is deferred.)
- No changes under `rslib/src/sync`. This is the Qt host plus the TS surface plus docs, plus the
  macOS Swift helper for WI5.
- Engine invariants: never mutate `due`, `interval`, or `memory_state`. The app still scores with
  AI off.
- Copy rules: no em-dashes, short labels, calm voice, no interaction blocks the UI over 100 ms.
- Attribution stays only in the About and licenses surface (already done).
- Leave the work parked and uncommitted per the git rules. Do not commit or merge unless asked.

## Deferred and future items (to record in `deferred-todos.md`)

- WI3 the first-run login gate.
- pgrep's own card template, to migrate off Anki's stock `Basic`.
- WI5 build note: if overriding the wheel proves messy, a pgrep-owned separate dylib target is the
  fallback.

## Decisions log (this session)

- Scope is WI1, WI2, WI4, WI5. WI3 login gate deferred.
- Menu removal uses Approach C (build pgrep's own menus, do not build Anki's), chosen over hiding.
- Collection defaults are left untouched; a future item captures pgrep's own note type.
- The window title bar becomes the unified, transparent macOS look (Option 2), folded into this
  pass as WI5, via the official native Swift helper route.
- WI4 leads with the local self-host path; the cloud stack choice is delegated for later.
