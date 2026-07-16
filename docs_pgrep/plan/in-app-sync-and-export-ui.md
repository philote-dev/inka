# In-App Sync and Export UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans` to
> implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Replace every native Qt progress, decision, completion, and error
surface reached by pgrep sync or export with one shell-level in-app operation
UI.

**Architecture:** Keep Anki's proven sync engine and full-sync mechanics, but
separate them from presentation through a `SyncUi` protocol. The pgrep
implementation writes revisioned operation state to a thread-safe coordinator;
the Svelte shell reads that state through the existing JSON bridge and renders
progress, errors, and full-sync decisions. The native implementation remains
only for the explicit `PGREP_SURFACE_MODE=off` developer hatch.

**Tech stack:** Python 3, Qt task manager, Svelte 5 in legacy syntax, SvelteKit
client rendering, Fluent strings already exposed through Python, pytest,
Vitest, and the existing `/pgrep-lab` review surface.

## Global constraints

- All shipped pgrep paths use the in-app UI, including Settings, first-run
  sign-in, the `Y` shortcut, auto-sync, shutdown media sync, and export.
- `PGREP_SURFACE_MODE=off` keeps upstream native dialogs because the pgrep SPA
  is not mounted.
- Sync mechanics, collection close/reopen ordering, backups, media sync, auth
  clearing, and full-sync safety choices must not change.
- The UI never renders server-provided text as HTML.
- A destructive upload or download decision is never selected implicitly.
  Escape and backdrop dismissal mean Cancel.
- Browser-first `just dev` must receive state through the bridge. Webview
  `CustomEvent` delivery is only an immediate wake-up optimization.
- No new runtime dependency.
- Use existing pgrep tokens and Inter typography. Score colors remain reserved
  for Memory, Performance, and Readiness.

---

## File structure

- Create `qt/aqt/pgrep_operation.py`: thread-safe operation state, revisions,
  pending decision callback, cancel callback, serialization, and webview wake-up.
- Modify `qt/aqt/sync.py`: presentation-neutral sync flow plus native
  `SyncUi` fallback.
- Modify `qt/aqt/pgrep.py`: product sync/export entry points and operation
  bridge handlers.
- Modify `qt/aqt/main.py`: route manual and automatic product sync through the
  pgrep UI and remove the native media-log shortcut path.
- Modify `qt/aqt/mediasync.py`: report product media progress/errors and wait
  silently during product shutdown.
- Create `ts/lib/components/OperationCenter.svelte`: pure operation UI for
  active, success, error, and decision states.
- Create `ts/routes/pgrep/lib/operation.ts`: bridge contract, reducer, polling,
  resolve/cancel/dismiss helpers.
- Modify `ts/routes/pgrep/+layout.svelte`: mount one operation center for every
  route and retire the ad hoc sync status implementation.
- Modify `ts/routes/pgrep/settings/+page.svelte`: bind Sync and Export rows to
  operation state instead of string matching.
- Create `ts/routes/pgrep-lab/operation-ui/+page.svelte` and modify
  `ts/routes/pgrep-lab/LabNav.svelte`: durable light/dark review fixtures.
- Test in `qt/tests/test_pgrep_operation.py`,
  `qt/tests/test_pgrep_sync_ui.py`, `qt/tests/test_pgrep_bridge.py`, and
  `ts/routes/pgrep/lib/operation.test.ts`.

---

### Task 1: Revisioned operation coordinator

**Interfaces**

- Produces `OperationController.begin()`, `update()`, `request_decision()`,
  `resolve()`, `cancel()`, `dismiss()`, and `snapshot()`.
- Serialized state:

```python
{
    "revision": int,
    "operation_id": int | None,
    "kind": "idle" | "sync" | "export" | "message",
    "phase": "idle" | "active" | "decision" | "success" | "error",
    "message": str,
    "detail": str | None,
    "progress": float | None,
    "cancellable": bool,
    "decision": {
        "title": str,
        "body": str,
        "choices": [{"id": str, "label": str, "destructive": bool}],
    } | None,
    "dismiss_after_ms": int | None,
}
```

- [x] **Step 1: Write failing coordinator tests.**

```python
def test_stale_update_cannot_overwrite_new_operation():
    controller = OperationController()
    first = controller.begin("sync", "Checking")
    second = controller.begin("export", "Exporting")
    assert controller.update(first, message="stale") is False
    assert controller.snapshot()["operation_id"] == second


def test_decision_resolves_once_and_clears_prompt():
    choices: list[str] = []
    controller = OperationController()
    operation_id = controller.begin("sync", "Checking")
    controller.request_decision(
        operation_id,
        title="Choose which copy to keep",
        body="The copies cannot be merged.",
        choices=[{"id": "cancel", "label": "Cancel", "destructive": False}],
        resolver=choices.append,
    )
    assert controller.resolve(operation_id, "cancel") is True
    assert controller.resolve(operation_id, "cancel") is False
    assert choices == ["cancel"]
```

- [x] **Step 2: Run the focused test and confirm RED.**

Run:

```bash
out/pyenv/bin/python -m pytest qt/tests/test_pgrep_operation.py -q
```

Expected: import failure because `aqt.pgrep_operation` does not exist.

- [x] **Step 3: Implement the controller with a `threading.RLock`.**

Callbacks are removed under the lock and invoked after releasing it. Every
accepted mutation increments `revision`. Invalid operation IDs and choice IDs
return `False` without changing state.

- [x] **Step 4: Run the focused test and confirm GREEN.**

---

### Task 2: Presentation-neutral sync flow

**Interfaces**

Add to `qt/aqt/sync.py`:

```python
class SyncUi(Protocol):
    def run_task(
        self,
        task: Callable[[], Any],
        on_done: Callable[[Future], None],
        *,
        message: str,
    ) -> None: ...

    def update(
        self, message: str, *, progress: float | None = None
    ) -> None: ...

    def request_decision(
        self,
        *,
        title: str,
        body: str,
        choices: list[SyncChoice],
        callback: Callable[[str], None],
    ) -> None: ...

    def error(self, err: Exception) -> None: ...
    def complete(self, message: str) -> None: ...
    def server_message(self, message: str) -> None: ...


def sync_collection(
    mw: aqt.main.AnkiQt,
    on_done: Callable[[], None],
    *,
    ui: SyncUi | None = None,
) -> None:
    ...
```

`None` selects `NativeSyncUi`, which preserves existing off-mode behavior.

- [x] **Step 1: Write failing tests with fake task managers and UIs.**

Cover:

1. Product `run_task` uses `taskman.run_in_background`, never
   `with_progress`.
2. `FULL_DOWNLOAD` offers only Download and Cancel.
3. `FULL_UPLOAD` offers only Upload and Cancel.
4. `FULL_SYNC` offers Upload, Download, and Cancel.
5. Error calls `ui.error`, clears auth on authentication errors, and calls
   `on_done` once.
6. Full upload/download progress reaches `ui.update`.
7. Native `ui=None` still calls the existing Qt progress/dialog path.

- [x] **Step 2: Run `qt/tests/test_pgrep_sync_ui.py` and confirm RED.**

- [x] **Step 3: Implement `SyncUi`, `SyncChoice`, and `NativeSyncUi`.**

Move dialog and progress calls into `NativeSyncUi`; keep the sync control flow
in module-level functions. Pass `ui` through `full_sync()`,
`confirm_full_download()`, `confirm_full_upload()`, `full_download()`, and
`full_upload()`.

- [x] **Step 4: Make product tasks non-modal.**

The product adapter in `pgrep_operation.py` calls
`mw.taskman.run_in_background(...)`, reports normal and full-sync progress, and
stores decisions in `OperationController`.

- [x] **Step 5: Run focused tests and confirm GREEN.**

---

### Task 3: Bridge operations and product entry points

**Interfaces**

Add handlers:

```python
def pgrep_operation_status() -> bytes: ...
def pgrep_operation_resolve() -> bytes: ...
def pgrep_operation_cancel() -> bytes: ...
def pgrep_operation_dismiss() -> bytes: ...
```

`pgrep_sync()` and successful `pgrep_sign_in()` return
`{"status": "started", "operation_id": int}`. Resolve, cancel, and dismiss
require that operation ID so stale pages cannot affect newer work.

- [x] **Step 1: Extend bridge registration and behavior tests first.**

Test endpoint registration, snapshot serialization, stale resolve rejection,
valid conflict resolution, cancel calling `col.abort_sync()`, and dismiss only
clearing terminal operations.

- [x] **Step 2: Run the focused bridge tests and confirm RED.**

- [x] **Step 3: Route `pgrep_sync` and `pgrep_sign_in` through
      `ProductSyncUi`.**

Replace login `with_progress()` with a background task that publishes
"Signing in" and reports failure in-app. Preserve login-gate inline credential
errors before a sync operation begins.

- [x] **Step 4: Replace export progress and errors.**

Start an `export` operation, run `QueryOp` without `.with_progress()`, publish
success with the path, and publish failure without `showWarning()`.

- [x] **Step 5: Run bridge tests and confirm GREEN.**

---

### Task 4: Automatic sync, shortcuts, and media phase

- [x] **Step 1: Write failing tests for product routing.**

Assert:

- `_sync_collection_and_media()` selects `ProductSyncUi` whenever
  `pgrep_host.leads_with_pgrep()` is true.
- `Y` never opens `sync_login()` or `MediaSyncDialog` in product mode.
- Product shutdown waits for media without calling
  `aqt.dialogs.open("sync_log", ...)`.
- Product media errors publish an operation error and never call `show_info()`.

- [x] **Step 2: Run focused tests and confirm RED.**

- [x] **Step 3: Update `main.py`.**

Product `Y` starts sync through the saved auth. If no auth exists, navigate to
`pgrep/login`. Automatic open/close sync uses the same product adapter. Off
mode keeps the existing toolbar and native login behavior.

- [x] **Step 4: Update `mediasync.py`.**

When product mode leads:

- starting and counts update the active sync operation;
- completion marks the whole sync successful;
- non-periodic failure marks it failed;
- shutdown uses a timer-only wait, not `MediaSyncDialog`.

- [x] **Step 5: Run focused tests and confirm GREEN.**

---

### Task 5: Svelte operation model and shell UI

**Interfaces**

`ts/routes/pgrep/lib/operation.ts` exports:

```typescript
export type OperationPhase =
    | "idle"
    | "active"
    | "decision"
    | "success"
    | "error";

export interface OperationSnapshot {
    revision: number;
    operation_id: number | null;
    kind: "idle" | "sync" | "export" | "message";
    phase: OperationPhase;
    message: string;
    detail: string | null;
    progress: number | null;
    cancellable: boolean;
    decision: OperationDecision | null;
    dismiss_after_ms: number | null;
}

export function acceptNewer(
    current: OperationSnapshot,
    incoming: OperationSnapshot,
): OperationSnapshot;
```

- [x] **Step 1: Write reducer tests first.**

Cover revision ordering, stale-state rejection, progress clamping, and
terminal-state preservation.

- [x] **Step 2: Run the Vitest file and confirm RED.**

- [x] **Step 3: Implement polling in the pgrep layout.**

Poll every 250 ms while active/decision and every 1.5 seconds while idle or
terminal. A `pgrep-operation-changed` webview event triggers an immediate
refresh. Cleanup is synchronously returned from `onMount`.

- [x] **Step 4: Build `OperationCenter.svelte`.**

Render:

- active: compact shell panel, message, determinate or indeterminate hairline,
  and Cancel when supported;
- success: polite `role="status"` and automatic dismiss;
- error: persistent `role="alert"` with detail and Dismiss;
- decision: `role="dialog"`, `aria-modal="true"`, plain-text body, explicit
  choices, safe initial focus, and Escape mapped to Cancel.

Use `--surface`, `--border`, `--text`, `--muted`, and `--error`. Do not use
Memory, Performance, or Readiness colors.

- [x] **Step 5: Replace Settings string matching.**

Sync and Export rows derive their disabled state and message from
`operation_id`, `kind`, and `phase`, never from `message.includes(...)`.

- [x] **Step 6: Run Svelte and TypeScript checks and confirm GREEN.**

---

### Task 6: Durable visual fixture and final chrome sweep

- [x] **Step 1: Add `/pgrep-lab/operation-ui`.**

Show active indeterminate sync, 62% full download, export success, sync error,
mandatory download, mandatory upload, and three-way conflict in light and dark.
Use the real `OperationCenter` with synthetic props and no backend calls.

- [x] **Step 2: Register the fixture in `LabNav.svelte`.**

Label it "Operation UI" with the blurb "Sync and export progress, decisions,
and failures without native dialogs."

- [x] **Step 3: Update the chrome audit.**

Move modal sync/export progress and full-sync/error mboxes from deferred to
killed. Record that only explicit off mode retains native fallback UI.

- [x] **Step 4: Run the reachability searches.**

```bash
rg -n 'with_progress|ask_user_dialog|show_warning|showWarning|show_info|showText' \
  qt/aqt/sync.py qt/aqt/pgrep.py qt/aqt/mediasync.py
```

Remaining calls are inside `NativeSyncUi`, native `sync_login` /
`handle_sync_error`, or the non-product branch of media error reporting.

- [x] **Step 5: Run verification.**

```bash
just test-py
just test-ts
just lint
just check
```

Important review fixes landed with this task: cancel/`Interrupted` are a
terminal `cancelled` phase; `try_begin` rejects concurrent starts; media
updates bind to `operation_id`; product unload keeps the window enabled for
in-app decisions; orphan media failures stay in-app; decision focus stays
trapped while resolving; Settings disables Sync/Export immediately on click.

Manual product check:

1. Settings > Sync now never opens a Qt window.
2. Active, success, and failure stay inside the pgrep shell.
3. A full-sync requirement opens the in-app decision dialog.
4. Escape cancels a decision and does not upload or download.
5. Export never opens a Qt progress or error window.
6. `PGREP_SURFACE_MODE=off` still uses upstream native sync UI.

`just check` may still fail on the pre-existing
`content_invariants.py::check_bundle` complexipy gate vs `main`; that is
unrelated to this sync UI work.

### Status: presentation plumbing complete

In-app progress, decisions, errors, cancel, busy rejection, media binding,
shutdown window enablement, copy tightening, and lab fixtures are landed on
`feat/login-gate-beta`. Engine behavior is unchanged: normal multi-device study
merges without asking; only empty-side setup and true history divergence ask.

### Next (UI pass — mental model)

**Slice 1 (landed in `b224b7cd2`):** Settings group “Devices”; Sync row
explains same collection + last-synced; URL demoted to “Account URL”; success
reads “Up to date”; full-sync copy uses account/device language; login gate
matches.

**Slice 2 (landed in `97c5e184d`):** Sync row labeled “This computer”; first
successful sync teaches that computer and phone share one collection;
remaining user-facing “server” copy → “account”.

Still open: iOS “This phone” label when the companion Settings lands; any
chrome that still says “server” outside the product surfaces.

See also [`reference/sync-conflict-rule.md`](../reference/sync-conflict-rule.md).

---

## Plan self-review

- **Coverage:** manual sync, sign-in sync, automatic sync, shutdown media,
  export, progress, success, conflict, mandatory direction, cancellation,
  errors, browser dev, and off-mode fallback each have an implementation task
  and a test seam.
- **Safety:** decisions are operation-ID scoped, stale updates are rejected,
  callbacks resolve once, and Cancel is the keyboard/default path.
- **Type consistency:** Python and TypeScript snapshots use the same field names
  and literal values.
- **No placeholders:** all files, interfaces, commands, and expected behaviors
  are specified.
