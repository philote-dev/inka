<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep Settings. Sectioned preference cards, ported from the Claude Design
     export (design/ux-foundation.md). State is local for now; the values wire to
     the backend once settings RPCs exist. The theme control flips the theme live.
     Honesty note baked in: the app works and still scores with AI off. The shared
     rail comes from +layout.svelte, so this surface renders content only. -->
<script lang="ts">
    import { onMount } from "svelte";

    type Theme = "Light" | "Dark" | "System";

    const THEMES: Theme[] = ["Light", "Dark", "System"];

    let targetRetention = 0.9;
    let aiOn = true;
    let theme: Theme = "Dark";
    const testDate = "Oct 24, 2026";
    const lastSynced = "12m ago";
    const account = "sam.chen@fastmail.com";

    $: retentionLabel = targetRetention.toFixed(2);

    function nightModeOn(): boolean {
        return document.documentElement.classList.contains("night-mode")
            || document.body.classList.contains("night-mode");
    }

    function applyTheme(next: Theme): void {
        theme = next;
        const el = document.documentElement;
        if (next === "Light") {
            el.classList.remove("night-mode");
        } else if (next === "Dark") {
            el.classList.add("night-mode");
        } else {
            const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
            el.classList.toggle("night-mode", prefersDark);
        }
    }

    onMount(() => {
        // Reflect the theme the app already shows, so the control starts honest.
        theme = nightModeOn() ? "Dark" : "Light";
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
                        <div class="row-sub">How much you keep before a card comes back</div>
                    </div>
                    <div class="row-control slider">
                        <input type="range" min="0.7" max="0.97" step="0.01" bind:value={targetRetention} aria-label="Target retention" />
                        <span class="val">{retentionLabel}</span>
                    </div>
                </div>
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Test date</div>
                        <div class="row-sub">Pacing works back from this day</div>
                    </div>
                    <button class="pill-btn" type="button">
                        <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
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
                        <div class="row-sub">The app always works and still scores with AI off.</div>
                    </div>
                    <button
                        class="toggle"
                        class:on={aiOn}
                        role="switch"
                        aria-checked={aiOn}
                        aria-label="AI assistance"
                        on:click={() => (aiOn = !aiOn)}
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
                        <div class="row-title">Sync</div>
                        <div class="row-sub mono">Last synced {lastSynced}</div>
                    </div>
                    <button class="pill-btn strong" type="button">Sync now</button>
                </div>
                <div class="row">
                    <div class="row-text">
                        <div class="row-title">Account</div>
                        <div class="row-sub">{account}</div>
                    </div>
                    <button class="link-btn" type="button">
                        Manage
                        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="6,3.5 11,8 6,12.5" />
                        </svg>
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
                            <button class="seg" class:on={theme === opt} on:click={() => applyTheme(opt)}>{opt}</button>
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
                        <div class="row-sub">Your cards, attempts, and history as a file</div>
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

        &.mono {
            font-variant-numeric: tabular-nums;
        }
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

    .link-btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: none;
        border: none;
        color: var(--muted);
        font-family: var(--font-ui);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        padding: 8px 4px;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
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

        .knob {
            position: absolute;
            top: 2px;
            left: 3px;
            width: 20px;
            height: 20px;
            border-radius: var(--radius-pill);
            background: var(--muted);
            transition: transform 240ms var(--ease-spring), background 240ms var(--ease-spring);
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
