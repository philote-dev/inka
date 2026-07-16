# L6 structural de-Anki Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking. Spec: `structural-de-anki-design.md` (same folder).

**Goal:** Make the exclusive (product) surface show only pgrep's own chrome. Build pgrep's own
menus, never Anki's; make the profile chooser unreachable; give macOS a unified transparent title
bar; and document the hosting path.

**Architecture:** Keep all decisions in `qt/aqt/pgrep_host.py` as small pure helpers, called from
the thin host (`qt/aqt/main.py`). Menu construction forks on surface mode. The macOS window chrome
reuses Anki's native Swift helper pattern (`qt/mac/theme.swift`). No changes under `rslib/src/sync`.

**Tech Stack:** Python + PyQt6 (Qt host), Svelte/SCSS (web rail safe-area), Swift/AppKit (macOS
helper), pytest.

---

## File structure

- `qt/aqt/pgrep_host.py` (modify): add pure policy helpers (`suppress_profile_chooser`,
  `exclusive_menu_titles`), retire `apply_menu_chrome`'s hiding role.
- `qt/aqt/main.py` (modify): fork `setupMenus`, add `_setup_exclusive_menubar`, guard
  `showProfileManager` and `unloadProfileAndShowProfileManager`, call the title-bar helper.
- `qt/mac/theme.swift` (modify): add `@_cdecl` `set_titlebar_transparent`.
- `qt/mac/anki_mac_helper/__init__.py` (modify): add the Python wrapper.
- Build wiring for the local helper (see Wave 2).
- `ts/routes/pgrep/pgrep.scss` or `ts/routes/pgrep/+layout.svelte` (modify): rail top safe-area
  under a `pgrep-native-titlebar` body class.
- `qt/tests/test_pgrep_shell.py` (create): unit tests for the pure helpers.
- `docs_pgrep/plan/hosting-roadmap.md` (create): WI4 doc.
- `docs_pgrep/plan/deferred-todos.md` and `build-plan.md` (modify): record deferred items + L6.

---

## Wave 1: exclusive menu bar (WI1) + profile collapse (WI2)

### Task 1: pure policy helpers in `pgrep_host.py`

**Files:** Modify `qt/aqt/pgrep_host.py`; Test `qt/tests/test_pgrep_shell.py`.

- [ ] **Step 1: Write failing tests.**

```python
# qt/tests/test_pgrep_shell.py
from aqt.pgrep_host import suppress_profile_chooser, exclusive_menu_titles


def test_chooser_suppressed_only_in_exclusive():
    assert suppress_profile_chooser("exclusive") is True
    assert suppress_profile_chooser("hosted") is False
    assert suppress_profile_chooser("off") is False


def test_exclusive_menus_have_no_anki_admin_menus():
    titles = exclusive_menu_titles()
    assert "Go" in titles
    assert "Edit" in titles
    # no Anki admin menus reach the product
    for banned in ("File", "Tools", "Help", "View"):
        assert banned not in titles
```

- [ ] **Step 2: Run, expect failure** (`ImportError`).

Run: `cd .worktrees/l6-structural-de-anki && PYTHONPATH=out/pylib:qt out/pyenv/bin/pytest qt/tests/test_pgrep_shell.py -q`

- [ ] **Step 3: Implement helpers.**

```python
def suppress_profile_chooser(mode: str) -> bool:
    """True when Anki's profile chooser must never surface (the product)."""
    return mode == "exclusive"


def exclusive_menu_titles() -> tuple[str, ...]:
    """The only top-level menus the product builds. Edit for text fields, Go for the rail.

    The macOS app menu (About/Settings/Quit) is added via Qt menu roles, not listed here.
    """
    return ("Edit", "Go")
```

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** (`git add -A && git commit -m "feat(pgrep): pure shell policy helpers"`).

### Task 2: fork `setupMenus` and build the exclusive menu bar

**Files:** Modify `qt/aqt/main.py` (`setupMenus` ~1472, add `_setup_exclusive_menubar`).

- [ ] **Step 1: Fork at the top of `setupMenus`.** Before the existing `m = self.form` wiring:

```python
def setupMenus(self) -> None:
    from aqt import pgrep_host

    if pgrep_host.surface_mode(self) == "exclusive":
        self._setup_exclusive_menubar()
        return
    m = self.form
    # ... existing Anki wiring unchanged (hosted/off) ...
```

- [ ] **Step 2: Add `_setup_exclusive_menubar`.** It clears the `.ui` menubar and builds only
      Edit + Go, plus role actions Qt relocates to the macOS app menu. On Windows/Linux the menubar is
      hidden and the Edit actions are added to the window so their shortcuts still fire.

```python
def _setup_exclusive_menubar(self) -> None:
    """Build pgrep's own minimal menu bar; never build Anki's admin menus.

    Approach C from the structural de-Anki spec. Anki's actions are not created, so no
    menu or keyboard route into them exists in the product.
    """
    from aqt.qt import QAction, QKeySequence, Qt

    bar = self.form.menubar
    bar.clear()

    # Edit: collection undo/redo plus standard clipboard for text fields.
    edit = bar.addMenu(tr.qt_accel_edit())
    undo = edit.addAction(tr.undo_undo())
    undo.setShortcut(QKeySequence.StandardKey.Undo)
    qconnect(undo.triggered, self.undo)
    redo = edit.addAction(tr.undo_redo())
    redo.setShortcut(QKeySequence.StandardKey.Redo)
    qconnect(redo.triggered, self.redo)
    edit.addSeparator()
    for role_key, std in (
        ("Cut", QKeySequence.StandardKey.Cut),
        ("Copy", QKeySequence.StandardKey.Copy),
        ("Paste", QKeySequence.StandardKey.Paste),
        ("Select All", QKeySequence.StandardKey.SelectAll),
    ):
        act = edit.addAction(role_key)
        act.setShortcut(std)
        qconnect(
            act.triggered,
            lambda _c=False, s=std: self._exclusive_edit_action(s),
        )

    # Go: rail destinations, full screen, zoom.
    go = bar.addMenu("&Go")
    for label, route, sc in (
        ("&Home", "pgrep", "Ctrl+1"),
        ("&Study", "pgrep/study", "Ctrl+2"),
        ("&Progress", "pgrep/progress", "Ctrl+3"),
        ("&Library", "pgrep/library", "Ctrl+4"),
    ):
        a = go.addAction(label)
        a.setShortcut(QKeySequence(sc))
        a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        qconnect(a.triggered, lambda _c=False, r=route: self.pgrep_navigate(r))
    go.addSeparator()
    full = go.addAction(tr.qt_accel_fullscreen() if hasattr(tr, "qt_accel_fullscreen") else "Full Screen")
    full.setShortcut(QKeySequence("F11") if is_lin else QKeySequence.StandardKey.FullScreen)
    full.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    qconnect(full.triggered, self.on_toggle_full_screen)
    for label, delta in (("Zoom In", 0.1), ("Zoom Out", -0.1)):
        z = go.addAction(label)
        qconnect(z.triggered, lambda _c=False, d=delta: self.web.setZoomFactor(self.web.zoomFactor() + d))
    zr = go.addAction("Actual Size")
    qconnect(zr.triggered, lambda: self.web.setZoomFactor(1))

    # App-menu role actions (macOS relocates these): About, Settings, Quit.
    about = QAction("About pgrep", self)
    about.setMenuRole(QAction.MenuRole.AboutRole)
    qconnect(about.triggered, self.onAbout)
    settings = QAction("Settings…", self)
    settings.setMenuRole(QAction.MenuRole.PreferencesRole)
    settings.setShortcut(QKeySequence(QKeySequence.StandardKey.Preferences))
    qconnect(settings.triggered, lambda: self.pgrep_navigate("pgrep/settings"))
    quit_action = QAction("Quit pgrep", self)
    quit_action.setMenuRole(QAction.MenuRole.QuitRole)
    quit_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Quit))
    qconnect(quit_action.triggered, self.close)
    self.addActions([about, settings, quit_action])

    # Windows/Linux: the rail is the nav, so hide the in-window menu bar but keep shortcuts
    # alive by owning the actions on the window.
    if not is_mac:
        self.addActions(edit.actions())
        self.addActions(go.actions())
        bar.setVisible(False)
```

- [ ] **Step 3: Add the clipboard relay** `_exclusive_edit_action` (routes standard edit keys to
      the focused widget, which is the webview in practice):

```python
def _exclusive_edit_action(self, std) -> None:
    from aqt.qt import QApplication, QKeyEvent
    w = QApplication.focusWidget()
    if w is not None:
        # Let the focused widget (the webview) handle the standard edit role.
        seq = QKeySequence(std)
        if seq.count():
            key = seq[0]
            QApplication.postEvent(w, QKeyEvent(QKeyEvent.Type.KeyPress, key.key(), key.keyboardModifiers()))
```

- [ ] **Step 4: Manual verify (macOS).** Launch exclusive (`just run`), confirm the menu bar shows
      only the app menu, Edit, and Go; File/View/Tools/Help are gone; Cmd+1..4 navigate; Cmd+, opens
      Settings; Undo/Redo present. Launch `PGREP_SURFACE_MODE=hosted just run` and confirm the full Anki
      menus return (dev hatch intact).

Run: `cd .worktrees/l6-structural-de-anki && just run`

- [ ] **Step 5: Commit** (`git commit -m "feat(pgrep): build pgrep's own exclusive menu bar (Approach C)"`).

### Task 3: guard the profile chooser (WI2)

**Files:** Modify `qt/aqt/main.py` (`showProfileManager` ~341, `unloadProfileAndShowProfileManager` ~616).

- [ ] **Step 1: Guard `showProfileManager`** at the very top:

```python
def showProfileManager(self) -> None:
    from aqt import pgrep_host

    if pgrep_host.suppress_profile_chooser(pgrep_host.surface_mode(self)):
        # The product never shows Anki's chooser. Auto-open the implicit profile,
        # creating one if the base folder is empty.
        profs = self.pm.profiles()
        if not profs:
            self.pm.create(self.pm.DEFAULT_PROFILE_NAME if hasattr(self.pm, "DEFAULT_PROFILE_NAME") else "User 1")
            profs = self.pm.profiles()
        auto = pgrep_host.profile_to_autoload(
            "exclusive", profs, self.pm.last_loaded_profile_name()
        )
        if auto is not None:
            self.pm.load(auto)
            self.loadProfile()
            return
        # Unrecoverable: fail plainly rather than exposing Anki's manager.
        showWarning("pgrep could not open your data. Please restart.")
        self.cleanupAndExit()
        return
    self.pm.profile = None
    # ... existing chooser code unchanged ...
```

- [ ] **Step 2: Make `unloadProfileAndShowProfileManager` inert in exclusive:**

```python
def unloadProfileAndShowProfileManager(self) -> None:
    from aqt import pgrep_host

    if pgrep_host.suppress_profile_chooser(pgrep_host.surface_mode(self)):
        return
    # ... existing unchanged ...
```

- [ ] **Step 3: Verify `pm.create` / DEFAULT name.** Read `qt/aqt/profiles.py` to confirm the
      create API and default profile name; adjust Step 1 to the real signature.

- [ ] **Step 4: Manual verify.** In exclusive, rename the profile folder to simulate a missing
      profile and confirm pgrep auto-creates/opens rather than showing the chooser. Confirm hosted still
      shows the chooser when multiple profiles exist.

- [ ] **Step 5: Commit** (`git commit -m "feat(pgrep): never surface Anki's profile chooser in the product"`).

---

## Wave 2: macOS transparent title bar (WI5)

### Task 4: native Swift helper + wrapper

**Files:** Modify `qt/mac/theme.swift`, `qt/mac/anki_mac_helper/__init__.py`.

- [ ] **Step 1: Add the Swift function** to `qt/mac/theme.swift`:

```swift
/// Make the given NSView's window use a transparent, unified title bar.
@_cdecl("set_titlebar_transparent")
public func setTitlebarTransparent(_ viewPtr: UnsafeMutableRawPointer) {
    let view = Unmanaged<NSView>.fromOpaque(viewPtr).takeUnretainedValue()
    guard let window = view.window else { return }
    window.titlebarAppearsTransparent = true
    window.titleVisibility = .hidden
    window.styleMask.insert(.fullSizeContentView)
}
```

- [ ] **Step 2: Add the wrapper** in `qt/mac/anki_mac_helper/__init__.py`:

```python
from ctypes import c_void_p
# in _MacOSHelper.__init__: self._dll.set_titlebar_transparent.argtypes = [c_void_p]

def set_titlebar_transparent(self, view_ptr: int) -> None:
    self._dll.set_titlebar_transparent(view_ptr)
```

### Task 5: build wiring so the app uses the local helper

**Files:** build system (investigate first).

- [ ] **Step 1: Investigate** how `anki_mac_helper` is installed into `out/pyenv` (the 0.1.1
      wheel). Find where the wheel install happens in the build.

Run: `rg -n "anki_mac_helper|anki-mac-helper" build/ tools/ *.py pyproject.toml 2>/dev/null`

- [ ] **Step 2: Choose the least-divergent wiring** (leading candidate: build `libankihelper.dylib`
      from `qt/mac` via `xcodebuild`/`swiftc` and overlay it plus the updated `__init__.py` onto the
      installed `anki_mac_helper` in `out/pyenv` as a post-install step). Fallback: a pgrep-owned
      separate dylib target and loader module. Document the chosen approach inline here before coding.

- [ ] **Step 3: Implement the build step**, then rebuild and confirm the new symbol loads
      (`out/pyenv/bin/python -c "from anki_mac_helper import macos_helper; print(macos_helper.set_titlebar_transparent)"`).

### Task 6: call it and add the web safe-area

**Files:** Modify `qt/aqt/main.py`, `ts/routes/pgrep/pgrep.scss` (or `+layout.svelte`).

- [ ] **Step 1: Call the helper** after the main window shows, in exclusive + macOS only, and tag
      the webview:

```python
# after the window is shown and pgrep leads, in exclusive mode on macOS:
from aqt import pgrep_host
if is_mac and pgrep_host.surface_mode(self) == "exclusive":
    from aqt._macos_helper import macos_helper
    if macos_helper is not None:
        macos_helper.set_titlebar_transparent(int(self.winId()))
    if self.pgrep_web is not None:
        self.pgrep_web.eval("document.body.classList.add('pgrep-native-titlebar')")
```

- [ ] **Step 2: Add the rail safe-area** so the traffic lights do not overlap:

```scss
:global(body.pgrep-native-titlebar) .shell {
    padding-top: 28px; /* clears the traffic-light strip */
}
```

- [ ] **Step 3: Manual verify (macOS, exclusive).** Traffic lights float over the content, no
      separate title strip, rail top clears the lights, window still drags and full-screens. Confirm
      iOS and hosted are unchanged (class not applied).

- [ ] **Step 4: Commit** (`git commit -m "feat(pgrep): unified transparent macOS title bar in the product"`).

---

## Wave 3: hosting roadmap doc (WI4)

### Task 7: write `hosting-roadmap.md`

**Files:** Create `docs_pgrep/plan/hosting-roadmap.md`.

- [ ] **Step 1: Write Part 1 (self-host on the Mac).** Cover: what `just sync-server` runs
      (`tools/sync-server.py`, built-in server, `pgrep:pgrep`, HTTP, `0.0.0.0:8090`); a launchd
      LaunchAgent plist to keep it alive across reboots; the sync data location and a backup approach;
      LAN reach (`your-mac-ip:8090`) vs internet reach (Tailscale or Cloudflare Tunnel + TLS); security
      caveats and limits.
- [ ] **Step 2: Write Part 2 (cloud, delegated).** VPS (Hetzner/Fly.io) + `anki-sync-server-enhanced`
  - Caddy + R2, auth phased CLI to Firebase, trade-offs and rough costs. Mark the final pick
    delegated. Defer the web app.
- [ ] **Step 3: Commit** (`git commit -m "docs(pgrep): L6 hosting roadmap (local-first, cloud later)"`).

---

## Wave 4: wrap-up

### Task 8: defaults guard test + bookkeeping + green

- [ ] **Step 1: Add a guard test** that no pgrep surface lists the stock defaults. Prefer a
      backend-level assertion (card sets never include `Default`/`Cloze`), since the web is not unit
      tested here:

```python
# pylib/tests/test_pgrep_card_sets_no_stock_defaults.py
from anki.pgrep import card_sets
def test_card_sets_never_expose_stock_defaults(pgrep_col):
    sets = card_sets.list_card_sets(pgrep_col)
    names = {s["name"] for s in sets}
    assert "Default" not in names and "Cloze" not in names
```

(Use the existing pgrep test fixture; check `pylib/tests` for the collection fixture name.)

- [ ] **Step 2: Record deferred items** in `docs_pgrep/plan/deferred-todos.md` (WI3 login gate,
      pgrep's own note type, WI5 build fallback; WI3's page artifacts were since built for the beta,
      see `login-gate-beta-handoff.md`) and update `build-plan.md` L6 to note the structural
      de-Anki sweep is in progress here.
- [ ] **Step 3: Run `just check`** in the worktree; fix any lint/type/test failures. Expected: green
      except the known pre-existing `test_installer` worktree flake.
- [ ] **Step 4: Leave uncommitted or commit per the user's call** (git rules: parked by default).

---

## Self-review

- **Spec coverage:** WI1 (Tasks 1-2), WI2 (Tasks 1,3), WI5 (Tasks 4-6), WI4 (Task 7), testing +
  bookkeeping (Tasks 1,8). All spec sections map to a task.
- **Placeholders:** Native/build steps (Task 5) are investigation-first by nature; the approach is
  named with a concrete leading candidate and a fallback, not left blank.
- **Consistency:** `suppress_profile_chooser` and `exclusive_menu_titles` are defined in Task 1 and
  used in Tasks 2-3. `pgrep_navigate`, `on_toggle_full_screen`, `onAbout` already exist in `main.py`.
- **Risk:** Task 5 (helper build wiring) is the main unknown; it is isolated to Wave 2 and has a
  documented fallback, so Waves 1, 3, 4 do not depend on it.
