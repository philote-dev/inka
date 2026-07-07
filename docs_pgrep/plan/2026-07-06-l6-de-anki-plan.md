# L6 de-Anki sweep, implementation plan

> **For agentic workers:** Implement task by task. Steps use checkbox (`- [ ]`) syntax.
> Each task touches a distinct set of files so tasks 1 to 4 can run in parallel. Do not
> run builds or `git`; the controller runs `just check` once, serially, after the parallel
> edits land (shared-build rule, build-plan.md section 3).

**Goal:** Remove every user-facing "Anki" and "AnkiWeb" from the shipped pgrep surface,
keep the Anki credit in an About and licenses surface only, and correct the stale L6 plan.

**Architecture:** A reachability-first rebrand. The About dialog is rebuilt from a pure,
testable helper. Sync and error strings are edited in place in `ftl/` (values only, keys
unchanged, so no API regen). A Settings row surfaces the credit cross-platform. Guard
tests lock the wording so it cannot silently regress.

**Tech Stack:** Python (Qt About dialog), Fluent `.ftl` strings, Svelte (Settings), pytest.

**Spec:** `docs_pgrep/plan/2026-07-06-l6-production-de-anki-design.md` (on `main`).

**Constraints (hard):** No em-dashes, short labels, calm voice. Keep the Anki credit in the
About and licenses surface only. Do not change `.ftl` keys, only their English values. Do
not touch `rslib/src/sync`. No new dependencies. Do not rename internal code or per-file
headers.

---

### Task 1: pgrep About dialog and licenses (Qt + Settings)

**Files:**

- Create: `qt/aqt/pgrep_about.py` (a Qt-free, testable HTML builder)
- Modify: `qt/aqt/about.py:66-83` (use the builder, drop the Anki logo and marketing lede)
- Create: `qt/tests/test_pgrep_about.py`
- Modify: `ts/routes/pgrep/settings/+page.svelte` (add an "About and licenses" row)

The current `about.py` leads with the Anki logo (`about.py:68`), the "Anki is a friendly,
intelligent..." lede (`about.py:69`), and the Anki website (`about.py:80-83`). The AGPL
license line (`about.py:71`, `tr.about_anki_is_licensed_under_the_agpl3`) and the
contributor list are the Anki credit and are kept, reframed under a credit heading.

- [ ] **Step 1: Write the failing test** `qt/tests/test_pgrep_about.py`

```python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from aqt.pgrep_about import about_html


def _html() -> str:
    return about_html(
        license_line="Anki is licensed under the AGPL3 license.",
        version_line="Version 26.05",
        seam_line="pgrep: ok",
        env_line="Python 3.13 Qt 6 Chromium 130",
        contributors_html="Damien Elmes, and others",
    )


def test_about_leads_with_pgrep():
    html = _html()
    assert "pgrep" in html
    # pgrep leads, the Anki marketing logo and lede are gone
    assert "anki-logo-thin.png" not in html
    assert "friendly, intelligent" not in html


def test_about_keeps_the_anki_credit():
    html = _html()
    # the AGPL credit that names Anki stays, this is the licenses part
    assert "AGPL" in html
    assert "Anki" in html
    assert "Ankitects" in html
```

- [ ] **Step 2: Create `qt/aqt/pgrep_about.py`**

```python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""pgrep About dialog content (Qt-free so it is unit testable).

The dialog leads with the pgrep identity. The Anki attribution stays here, in the
licenses and credits block, to satisfy the AGPL credit requirement in one place.
"""

from __future__ import annotations


def about_html(
    *,
    license_line: str,
    version_line: str,
    seam_line: str | None,
    env_line: str,
    contributors_html: str,
) -> str:
    """Return the About dialog body as HTML.

    All dynamic values are passed in so this function needs no Qt or collection.
    """
    parts: list[str] = []
    parts.append("<center><h1 style='letter-spacing:0.05em'>pgrep</h1></center>")
    parts.append(
        "<p>pgrep is a focused study app for the Physics GRE. "
        "It runs on your own devices and syncs to a server you control."
    )
    parts.append(f"<p>{version_line}<br>")
    if seam_line:
        parts.append(f"{seam_line}<br>")
    parts.append(f"{env_line}")
    parts.append("<hr>")
    parts.append("<p><b>Built on Anki</b>")
    parts.append(
        "<p>pgrep is built on Anki, created by Ankitects Pty Ltd "
        "(Damien Elmes) and the Anki community. "
        f"{license_line} Source is available under that license."
    )
    parts.append(f"<p style='color:gray;font-size:small'>{contributors_html}")
    return "".join(parts)
```

- [ ] **Step 3: Rewire `qt/aqt/about.py`** to build the body via `about_html`. Replace the
      block at `about.py:66-83` (the `abouttext = "<center><img ...` through the
      `about_visit_website` block) with the gather-and-delegate below. Keep the contributor
      assembly at `about.py:85-241` but capture it into `contributors_html` and pass it in.

```python
    # WebView contents
    ######################################################################
    from aqt.pgrep_about import about_html

    seam_line = None
    if aqt.mw.col:
        seam_line = f"pgrep: {aqt.mw.col.pgrep_seam_check()}"
    env_line = ("Python %s Qt %s Chromium %s") % (
        platform.python_version(),
        qVersion(),
        (qWebEngineChromiumVersion() or "").split(".")[0],
    )
```

Then, after the existing `allusers` list is built into the
`about_written_by_damien_elmes_with_patches(...)` string plus the two thanks lines,
collect those into `contributors_html` and call:

```python
    contributors_html = tr.about_written_by_damien_elmes_with_patches(
        cont=", ".join(allusers) + f", {tr.about_and_others()}"
    )
    contributors_html += f"<p>{tr.about_if_you_have_contributed_and_are()}"
    contributors_html += f"<p>{tr.about_a_big_thanks_to_all_the()}"

    abouttext = about_html(
        license_line=tr.about_anki_is_licensed_under_the_agpl3(),
        version_line=tr.about_version(val=version_with_build()),
        seam_line=seam_line,
        env_line=env_line,
        contributors_html=contributors_html,
    )
    abt.label.setMinimumWidth(800)
    abt.label.setMinimumHeight(600)
    dialog.show()
    abt.label.stdHtml(abouttext, js=[])
    return dialog
```

Remove the old `abouttext = "<center><img ...`, the `lede` line, the
`about_anki_is_licensed_under_the_agpl3` append, the version/seam/env appends, and the
`about_visit_website` append (all superseded by `about_html`).

- [ ] **Step 4: Add the Settings "About and licenses" row** in
      `ts/routes/pgrep/settings/+page.svelte`. Add a new section at the end of the settings
      list, matching the file's existing row markup and classes. Static text is fine (no new
      bridge call):

```svelte
<section class="settings-group">
  <h2>About</h2>
  <p class="about-line">pgrep</p>
  <p class="about-credit">
    Built on Anki, created by Ankitects Pty Ltd and the Anki community, and
    licensed under the GNU AGPL v3 or later. Source is available under that license.
  </p>
</section>
```

Match the surrounding indentation and reuse existing group/heading classes if the file
already defines them (read the file first and follow its pattern). Add minimal scoped
styles only if the file has no equivalent.

- [ ] **Step 5 (controller runs):** verified by `qt/tests/test_pgrep_about.py` and
      `just check`.

---

### Task 2: sync and error strings

**Files:**

- Modify: `ftl/core/sync.ftl`
- Modify: `ftl/qt/errors.ftl`
- Create: `pylib/tests/test_pgrep_sync_branding.py`

Change **values only**, never keys. The key `sync-download-from-ankiweb` stays; only its
English text changes. This means no generated-API regen is needed.

- [ ] **Step 1: Edit `ftl/core/sync.ftl`.** Apply exactly these value changes:

```
sync-conflict = Only one copy of pgrep can sync at once. Please wait a few minutes, then try again.
sync-server-error = Your sync server encountered a problem. Please try again in a few minutes.
sync-client-too-old = Your pgrep version is too old. Please update to the latest version to continue syncing.
sync-must-wait-for-end = pgrep is currently syncing. Please wait for the sync to complete, then try again.
sync-confirm-empty-download = This device has no cards. Download from server?
sync-confirm-empty-upload = The server has no cards. Replace it with this device's collection?
sync-download-from-ankiweb = Download from server
sync-upload-to-ankiweb = Upload to server
sync-downloading-from-ankiweb = Downloading from server...
sync-uploading-to-ankiweb = Uploading to server...
```

Replace the multi-line `sync-conflict-explanation` block with:

```
sync-conflict-explanation =
    Your decks here and on the server differ in such a way that they can't be merged together, so it's necessary to overwrite the decks on one side with the decks from the other.

    If you choose download, pgrep will fetch the collection from the server, and any changes you have made on this device since the last sync will be lost.

    If you choose upload, pgrep will send this device's data to the server, and any changes that are waiting on the server will be lost.

    After all devices are in sync, future reviews and added cards can be merged automatically.
```

Replace the multi-line `sync-conflict-explanation2` block with:

```
sync-conflict-explanation2 =
    There is a conflict between this device and your sync server. You must choose which version to keep:

    - Select **{ sync-download-from-ankiweb }** to replace the decks here with the server’s version. You will lose any changes made on this device since your last sync.
    - Select **{ sync-upload-to-ankiweb }** to overwrite the server’s version with the decks from this device, and delete any changes stored there.

    Once the conflict is resolved, syncing will work as usual.
```

Replace the `sync-upload-too-large` block, changing "AnkiWeb" to "the server":

```
sync-upload-too-large =
    Your collection file is too large to send to the server. You can reduce its size by removing any unwanted decks (optionally exporting them first), and then using Check Database to shrink the file size down.

    { $details } (uncompressed)
```

Leave the media strings, `sync-ankiweb-id-label`, `sync-password-label`,
`sync-account-required`, and all AnkiHub strings unchanged (account and AnkiHub concepts
a self-hosted pgrep never shows). Leave the `### Messages shown when synchronizing with
  AnkiWeb.` comment (a comment, not user-facing).

- [ ] **Step 2: Edit `ftl/qt/errors.ftl`.** App-name rebrand only:

```
errors-standard-popup2 =
    pgrep encountered a problem. Please follow the troubleshooting steps.
errors-unable-open-collection =
    pgrep was unable to open your collection file. If problems persist after restarting your computer, please use the Open Backup button in the profile manager.

    Debug info:
```

In `errors-addons-active-popup`, change "start Anki" to "start pgrep" and "restart Anki"
to "restart pgrep". In `errors-accessing-db`, change "interfering with Anki" to
"interfering with pgrep". Leave the `Documents/Anki` folder path (on-disk data path,
deferred to packaging), the `-errors-support-site` link (deferred to packaging), and the
`Tools > Check Database` and `Tools > Add-ons` menu references (Anki-menu UX, deferred).

- [ ] **Step 3: Write the guard test** `pylib/tests/test_pgrep_sync_branding.py`:

```python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_sync_conflict_uses_server_wording():
    ftl = _read("ftl/core/sync.ftl")
    assert "sync-download-from-ankiweb = Download from server" in ftl
    assert "sync-upload-to-ankiweb = Upload to server" in ftl
    assert "conflict between this device and your sync server" in ftl
    # the user-facing service name is gone from the conflict copy
    assert "and AnkiWeb" not in ftl
    assert "from AnkiWeb" not in ftl


def test_sync_app_name_is_pgrep():
    ftl = _read("ftl/core/sync.ftl")
    assert "Only one copy of pgrep can sync" in ftl
    assert "pgrep is currently syncing" in ftl


def test_errors_app_name_is_pgrep():
    ftl = _read("ftl/qt/errors.ftl")
    assert "pgrep encountered a problem" in ftl
    assert "pgrep was unable to open your collection" in ftl
```

- [ ] **Step 4 (controller runs):** verified by the guard test and `just check`.

---

### Task 3: correct the L6 plan (bookkeeping)

**Files:**

- Modify: `docs_pgrep/plan/build-plan.md` (the `### L6` section, lines around 297-329)

- [ ] **Step 1:** Rewrite the L6 section so its status matches the repo. Mark L6.1 (the
      exclusive flip, `pgrep_host.py:39`) and the window title and icon work (`main.py:517`,
      `main.py:981`, `main.py:1475`) as done. Split the remainder into: (a) the de-Anki sweep
      (About and licenses, sync and error strings), pointing to
      `2026-07-06-l6-production-de-anki-design.md`, and (b) the follow-ons: packaging (bundle
      name and id, `.dmg` name, `CFBundleName`, the deferred data-folder and support-link
      cleanup, phone build, needs signing), hardening (crash test, benchmark), and submission
      recording. Keep the section's existing voice and the copy rule (no em-dashes).

- [ ] **Step 2:** Update the L6 row in the section 1 status table and the section 6
      constraint table only if they assert something now false. Keep constraint 9 (AGPL,
      crediting Anki) marked satisfied by the About and licenses surface.

---

### Task 4: reachability audit (read-only)

**Files:** none (produces a findings list for the controller).

- [ ] **Step 1:** With the surface in exclusive mode as the reference, list every place a
      user can reach a literal "Anki" or "AnkiWeb" string: walk the pgrep routes
      (`ts/routes/pgrep/`), the Qt chrome and dialogs reachable when admin menus are hidden
      (`qt/aqt/pgrep_host.py:apply_menu_chrome`, `qt/aqt/main.py` menu setup), and the `.ftl`
      strings those surfaces render. Report each finding as file, string, and whether it is
      reachable in exclusive mode. Do not edit anything. Flag anything the three tasks above do
      not already cover so the controller can decide on a follow-up.

---

## Self-review

- **Spec coverage.** Workstream 1 (About and licenses), Task 1. Workstream 2 (sync
  strings), Task 2 step 1. Workstream 3 (error strings), Task 2 step 2. Workstream 4
  (reachability audit), Task 4. Bookkeeping, Task 3. Constraints and exit gate, the guard
  tests plus `just check`. Covered.
- **Placeholder scan.** Every edit lists exact strings or exact code. No TBDs.
- **Type consistency.** `about_html(...)` keyword params match between the test (Task 1
  step 1), the definition (step 2), and the call site (step 3). The `.ftl` keys are
  unchanged, so no call-site drift.
- **Parallel safety.** Task 1 owns `qt/aqt/pgrep_about.py`, `qt/aqt/about.py`,
  `qt/tests/test_pgrep_about.py`, `ts/routes/pgrep/settings/+page.svelte`. Task 2 owns
  `ftl/core/sync.ftl`, `ftl/qt/errors.ftl`, `pylib/tests/test_pgrep_sync_branding.py`. Task
  3 owns `docs_pgrep/plan/build-plan.md`. Task 4 owns nothing. No file is shared, so tasks
  1 to 4 run in parallel. The controller runs `just check` once, serially, at the end.

---

## Wave 2: reachable Qt chrome and startup strings (audit follow-ups)

The reachability audit (Task 4) found more reachable Anki strings than wave 1 covered.
Approved scope: disable the on-launch update phone-home, and rebrand the remaining reachable
app-name strings and default dialog and progress titles. Defer packaging-coupled items (the
app bundle name `setApplicationName`, the `help.ankiweb.net` and `apps.ankiweb.net` URLs, and
the `Documents/Anki` data folder). Tasks 5 and 6 own disjoint files, so they run in parallel.

### Task 5: disable the on-launch update check plus Qt code strings (Qt Python)

**Files (one owner, they overlap on `main.py`):**

- Modify: `qt/aqt/main.py` (`setup_auto_update`; the hardcoded FileTooNew and downgrade strings)
- Modify: `qt/aqt/utils.py` (default dialog titles; `supportText`)
- Modify: `qt/aqt/progress.py` (default progress title)
- Modify: `qt/aqt/taskman.py` (`with_progress` default title)
- Modify: `qt/aqt/errors.py` (mbox title; the fatal panic string; the addon debug header)
- Modify: `qt/aqt/profiles.py` (the language dialog hardcoded title)

- [ ] **Step 1: Disable the on-launch update check.** In `setup_auto_update`
      (`main.py` around line 1630), do not call `aqt.update.check_for_update()`. pgrep has no
      update channel and must not contact Anki's servers on launch. Replace the body with an
      early return and a one-line comment explaining why. Leave the manual
      `action_check_for_updates` handler alone (it lives in the admin menu, unreachable in
      exclusive mode).
- [ ] **Step 2: Default titles.** Change every default title argument `title: str = "Anki"`
      to `"pgrep"` in `utils.py` (`showInfo`, `showWarning`, `showCritical`, `askUser`,
      `askUserDialog`, `MessageBox`, and any sibling with the same default), in `progress.py`
      (the progress dialog default title), and in `taskman.py` (`with_progress` default title).
- [ ] **Step 3: Debug and crash text.** In `utils.py`, `supportText()` change the
      `"Anki %s %s"` (or equivalent) prefix to `"pgrep %s %s"`. In `errors.py`, change
      `_mbox.setWindowTitle("Anki")` to `"pgrep"`, the hardcoded fatal string
      "A fatal error occurred, and Anki must close" to say "pgrep must close", and the
      "===IDs of active AnkiWeb add-ons===" header to "===IDs of active add-ons===".
- [ ] **Step 4: Hardcoded main.py and profiles.py strings.** In `main.py`, change
      "This profile requires a newer version of Anki to open..." to "...of pgrep..." and
      "Profiles can now be opened with an older version of Anki." to "...of pgrep." In
      `profiles.py`, change the language-selection dialog's hardcoded window title "Anki" to
      "pgrep".

Grep each file for the literal `"Anki"` and `AnkiWeb` and rebrand only the user-facing app
name. Do not touch URLs (`ankiweb.net`), the `Documents/Anki` path, internal identifiers,
or comments.

### Task 6: startup and misc ftl strings (values only)

**Files:**

- Modify: `ftl/core/profiles.ftl` (app-name only; keep the `Documents/Anki` paths)
- Modify: `ftl/qt/qt-misc.ftl` (app-name only; keep `apps.ankiweb.net` and help URLs)
- Modify: `pylib/tests/test_pgrep_sync_branding.py` (extend with a few stable assertions)

- [ ] **Step 1:** In `ftl/core/profiles.ftl`, rebrand the app name "Anki" to "pgrep" in the
      values of `profiles-anki-could-not-read-your-profile`,
      `profiles-anki-could-not-rename-your-profile` (keep its `Documents/Anki` path),
      `profiles-confirm-lang-choice`, `profiles-could-not-create-data-folder`, and
      `profiles-prefs-file-is-corrupt`. Keys unchanged.
- [ ] **Step 2:** In `ftl/qt/qt-misc.ftl`, rebrand the app name "Anki" to "pgrep" in the
      values of `qt-misc-anki-updatedanki-has-been-released`,
      `qt-misc-in-order-to-ensure-your-collection`, `qt-misc-your-collection-file-appears-to-be`,
      `qt-misc-unable-to-access-anki-media-folder`, `qt-misc-your-firewall-or-antivirus-program-is`,
      `qt-misc-incompatible-video-driver`, `qt-misc-error-loading-graphics-driver`,
      `qt-misc-anki-is-running`, `qt-misc-if-instance-is-not-responding`,
      `qt-misc-automatic-syncing-and-backups-have-been`, and `qt-misc-please-ensure-a-profile-is-open`.
      Keys unchanged. Leave any `apps.ankiweb.net` or `help.ankiweb.net` URL and the
      `Documents/Anki` path.
- [ ] **Step 3:** Extend `pylib/tests/test_pgrep_sync_branding.py` with a few stable guard
      assertions, for example that `ftl/core/profiles.ftl` now contains "pgrep could not read
      your profile" and that `ftl/qt/qt-misc.ftl` contains the pgrep app name where it was
      "Anki". Read the files after editing to copy exact substrings so the assertions match.
