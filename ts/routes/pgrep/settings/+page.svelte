<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep Settings. Sectioned preference cards, ported from the Claude Design
     export (design/ux-foundation.md). Every control is wired to the backend:
     target retention persists on the sample deck's FSRS config, test date and
     theme persist in the collection, Export writes a .colpkg, and Sync runs
     Anki's own sync. The AI toggle reads and writes the AI seam. Honesty note
     baked in: the app works and still scores with AI off. The shared rail comes
     from +layout.svelte, so this surface renders content only. -->
<script lang="ts">
    import { goto } from "$app/navigation";
    import { onDestroy, onMount } from "svelte";
    import { manifoldView, type ManifoldView } from "$lib/pgrep/prefs";
    import { pgrepCall } from "../lib/bridge";

    type Theme = "Light" | "Dark" | "System";

    // The knowledge-map projection. A per-device presentation choice, so it lives
    // in localStorage (via the store) rather than the synced collection.
    const MANIFOLD_VIEWS: { value: ManifoldView; label: string }[] = [
        { value: "auto", label: "Auto" },
        { value: "wire", label: "3D" },
        { value: "map", label: "Map" },
    ];

    interface AiStatus {
        enabled: boolean;
        model: string | null;
        has_key: boolean;
        ready: boolean;
    }

    interface Settings {
        target_retention: number;
        test_date: string | null;
        theme: Theme | null;
        sync_url: string;
        retention_min: number;
        retention_max: number;
    }

    const THEMES: Theme[] = ["Light", "Dark", "System"];

    let targetRetention = 0.9;
    let retentionMin = 0.7;
    let retentionMax = 0.97;
    // AI is off by default; the real state is read from the backend on mount so
    // the toggle never claims AI is on when it is not.
    let aiOn = false;
    let aiBusy = false;
    let theme: Theme = "Dark";
    // An ISO YYYY-MM-DD string, or empty when the learner has set no test date.
    let testDate = "";

    // 8090, not 8080: `just run` uses 8080 for the Qt remote-debug/hot-reload
    // server, so the sync stack gets its own port to avoid the collision.
    let serverURL = "http://127.0.0.1:8090/";
    let syncing = false;
    let syncMsg = "";

    let exporting = false;
    let exportMsg = "";

    // Reset is destructive, so it takes two clicks: the first arms the button
    // (it reads "Confirm reset?"), a second within a few seconds confirms. A
    // stray single click disarms itself and never touches any data.
    let resetArmed = false;
    let resetting = false;
    let resetMsg = "";
    let resetTimer: ReturnType<typeof setTimeout> | undefined;

    async function loadAiStatus(): Promise<void> {
        try {
            const status = await pgrepCall<AiStatus>("pgrepAiStatus", {});
            aiOn = status.enabled;
        } catch {
            aiOn = false;
        }
    }

    async function loadSettings(): Promise<void> {
        try {
            const s = await pgrepCall<Settings>("pgrepSettingsGet", {});
            targetRetention = s.target_retention;
            retentionMin = s.retention_min;
            retentionMax = s.retention_max;
            testDate = s.test_date ?? "";
            if (s.sync_url) {
                serverURL = s.sync_url;
            }
            // A stored theme wins; otherwise the app keeps reflecting whatever it
            // already shows, so a fresh profile never claims a choice unmade.
            if (s.theme) {
                applyTheme(s.theme);
            }
        } catch {
            // Leave the honest defaults in place if the read fails.
        }
    }

    async function saveRetention(): Promise<void> {
        try {
            const s = await pgrepCall<Settings>("pgrepSettingsSet", {
                target_retention: targetRetention,
            });
            targetRetention = s.target_retention;
        } catch {
            // Keep the shown value; the next load reconciles it.
        }
    }

    async function saveTestDate(): Promise<void> {
        try {
            const s = await pgrepCall<Settings>("pgrepSettingsSet", {
                test_date: testDate,
            });
            testDate = s.test_date ?? "";
        } catch {
            // Keep the typed value; the next load reconciles it.
        }
    }

    async function saveSyncUrl(): Promise<void> {
        try {
            const s = await pgrepCall<Settings>("pgrepSettingsSet", {
                sync_url: serverURL,
            });
            serverURL = s.sync_url;
        } catch {
            // Keep the typed value; the next load reconciles it.
        }
    }

    async function chooseTheme(next: Theme): Promise<void> {
        applyTheme(next);
        try {
            await pgrepCall("pgrepSettingsSet", { theme: next });
        } catch {
            // The live theme still applied; persistence retries on the next pick.
        }
    }

    async function toggleAi(): Promise<void> {
        if (aiBusy) {
            return;
        }
        aiBusy = true;
        try {
            const status = await pgrepCall<AiStatus>("pgrepAiSetEnabled", {
                enabled: !aiOn,
            });
            aiOn = status.enabled;
        } catch {
            // Leave the toggle unchanged when the write fails.
        } finally {
            aiBusy = false;
        }
    }

    async function syncNow(): Promise<void> {
        syncing = true;
        syncMsg = "Syncing\u2026";
        try {
            await pgrepCall("pgrepSync", { url: serverURL.trim() });
            syncMsg = "Sync running. Watch the desktop for progress and completion.";
        } catch (e) {
            syncMsg = `Sync failed. ${e}`;
        } finally {
            syncing = false;
        }
    }

    async function exportData(): Promise<void> {
        if (exporting) {
            return;
        }
        exporting = true;
        exportMsg = "Exporting\u2026";
        try {
            const res = await pgrepCall<{ status: string; path: string }>(
                "pgrepExport",
                {},
            );
            exportMsg = `Export running. Saving to ${res.path}`;
        } catch (e) {
            exportMsg = `Export failed. ${e}`;
        } finally {
            exporting = false;
        }
    }

    function armReset(): void {
        resetArmed = true;
        clearTimeout(resetTimer);
        resetTimer = setTimeout(() => {
            resetArmed = false;
        }, 4000);
    }

    async function confirmReset(): Promise<void> {
        clearTimeout(resetTimer);
        resetArmed = false;
        resetting = true;
        resetMsg = "Resetting\u2026";
        try {
            const res = await pgrepCall<{
                attempts_deleted: number;
                cards_reset: number;
            }>("pgrepReset", {});
            resetMsg =
                `Progress reset. Cleared ${res.attempts_deleted} attempts and ` +
                `reset ${res.cards_reset} sample cards.`;
        } catch (e) {
            resetMsg = `Reset failed. ${e}`;
        } finally {
            resetting = false;
        }
    }

    function onResetClick(): void {
        if (resetting) {
            return;
        }
        if (resetArmed) {
            void confirmReset();
        } else {
            armReset();
        }
    }

    function resetLabel(busy: boolean, armed: boolean): string {
        if (busy) {
            return "Resetting\u2026";
        }
        if (armed) {
            return "Confirm reset?";
        }
        return "Reset";
    }

    function resetHint(msg: string, armed: boolean): string {
        if (msg) {
            return msg;
        }
        if (armed) {
            return "This clears your attempts and sample progress. Click again to confirm.";
        }
        return "Start over. This clears progress, not your cards.";
    }

    $: retentionLabel = targetRetention.toFixed(2);

    function nightModeOn(): boolean {
        return (
            document.documentElement.classList.contains("night-mode") ||
            document.body.classList.contains("night-mode")
        );
    }

    function applyTheme(next: Theme): void {
        theme = next;
        const el = document.documentElement;
        if (next === "Light") {
            el.classList.remove("night-mode");
        } else if (next === "Dark") {
            el.classList.add("night-mode");
        } else {
            const prefersDark =
                window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
            el.classList.toggle("night-mode", prefersDark);
        }
    }

    onMount(() => {
        // Reflect the theme the app already shows, so the control starts honest.
        theme = nightModeOn() ? "Dark" : "Light";
        void loadAiStatus();
        void loadSettings();
    });

    onDestroy(() => clearTimeout(resetTimer));
</script>

<div class="main">
    <div class="column">
        <header class="head">
            <h1>Settings</h1>
        </header>

        <section class="group">
            <div class="group-label">Study</div>
            <div class="card">
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Target retention</div>
                        <div class="row-sub">
                            How much you keep before a card comes back
                        </div>
                    </div>
                    <div class="row-control slider">
                        <input
                            type="range"
                            min={retentionMin}
                            max={retentionMax}
                            step="0.01"
                            bind:value={targetRetention}
                            on:change={saveRetention}
                            aria-label="Target retention"
                        />
                        <span class="val">{retentionLabel}</span>
                    </div>
                </div>
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Test date</div>
                        <div class="row-sub">Pacing works back from this day</div>
                    </div>
                    <input
                        class="date-input mono"
                        type="date"
                        bind:value={testDate}
                        on:change={saveTestDate}
                        aria-label="Test date"
                    />
                </div>
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Diagnostic</div>
                        <div class="row-sub">
                            Re-place your topics with a fresh quick check
                        </div>
                    </div>
                    <button
                        class="pill-btn strong"
                        type="button"
                        on:click={() => goto("/pgrep/diagnostic")}
                    >
                        Re-run
                    </button>
                </div>
            </div>
        </section>

        <section class="group">
            <div class="group-label">AI</div>
            <div class="card">
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">AI assistance</div>
                        <div class="row-sub">
                            The app always works and still scores with AI off.
                        </div>
                    </div>
                    <button
                        class="toggle"
                        class:on={aiOn}
                        role="switch"
                        aria-checked={aiOn}
                        aria-label="AI assistance"
                        disabled={aiBusy}
                        on:click={toggleAi}
                    >
                        <span class="knob"></span>
                    </button>
                </div>
            </div>
        </section>

        <section class="group">
            <div class="group-label">Sync</div>
            <div class="card">
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Server</div>
                        <div class="row-sub">Self-hosted sync server URL</div>
                    </div>
                    <input
                        class="url-input mono"
                        type="text"
                        bind:value={serverURL}
                        on:change={saveSyncUrl}
                        on:blur={saveSyncUrl}
                        spellcheck="false"
                        autocomplete="off"
                        aria-label="Sync server URL"
                    />
                </div>
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Sync</div>
                        <div class="row-sub">
                            {syncMsg || "Two-way sync with the phone"}
                        </div>
                    </div>
                    <button
                        class="pill-btn strong"
                        type="button"
                        on:click={syncNow}
                        disabled={syncing}
                    >
                        {syncing ? "Syncing…" : "Sync now"}
                    </button>
                </div>
            </div>
        </section>

        <section class="group">
            <div class="group-label">Appearance</div>
            <div class="card">
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Theme</div>
                        <div class="row-sub">Light and dark are both first class</div>
                    </div>
                    <div class="segmented" role="group" aria-label="Theme">
                        {#each THEMES as opt (opt)}
                            <button
                                class="seg"
                                class:on={theme === opt}
                                on:click={() => chooseTheme(opt)}
                            >
                                {opt}
                            </button>
                        {/each}
                    </div>
                </div>
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Manifold</div>
                        <div class="row-sub">
                            How your knowledge map is drawn. Auto uses the 3D surface
                            where it can, the flat map elsewhere.
                        </div>
                    </div>
                    <div class="segmented" role="group" aria-label="Manifold view">
                        {#each MANIFOLD_VIEWS as opt (opt.value)}
                            <button
                                class="seg"
                                class:on={$manifoldView === opt.value}
                                on:click={() => manifoldView.set(opt.value)}
                            >
                                {opt.label}
                            </button>
                        {/each}
                    </div>
                </div>
            </div>
        </section>

        <section class="group">
            <div class="group-label">Data</div>
            <div class="card">
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Export</div>
                        <div class="row-sub">
                            {exportMsg || "Your cards, attempts, and history as a file"}
                        </div>
                    </div>
                    <button
                        class="pill-btn strong"
                        type="button"
                        on:click={exportData}
                        disabled={exporting}
                    >
                        {exporting ? "Exporting…" : "Export"}
                    </button>
                </div>
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Reset</div>
                        <div class="row-sub">{resetHint(resetMsg, resetArmed)}</div>
                    </div>
                    <button
                        class="pill-btn danger"
                        class:armed={resetArmed}
                        type="button"
                        on:click={onResetClick}
                        disabled={resetting}
                    >
                        {resetLabel(resetting, resetArmed)}
                    </button>
                </div>
            </div>
        </section>

        <section class="group">
            <div class="group-label">About</div>
            <div class="card">
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">pgrep</div>
                        <div class="row-sub">
                            Built on Anki, created by Ankitects Pty Ltd and the Anki
                            community, and licensed under the GNU AGPL v3 or later.
                            Source is available under that license.
                        </div>
                    </div>
                </div>
            </div>
        </section>
    </div>
</div>

<style lang="scss">
    .main {
        padding: 40px 24px 64px;
        display: flex;
        justify-content: center;
    }

    .column {
        width: 100%;
        max-width: 620px;
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
    }

    .head h1 {
        margin: 0;
        font-size: var(--text-title);
        font-weight: 600;
        letter-spacing: -0.02em;
    }

    .group-label {
        font-size: var(--text-caption);
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 10px;
        padding-left: 2px;
    }

    .card {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
    }

    .row {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        padding: 16px 20px;

        & + .row {
            border-top: var(--hairline);
        }
    }

    .row-text {
        flex: 1 1 auto;
        min-width: 0;
    }

    .row-title {
        font-size: var(--text-body);
        font-weight: 500;
    }

    .row-sub {
        font-size: var(--text-small);
        color: var(--muted);
        margin-top: 3px;
    }

    .row-control {
        flex: 0 0 auto;
    }

    .slider {
        display: flex;
        align-items: center;
        gap: 14px;

        input[type="range"] {
            width: 160px;
            accent-color: var(--action-bg);
            cursor: pointer;
        }

        .val {
            font-family: var(--font-mono);
            font-size: 13px;
            font-variant-numeric: tabular-nums;
            width: 38px;
            text-align: right;
        }
    }

    .mono {
        font-variant-numeric: tabular-nums;
    }

    .url-input {
        flex: 0 0 auto;
        width: 240px;
        max-width: 48vw;
        background: var(--elevated);
        border: var(--hairline);
        border-radius: var(--radius-control);
        padding: 9px 12px;
        color: var(--text);
        font-family: var(--font-mono);
        font-size: 13px;
        text-align: right;

        &:focus {
            outline: none;
            border-color: var(--muted);
        }
    }

    .date-input {
        flex: 0 0 auto;
        background: var(--elevated);
        border: var(--hairline);
        border-radius: var(--radius-control);
        padding: 8px 12px;
        color: var(--text);
        font-family: var(--font-mono);
        font-size: 13px;
        cursor: pointer;
        // Light by default; the night-mode override flips the native calendar
        // indicator so it stays visible in dark.
        color-scheme: light;
        transition: var(--transition-calm);

        &:hover {
            border-color: var(--muted);
        }

        &:focus {
            outline: none;
            border-color: var(--muted);
        }
    }

    :global(.night-mode) .date-input {
        color-scheme: dark;
    }

    .pill-btn {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        background: none;
        border: var(--hairline);
        border-radius: var(--radius-control);
        padding: 9px 14px;
        color: var(--text);
        font-family: var(--font-ui);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        white-space: nowrap;
        transition: var(--transition-calm);

        &:hover {
            border-color: var(--muted);
            background: var(--hover-wash);
        }

        &.strong {
            border-color: var(--muted);
        }

        &.danger {
            color: var(--error);
            border-color: var(--error-tint);

            &:hover {
                border-color: var(--error-tint-strong);
                background: var(--error-wash);
            }

            // Armed (awaiting the confirming second click): a filled red so the
            // destructive intent is unmistakable.
            &.armed {
                color: var(--error-fg);
                background: var(--error);
                border-color: var(--error);

                &:hover {
                    background: var(--error);
                    border-color: var(--error);
                }
            }
        }
    }

    .toggle {
        flex: 0 0 44px;
        width: 44px;
        height: 26px;
        border-radius: var(--radius-pill);
        border: 1px solid var(--border);
        background: var(--elevated);
        position: relative;
        cursor: pointer;
        padding: 0;
        transition: var(--transition-calm);

        &:disabled {
            cursor: default;
        }

        .knob {
            position: absolute;
            top: 2px;
            left: 3px;
            width: 20px;
            height: 20px;
            border-radius: var(--radius-pill);
            background: var(--muted);
            transition:
                transform 240ms var(--ease-spring),
                background 240ms var(--ease-spring);
        }

        &.on {
            background: var(--action-bg);
            border-color: transparent;

            .knob {
                transform: translateX(18px);
                background: var(--action-fg);
            }
        }
    }

    .segmented {
        display: inline-flex;
        border: var(--hairline);
        border-radius: var(--radius-control);
        padding: 3px;
        gap: 2px;

        .seg {
            appearance: none;
            border: none;
            background: none;
            font-family: var(--font-ui);
            font-size: 13px;
            font-weight: 500;
            color: var(--muted);
            padding: 6px 14px;
            border-radius: 7px;
            cursor: pointer;
            transition: var(--transition-calm);

            &:hover:not(.on) {
                color: var(--text);
            }

            &.on {
                color: var(--text);
                background: var(--elevated);
            }
        }
    }
</style>
