# Title bar drag and scroll containment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the macOS exclusive product surface, make the window draggable by its top edge again, keep content clear of the traffic lights using Qt's real inset, and make only the content panel scroll instead of the whole app.

**Architecture:** A transparent native `QWidget` drag strip overlays the top edge of the pgrep webview and starts a native window move on press. Qt 6.9's `QWindow.safeAreaMargins()` is the single source of truth for the traffic-light inset, pushed to the web as the `--pgrep-titlebar-inset` CSS variable. The Svelte shell becomes a fixed app frame (`100dvh`, `overflow: hidden`) whose content panel is the only scroll container.

**Tech Stack:** Python + PyQt6 (`qt/aqt`), Svelte + SCSS (`ts/routes/pgrep`), pytest (`qt/tests`), the `just` recipes for build/check.

## Global Constraints

- Scope every runtime behavior to macOS AND surface mode `exclusive`. `hosted`, `off`, non-mac, and the dev lab (`/pgrep-lab`) must be unchanged. Gate with `pgrep_titlebar.native_titlebar_enabled(mode, is_mac)`.
- Keep the edge-to-edge look (floating traffic lights). Do not revert to a stock native title bar.
- No new dependency, no protobuf change, no bridge-contract change. Push the inset with the existing `AnkiWebView.eval` mechanism.
- Reserve `_TRAFFIC_LIGHTS_WIDTH = 80` px at the top-left so the drag strip never covers the traffic lights.
- Fallback inset is `28` px (`_DEFAULT_INSET`), used before Qt reports a safe area and as the CSS `var(...)` fallback, matching the historic value.
- Writing style: no em dashes; colons and semicolons used sparingly.
- Final gate for the whole change: `just check` passes.

---

### Task 1: Pure title-bar helpers and gating refactor (Python)

Create the new module with only its pure, testable helpers, and route the existing `apply_native_titlebar` guard through the shared predicate. No Qt window is needed to test this task.

**Files:**

- Create: `qt/aqt/pgrep_titlebar.py`
- Modify: `qt/aqt/pgrep_host.py` (`apply_native_titlebar`, around lines 154-173)
- Test: `qt/tests/test_pgrep_titlebar.py`

**Interfaces:**

- Produces:
  - `pgrep_titlebar.native_titlebar_enabled(mode: str, is_mac: bool) -> bool`
  - `pgrep_titlebar.titlebar_inset_script(top_px: int) -> str`
  - `pgrep_titlebar._TRAFFIC_LIGHTS_WIDTH: int` (= 80)
  - `pgrep_titlebar._DEFAULT_INSET: int` (= 28)

- [ ] **Step 1: Write the failing tests**

Create `qt/tests/test_pgrep_titlebar.py`:

```python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep macOS title-bar runtime.

Only the pure helpers are covered here; the drag strip needs a live window, so it
is verified manually. The negative install path (not mac, or not exclusive) is
still exercised because it returns before touching Qt.
"""

import types

from aqt import pgrep_titlebar


def test_native_titlebar_enabled_only_for_mac_exclusive() -> None:
    assert pgrep_titlebar.native_titlebar_enabled("exclusive", True) is True
    assert pgrep_titlebar.native_titlebar_enabled("exclusive", False) is False
    assert pgrep_titlebar.native_titlebar_enabled("hosted", True) is False
    assert pgrep_titlebar.native_titlebar_enabled("off", True) is False


def test_inset_script_sets_the_custom_property() -> None:
    script = pgrep_titlebar.titlebar_inset_script(28)
    assert "--pgrep-titlebar-inset" in script
    assert "'28px'" in script
    # Value is coerced to an int so a float never leaks into the CSS.
    assert "'34px'" in pgrep_titlebar.titlebar_inset_script(34.7)  # type: ignore[arg-type]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `just test-py` (or `pytest qt/tests/test_pgrep_titlebar.py -v` in the qt env)
Expected: FAIL with `ModuleNotFoundError: No module named 'aqt.pgrep_titlebar'`

- [ ] **Step 3: Create `qt/aqt/pgrep_titlebar.py` with the pure helpers**

```python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""macOS native title-bar runtime for the pgrep product surface.

The exclusive product on macOS extends the web surface under a transparent title
bar (see ``pgrep_host.apply_native_titlebar``). That leaves two gaps this module
fills. The window can no longer be dragged by its top edge, because the
``QWebEngineView`` covers the whole window and consumes the mouse events a native
drag needs, so a thin transparent strip restores dragging. And the real
traffic-light inset must reach the web as a variable rather than a guessed
constant, so it is read from Qt's safe-area margins and pushed to the page.

Everything here is scoped to macOS plus surface mode ``exclusive``; it is inert
elsewhere.
"""

from __future__ import annotations

# Width reserved at the top-left for the macOS traffic lights, so the drag strip
# never sits over them and swallows their clicks. The three controls span roughly
# 13..77px; 80 leaves a small margin.
_TRAFFIC_LIGHTS_WIDTH = 80

# Fallback title-bar inset used before Qt reports a real safe area, and as the CSS
# fallback. Matches the historic hardcoded value.
_DEFAULT_INSET = 28


def native_titlebar_enabled(mode: str, is_mac: bool) -> bool:
    """True only for the shipped product on macOS (exclusive plus mac)."""
    return is_mac and mode == "exclusive"


def titlebar_inset_script(top_px: int) -> str:
    """JS that sets the ``--pgrep-titlebar-inset`` custom property on the page."""
    return (
        "document.documentElement.style.setProperty("
        f"'--pgrep-titlebar-inset', '{int(top_px)}px');"
    )
```

- [ ] **Step 4: Route the existing guard through the predicate**

In `qt/aqt/pgrep_host.py`, `apply_native_titlebar` currently guards with:

```python
    from anki.utils import is_mac

    if not is_mac or surface_mode(mw) != "exclusive":
        return
```

Replace those lines with:

```python
    from anki.utils import is_mac

    from aqt import pgrep_titlebar

    if not pgrep_titlebar.native_titlebar_enabled(surface_mode(mw), is_mac):
        return
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `just test-py` (or `pytest qt/tests/test_pgrep_titlebar.py qt/tests/test_pgrep_host.py -v`)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add qt/aqt/pgrep_titlebar.py qt/aqt/pgrep_host.py qt/tests/test_pgrep_titlebar.py
git commit -m "feat(pgrep): add pure macOS title-bar helpers and share the enable gate"
```

---

### Task 2: Native drag strip, safe-area inset push, and wiring (Python)

Add the transparent drag strip and the inset push to `pgrep_titlebar.py`, then wire them in: create the strip after the window is shown, and re-push the inset when the pgrep page loads. The live widget is verified manually; the negative install path is unit-tested because it returns before creating any widget.

**Files:**

- Modify: `qt/aqt/pgrep_titlebar.py` (add the widget, `install`, `push_inset`)
- Modify: `qt/aqt/pgrep_host.py` (`enter_pgrep`, around lines 134-151)
- Modify: `qt/aqt/main.py` (`loadProfile`, the `else:` show branch around lines 561-564)
- Test: `qt/tests/test_pgrep_titlebar.py` (add negative-path cases)

**Interfaces:**

- Consumes: `native_titlebar_enabled`, `titlebar_inset_script`, `_TRAFFIC_LIGHTS_WIDTH`, `_DEFAULT_INSET` (Task 1); `pgrep_host.surface_mode(mw) -> str`; `mw.form.centralwidget`, `mw.pgrep_web`, `mw.windowHandle()`.
- Produces:
  - `pgrep_titlebar.PgrepTitleBarDrag(mw)` (a `QWidget`)
  - `pgrep_titlebar.install(mw) -> None`
  - `pgrep_titlebar.push_inset(mw) -> None`

- [ ] **Step 1: Write the failing negative-path tests**

Append to `qt/tests/test_pgrep_titlebar.py`:

```python
def test_install_is_a_noop_when_not_enabled(monkeypatch) -> None:
    # not exclusive -> install returns before touching Qt, so a bare stub is fine
    calls = {"surface": "hosted"}
    mw = types.SimpleNamespace(pgrep_web=None, form=types.SimpleNamespace())
    monkeypatch.setattr(pgrep_titlebar, "_current_mode", lambda _mw: calls["surface"])
    monkeypatch.setattr(pgrep_titlebar, "_running_on_mac", lambda: True)
    pgrep_titlebar.install(mw)
    assert not hasattr(mw, "_pgrep_titlebar_drag")


def test_push_inset_is_a_noop_without_a_webview() -> None:
    mw = types.SimpleNamespace(pgrep_web=None)
    # No pgrep webview means nothing to eval into; must not raise.
    pgrep_titlebar.push_inset(mw)
```

Note: the test monkeypatches two tiny seams (`_current_mode`, `_running_on_mac`) so the negative path never imports a live Qt window. Define them in Step 2.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest qt/tests/test_pgrep_titlebar.py -v`
Expected: FAIL with `AttributeError: module 'aqt.pgrep_titlebar' has no attribute 'install'`

- [ ] **Step 3: Add the widget, install, and push_inset**

Add to `qt/aqt/pgrep_titlebar.py`. Extend the imports at the top of the file:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from aqt.qt import QEvent, Qt, QWidget

if TYPE_CHECKING:
    from aqt.qt import QMouseEvent, QObject

    import aqt.main
```

Add these seams and the runtime below the pure helpers:

```python
def _running_on_mac() -> bool:
    from anki.utils import is_mac

    return is_mac


def _current_mode(mw: aqt.main.AnkiQt) -> str:
    from aqt import pgrep_host

    return pgrep_host.surface_mode(mw)


def _safe_area_top(mw: aqt.main.AnkiQt) -> int:
    """The true traffic-light inset in px, or the fallback before Qt reports it."""
    handle = mw.windowHandle()
    top = handle.safeAreaMargins().top() if handle is not None else 0
    return top if top > 0 else _DEFAULT_INSET


class PgrepTitleBarDrag(QWidget):
    """Transparent strip over the top edge that moves the window on drag.

    Parented to the central widget and kept above the pgrep webview. It grabs only
    press (start a native window move, with a manual-move fallback) and
    double-click (toggle zoom); every other event passes through untouched. It is
    its own event filter on the central widget, so it re-lays-out on resize.
    """

    def __init__(self, mw: aqt.main.AnkiQt) -> None:
        self._mw = mw
        central = mw.form.centralwidget
        super().__init__(central)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._manual_origin = None  # QPoint | None; fallback drag offset
        central.installEventFilter(self)
        self.relayout()

    def relayout(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        top = _safe_area_top(self._mw)
        width = max(0, parent.width() - _TRAFFIC_LIGHTS_WIDTH)
        self.setGeometry(_TRAFFIC_LIGHTS_WIDTH, 0, width, top)
        self.raise_()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.relayout()
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        handle = self._mw.windowHandle()
        if handle is not None and handle.startSystemMove():
            event.accept()
            return
        # Fallback: track the offset and move the window manually.
        win = self._mw
        self._manual_origin = (
            event.globalPosition().toPoint() - win.frameGeometry().topLeft()
        )
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._manual_origin is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            self._mw.move(event.globalPosition().toPoint() - self._manual_origin)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._manual_origin = None
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        win = self._mw
        win.setWindowState(win.windowState() ^ Qt.WindowState.WindowMaximized)
        event.accept()


def push_inset(mw: aqt.main.AnkiQt) -> None:
    """Send the current traffic-light inset to the pgrep page as a CSS variable."""
    web = getattr(mw, "pgrep_web", None)
    if web is None:
        return
    web.eval(titlebar_inset_script(_safe_area_top(mw)))


def install(mw: aqt.main.AnkiQt) -> None:
    """Create the drag strip and start tracking the safe-area inset.

    Call once, after the main window is shown. Inert unless mac plus exclusive.
    """
    if not native_titlebar_enabled(_current_mode(mw), _running_on_mac()):
        return
    strip = PgrepTitleBarDrag(mw)
    strip.show()
    # Keep a reference so the widget and its event filter outlive this call.
    mw._pgrep_titlebar_drag = strip  # type: ignore[attr-defined]
    handle = mw.windowHandle()
    if handle is not None:

        def _on_safe_area_changed() -> None:
            strip.relayout()
            push_inset(mw)

        handle.safeAreaMarginsChanged.connect(_on_safe_area_changed)
    push_inset(mw)
```

- [ ] **Step 4: Push the inset when the pgrep page first loads**

In `qt/aqt/pgrep_host.py`, `enter_pgrep` ends with:

```python
if is_mac and surface_mode(mw) == "exclusive":
    web.eval("document.body.classList.add('pgrep-native-titlebar');")
```

Append the inset push right after that `eval`:

```python
        if is_mac and surface_mode(mw) == "exclusive":
            web.eval("document.body.classList.add('pgrep-native-titlebar');")
            from aqt import pgrep_titlebar

            pgrep_titlebar.push_inset(mw)
```

- [ ] **Step 5: Install the strip after the window is shown**

In `qt/aqt/main.py`, `loadProfile` shows the window in its `else:` branch:

```python
else:
    self.show()
    self.activateWindow()
    self.raise_()
```

Add the install call at the end of that branch:

```python
        else:
            self.show()
            self.activateWindow()
            self.raise_()
            from aqt import pgrep_titlebar

            pgrep_titlebar.install(self)
```

- [ ] **Step 6: Run the unit tests to verify they pass**

Run: `pytest qt/tests/test_pgrep_titlebar.py -v`
Expected: PASS (negative paths only; the live widget is verified in Step 7)

- [ ] **Step 7: Manual verification on macOS**

Run: `just preview` (exclusive surface).
Expected:

- The window drags by its top edge (the band above the rail and content), and the traffic lights still respond to clicks.
- Double-clicking the top band toggles maximize.
- Content and the rail sit clear of the traffic lights.

- [ ] **Step 8: Commit**

```bash
git add qt/aqt/pgrep_titlebar.py qt/aqt/pgrep_host.py qt/aqt/main.py qt/tests/test_pgrep_titlebar.py
git commit -m "feat(pgrep): restore macOS window dragging with a native title-bar strip"
```

---

### Task 3: Traffic-light inset variable on the web (Svelte)

Consume the pushed `--pgrep-titlebar-inset` variable so the clearance tracks Qt's real inset, with `28px`/`42px` as fallbacks instead of the truth.

**Files:**

- Modify: `ts/routes/pgrep/+layout.svelte` (the `pgrep-native-titlebar` rules, around lines 231-245)

**Interfaces:**

- Consumes: `--pgrep-titlebar-inset` (set by `pgrep_titlebar.push_inset`, Task 2).

- [ ] **Step 1: Replace the hardcoded insets with the variable**

In `ts/routes/pgrep/+layout.svelte`, replace:

```scss
    :global(body.pgrep-native-titlebar) .shell {
        padding-top: 28px;
    }

    :global(body.pgrep-native-titlebar) .rail-burger {
        top: 42px;
    }

    :global(body.pgrep-native-titlebar) .rail-edge {
        top: 28px;
    }
```

with:

```scss
    :global(body.pgrep-native-titlebar) .shell {
        padding-top: var(--pgrep-titlebar-inset, 28px);
    }

    :global(body.pgrep-native-titlebar) .rail-burger {
        top: calc(var(--pgrep-titlebar-inset, 28px) + 14px);
    }

    :global(body.pgrep-native-titlebar) .rail-edge {
        top: var(--pgrep-titlebar-inset, 28px);
    }
```

- [ ] **Step 2: Verify svelte/type/lint checks pass**

Run: `just lint`
Expected: PASS (includes check:svelte and check:typescript)

- [ ] **Step 3: Commit**

```bash
git add ts/routes/pgrep/+layout.svelte
git commit -m "feat(pgrep): drive the title-bar inset from Qt's safe-area variable"
```

---

### Task 4: Fixed shell with a single scroll panel (Svelte)

Turn the shell into a fixed app frame so the rail and top stay put and only the content panel scrolls, ending the whole-window rubber-band. Retarget reset-to-top at the panel, and stop inner pages forcing a second scrollbar.

**Files:**

- Modify: `ts/routes/pgrep/+layout.svelte` (`.pgrep`/`.shell`/`.page` styles around lines 220-250; the `<main class="page">` markup around line 205; the reset `onMount` around lines 117-126)
- Modify: `ts/routes/pgrep/+page.svelte` (`.main` style, line 367)
- Modify: `ts/routes/pgrep/library/+page.svelte` (`.library-wheel` style, lines 185-186)

**Interfaces:**

- Consumes: nothing new. Produces no exported symbols; this is layout and scroll behavior.

- [ ] **Step 1: Make the shell a fixed frame and the panel the scroller**

In `ts/routes/pgrep/+layout.svelte`, replace:

```scss
    .pgrep {
        min-height: 100vh;
    }

    .shell {
        display: flex;
        min-height: 100vh;
        background: var(--canvas);
        color: var(--text);
    }
```

with:

```scss
    .pgrep {
        height: 100dvh;
        overflow: hidden;
    }

    .shell {
        display: flex;
        height: 100%;
        box-sizing: border-box;
        overflow: hidden;
        background: var(--canvas);
        color: var(--text);
    }
```

Then replace:

```scss
.page {
    flex: 1 1 auto;
    min-width: 0;
}
```

with:

```scss
.page {
    flex: 1 1 auto;
    min-width: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
}
```

- [ ] **Step 2: Bind the panel and retarget reset-to-top**

In the same file, add a ref alongside the other layout state (near `let showSplash = true;`):

```javascript
let pageEl: HTMLElement | undefined;
```

Bind it on the `<main>` element. Replace:

```svelte
<main class="page">
```

with:

```svelte
<main class="page" bind:this={pageEl}>
```

Then change the reset handler. Replace:

```javascript
if (first) {
    first = false;
    return;
}
window.scrollTo({ top: 0 });
```

with:

```javascript
if (first) {
    first = false;
    return;
}
pageEl?.scrollTo({ top: 0 });
```

- [ ] **Step 3: Stop the Home surface forcing a second scrollbar**

In `ts/routes/pgrep/+page.svelte`, in the `.main` rule (line 367), replace:

```scss
.main {
    min-height: 100vh;
```

with:

```scss
.main {
    min-height: 100%;
```

- [ ] **Step 4: Fit the library wheel to the panel**

In `ts/routes/pgrep/library/+page.svelte`, replace:

```scss
.library-wheel {
    display: flex;
    flex-direction: column;
    height: 100vh;
    height: 100dvh;
}
```

with:

```scss
.library-wheel {
    display: flex;
    flex-direction: column;
    height: 100%;
}
```

- [ ] **Step 5: Verify svelte/type/lint checks pass**

Run: `just lint`
Expected: PASS

- [ ] **Step 6: Manual verification on macOS**

Run: `just preview`.
Expected:

- Scrolling a long surface (Home, Progress) moves only the content panel; the rail and top edge stay fixed.
- No whole-window rubber-band. Study, the library wheel, and Home each fill the panel with no stray inner scrollbar.
- Also spot-check in a browser via `just dev` (no title bar) that scrolling and layout are unchanged there.

- [ ] **Step 7: Commit**

```bash
git add ts/routes/pgrep/+layout.svelte ts/routes/pgrep/+page.svelte ts/routes/pgrep/library/+page.svelte
git commit -m "feat(pgrep): fix the shell so only the content panel scrolls"
```

---

### Task 5: Full check and verification matrix

Run the repo gate and walk the acceptance matrix once, end to end.

**Files:**

- None (verification only)

- [ ] **Step 1: Run the full check**

Run: `just check`
Expected: format, lint, types, and unit tests all PASS across Python and Svelte.

- [ ] **Step 2: Acceptance matrix on macOS (`just preview`, exclusive)**

Confirm each:

- Window drags by the top band; traffic lights still click; double-click toggles maximize.
- Content and rail clear the traffic lights in both light and dark, rail expanded and collapsed.
- Only the content panel scrolls; no whole-window rubber-band.
- Resizing the window keeps the drag strip aligned and the inset correct.

- [ ] **Step 3: Regression spot-checks**

- `just dev` in a browser: no title-bar class, normal scrolling, no drag strip.
- Set `PGREP_SURFACE_MODE=hosted` and launch: stock Anki chrome, no drag strip, no inset variable, unchanged scrolling.

- [ ] **Step 4: Final commit if anything was adjusted**

```bash
git add -A
git commit -m "chore(pgrep): verify title-bar drag and scroll containment"
```

## Notes for the executor

- Do this work in a dedicated worktree and branch, for example `feat/titlebar-drag-and-scroll`, created via the `superpowers:using-git-worktrees` skill, then merge to `main` when green.
- If the transparent strip ever fails to receive presses over the web view on a given macOS version, the widget already falls back to a manual `move()`; if even that misbehaves, the next option is forcing the strip native (`WA_NativeWindow`) before raising it. Do not switch to a JS to Python drag bridge, which is racy.
