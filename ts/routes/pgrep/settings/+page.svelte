<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep Settings. Sectioned preference cards, ported from the Claude Design
     export (design/ux-foundation.md). Sync (pgrepSync) and the AI toggle
     (pgrepAiStatus / pgrepAiSetEnabled) are wired to the backend; the theme
     control flips the theme live. The remaining rows (target retention, test
     date, export, reset) are local until their RPCs exist. Honesty note baked in:
     the app works and still scores with AI off. The shared rail comes from
     +layout.svelte, so this surface renders content only. -->
<script lang="ts">
    import { onMount } from "svelte";
    import { pgrepCall } from "../lib/bridge";

    type Theme = "Light" | "Dark" | "System";

    interface AiStatus {
        enabled: boolean;
        model: string | null;
        has_key: boolean;
        ready: boolean;
    }

    const THEMES: Theme[] = ["Light", "Dark", "System"];

    let targetRetention = 0.9;
    // AI is off by default; the real state is read from the backend on mount so
    // the toggle never claims AI is on when it is not.
    let aiOn = false;
    let aiBusy = false;
    let theme: Theme = "Dark";
    const testDate = "Oct 24, 2026";

    let serverURL = "http://127.0.0.1:8090/";
    let syncing = false;
    let syncMsg = "";

    async function loadAiStatus(): Promise<void> {
        try {
            const status = await pgrepCall<AiStatus>("pgrepAiStatus", {});
            aiOn = status.enabled;
        } catch {
            aiOn = false;
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
            syncMsg = `Sync failed: ${e}`;
        } finally {
            syncing = false;
        }
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
    });
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
                            min="0.7"
                            max="0.97"
                            step="0.01"
                            bind:value={targetRetention}
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
                    <button class="pill-btn" type="button">
                        <svg
                            width="15"
                            height="15"
                            viewBox="0 0 20 20"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.5"
                            stroke-linecap="round"
                        >
                            <rect x="3" y="4.5" width="14" height="12.5" rx="2" />
                            <line x1="3" y1="8.5" x2="17" y2="8.5" />
                            <line x1="7" y1="2.5" x2="7" y2="6" />
                            <line x1="13" y1="2.5" x2="13" y2="6" />
                        </svg>
                        <span class="mono">{testDate}</span>
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
                                on:click={() => applyTheme(opt)}
                            >
                                {opt}
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
                            Your cards, attempts, and history as a file
                        </div>
                    </div>
                    <button class="pill-btn strong" type="button">Export</button>
                </div>
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Reset</div>
                        <div class="row-sub">Start over. This cannot be undone.</div>
                    </div>
                    <button class="pill-btn danger" type="button">Reset</button>
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
