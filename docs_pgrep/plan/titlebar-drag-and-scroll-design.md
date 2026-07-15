# Title bar drag and scroll containment, design

Date: 2026-07-14. Status: approved, ready to plan. Author: pair session.

## Context

The shipped product surface on macOS (surface mode `exclusive`) uses Qt 6.9's
expanded client area so the pgrep web surface fills the window edge to edge and
the traffic lights float over it, with no separate title strip. This is set in
`pgrep_host.apply_native_titlebar` (`ExpandedClientAreaHint`,
`NoTitleBarBackgroundHint`, and `WA_ContentsMarginsRespectsSafeArea` off).

Three problems came out of that treatment:

1. The window is no longer draggable by its top edge. The `QWebEngineView`
   covers the whole window, including the title bar area, and consumes the mouse
   events a native drag would need.
2. Content can collide with the floating traffic lights. Clearance is a
   hardcoded `28px` guess in `+layout.svelte`, not the real inset.
3. The whole app scrolls and rubber-bands. The shell uses `min-height: 100vh`
   and the content panel has no overflow, so the entire document (the rail
   included) scrolls as one, rather than only the content area.

This spec fixes all three, scoped to macOS `exclusive` only. `hosted`, `off`,
non-mac, and the dev lab (`/pgrep-lab`) are untouched.

## Principle

Keep the edge-to-edge look with floating traffic lights. Restore the missing
window behaviors around it rather than reverting to a stock title bar. Make the
traffic-light inset come from Qt (one honest source of truth) instead of a magic
number, and make the app frame behave like a normal desktop app where the chrome
stays put and only the content panel scrolls.

## Part 1: restore window dragging

Add a transparent native drag strip over the top edge of the window, above the
pgrep webview, that moves the window on drag. A native overlay is the only
reliable option under Qt WebEngine: the web view consumes mouse events, so
`-webkit-app-region` (Electron only) and a passive native title bar do not work,
and a JS to Python bridge to `startSystemMove` is racy because the native move
loop needs the live mouse-down event.

- A `PgrepTitleBarDrag(QWidget)`:
  - `mousePressEvent` calls `self.window().windowHandle().startSystemMove()`.
  - `mouseDoubleClickEvent` toggles zoom, the standard macOS title-bar gesture.
  - Transparent (`WA_TranslucentBackground`, `WA_NoSystemBackground`, no paint)
    so the web shows through. It grabs only press and double-click and passes
    everything else.
- Geometry: `x` starts to the right of the traffic-light cluster so the lights
  still receive their clicks, spans to the right window edge, and its height is
  the Qt safe-area top inset (Part 2). It is kept `raise()`d above the webview
  and repositioned whenever the window resizes (an event filter on the main
  window).
- Installed only when `is_mac and surface_mode(mw) == "exclusive"`, right after
  `apply_native_titlebar`. Lives with the other host code (a helper in
  `pgrep_host.py`, or a small `pgrep_titlebar.py` if it reads cleaner).

## Part 2: traffic-light collision, one honest source of truth

Replace the hardcoded `28px` with Qt's real inset. `QWindow.safeAreaMargins()`
(Qt 6.9) reports the area obscured by the traffic lights and title bar.

- On load, and on `safeAreaMarginsChanged`, push the top inset to the web as a
  CSS custom property `--pgrep-titlebar-inset` on the document element. The
  existing `pgrep-native-titlebar` body class stays as the on/off gate.
- `+layout.svelte` uses `var(--pgrep-titlebar-inset, 28px)` everywhere it now
  hardcodes the inset (`.shell` padding-top, `.rail-burger`, `.rail-edge`), so
  `28px` becomes a fallback rather than the truth. The same value drives the
  native strip height, so the strip and the content inset never disagree.
- Left clearance: the rail stays on the left and its content already sits below
  the top inset, so it clears the lights vertically. The collapsed-rail burger
  uses the same inset instead of its own `42px`.

## Part 3: fixed shell, one scroll panel

Convert the shell to a fixed app frame where the chrome is stationary and only
the content panel scrolls, the way a normal desktop app behaves. This also ends
the whole-window rubber-band, because the document itself no longer scrolls.

- `+layout.svelte`:
  - `.pgrep`: `height: 100dvh; overflow: hidden` (was `min-height: 100vh`).
  - `.shell`: `height: 100%; overflow: hidden; box-sizing: border-box`, keeping
    the safe-area `padding-top`.
  - `.page`: `overflow-y: auto; overscroll-behavior: contain`, so only it
    scrolls and its bounce does not chain to the window. The rail becomes
    full-height and stationary.
- Reset to top: the `resetSignal` handler in `+layout.svelte` currently calls
  `window.scrollTo({ top: 0 })`. Retarget it to the `.page` element via a bound
  ref. Study reacts to `resetSignal` itself and does not touch window scroll, so
  it is unaffected.
- Inner heights: product pages that set `100vh` on an inner element
  (`+page.svelte` Home, `library/+page.svelte`) switch to `100%` or `100dvh` so
  they fill the panel instead of forcing a second scrollbar inside it.

## Part 4: full-height structure, inset content, faded divider (refinement)

The first pass inset the whole shell (`padding-top` on `.shell`), which pushed
the rail and its `border-right` down so the divider stopped short of the top and
read as incomplete. The governing principle from the macOS full-height sidebar
pattern (WWDC20) is to separate structure from content: the columns and the
divider fill to the window's top edge, and only the content is inset by the
title-bar safe area.

- Move the inset off `.shell` and onto the two content columns:
  - `.page` gets `padding-top: var(--pgrep-titlebar-inset, 28px)` (native only).
  - `.rail` gets a native top padding so the brand and nav clear the lights.
  - `.shell` no longer pads, so the rail runs full height.
- Divider: the rail's right divider fades out over the top band rather than
  running into the floating traffic lights or hard-terminating below them. A
  masked pseudo-element (a `linear-gradient` mask over the top inset) gives the
  intentional fade; non-mac keeps the plain full-height hairline.
- Scroll-edge shadow: a subtle separator under the band that fades in only once
  the content panel has scrolled, matching native `titlebarSeparatorStyle`
  behavior, instead of a permanent line.

### The collision guarantee

Content cannot collide with the traffic lights by construction:
`QWindow.safeAreaMargins().top()` is the platform's own definition of the region
where content would be obscured, so insetting content by it removes overlap by
definition. The inset is applied on the shared shell columns, so every surface
inherits it, and `_safe_area_top` clamps to a floor (`max(reported, 28px)`) so it
can never under-inset. Two residual caveats, both designed around: a sub-second
first-paint frame uses the CSS fallback before the pushed value lands, and any
future `position: fixed` element placed in the top-left must use the
`--pgrep-titlebar-inset` variable itself.

## Non-goals

- No change to `hosted`, `off`, non-mac, or the dev lab (`/pgrep-lab`).
- No revert to a stock native title bar. The edge-to-edge look stays.
- No new dependency and no protobuf or bridge-contract change. The inset is
  pushed with the same `web.eval` mechanism `enter_pgrep` already uses.

## Testing and verification

- Manual on macOS via `just preview` (exclusive surface):
  - Drag the window by the top strip; confirm the traffic lights still click.
  - Confirm the content panel scrolls internally while the rail and top stay
    put, with no whole-window rubber-band.
  - Check light and dark themes, and the rail both collapsed and expanded.
- `just check` for format, lint, and types across Python and Svelte.
- A small `pgrep_host` (or `pgrep_titlebar`) unit check for the pure gating
  logic (strip present only for mac plus exclusive), if it isolates cleanly
  without a live `QWidget`.

## Rollout

Doc-only spec work lands in the primary checkout. Implementation lands in a
dedicated worktree and branch (for example `feat/titlebar-drag-and-scroll`) per
the repo worktree convention, then merges to `main`.
