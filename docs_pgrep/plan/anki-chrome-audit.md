# Surviving Anki chrome (audit after exclusive de-Anki pass)

Date: 2026-07-15. Status: living checklist. Intentional About credit is allowed.

## Killed this pass (must not pop up in exclusive)

- First-run language picker skipped; `setlang.ui` / `main.ui` titles say pgrep
- Qt application name is pgrep (unless `PGREP_SURFACE_MODE=off`)
- CLI: Starting / version / --help say pgrep
- Rust DB lock: "pgrep already open..."
- Error Help no longer opens docs.ankiweb.net in product modes; Help button hidden
- Error / profile / mic / import copy no longer names Documents/Anki, AnkiWeb, or Anki as the app
- Profile `README.txt` no longer points at ankiweb docs
- Yellow Qt `tooltip()` panel (sync complete, export, undo, …) while the pgrep
  surface leads. Routed to the shell status line via `pgrep-status`
  (`pgrep_host.notify_status` / `utils.tooltip`). Help stub is silent.
- Native sync/export progress windows, full-sync conflict and mandatory
  direction dialogs, server messages, and sync/export/media error boxes on
  shipped paths. The shell operation center owns active progress, cancellation,
  terminal outcomes, and safe upload/download/cancel decisions. See
  [`in-app-sync-and-export-ui.md`](in-app-sync-and-export-ui.md).
- The global `Y` shortcut and automatic open/close sync use the same product
  operation UI. Product shutdown waits for media without opening Media Sync Log.

## Allowed (AGPL)

- Settings / About: "Built on Anki..." credit only

## Still deferred (packaging / migration cost)

These can still be _seen_ outside the SPA. Do not pretend they are gone.

| Artifact                       | Where                                                       | Why deferred                                                |
| ------------------------------ | ----------------------------------------------------------- | ----------------------------------------------------------- |
| On-disk folder `Anki2`         | `~/Library/Application Support/Anki2` (and platform peers)  | Renaming needs a migration path for existing collections    |
| Bundle id `net.ankiweb.pgrep*` | macOS Get Info, iOS project                                 | Ripples through installer + signing                         |
| Linux install.sh / MIME "Anki" | `qt/installer/linux-template/`                              | Linux ship path; mac beta first                             |
| Off-mode admin dialogs         | Preferences style "Anki", native sync fallback, Tools menus | Explicit developer hatch only; the pgrep SPA is not mounted |

## How to re-audit

```bash
just preview-fresh   # no language dialog, no Anki-titled chrome
rg -n 'setWindowTitle\("Anki"\)|>Anki</string>|Starting Anki|Documents/Anki|docs\.ankiweb\.net|help\.ankiweb\.net' \
  qt/aqt ftl/qt ftl/core rslib/src --glob '!**/ftl-repo/**'
# Floating yellow toast factory (should only draw when pgrep_web is hidden):
rg -n 'tooltip\(|#feffc4|WindowType\.ToolTip' qt/aqt
# Native operation chrome (remaining calls must be inside off-mode fallback):
rg -n 'with_progress|ask_user_dialog|show_warning|showWarning|show_info|showText' \
  qt/aqt/sync.py qt/aqt/pgrep.py qt/aqt/mediasync.py
```
