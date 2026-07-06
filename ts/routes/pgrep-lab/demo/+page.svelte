<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep demo control. A durable dev control that injects a clearly-marked
     hypothetical study history so Memory, Performance and Readiness light up on
     demand, then clears it again, and syncs that account to the self-hosted
     server so the same lit-up data lands on the phone. This is the backbone of
     the desktop-to-mobile sync demo. It is dev-only: it lives in pgrep-lab and is
     never wired into the shipped user surfaces, so real accounts still abstain by
     construction. Injection runs through the dev bridge handler pgrepDemoProfile;
     the sync button reuses the same pgrepSync flow the Settings surface uses. -->
<script lang="ts">
    import { onMount } from "svelte";
    import { pgrepCall } from "../../pgrep/lib/bridge";

    interface OverallScore {
        point: number | null;
        low: number | null;
        high: number | null;
        abstain: boolean;
        reason: string | null;
    }

    interface ReadinessScore {
        scaled: number | null;
        low: number | null;
        high: number | null;
        abstain: boolean;
        reason: string | null;
    }

    interface DemoStatus {
        injected: boolean;
        profile: string | null;
        profiles: { key: string; label: string }[];
        demo_cards: number;
        demo_attempts: number;
        covered_categories: string[];
        coverage_weight: number;
        coverage_pct: number;
        coverage_gate: number;
        scores: {
            memory: OverallScore;
            performance: OverallScore;
            readiness: ReadinessScore;
        };
    }

    let status: DemoStatus | null = null;
    let profile = "strong";
    let busy = false;
    let error = "";

    // Sync uses the same one-click flow the Settings surface uses: the URL is the
    // self-hosted server default and the account is the sync-server's default user
    // (see `just sync-server`), so there is no login form to fill for the demo.
    // 8090, not 8080: `just run` holds 8080 for the Qt remote-debug/hot-reload
    // server, so the sync stack uses its own port. Matches Settings and the CLI.
    const serverURL = "http://127.0.0.1:8090/";
    const account = "pgrep";
    let syncing = false;
    let syncMsg = "";

    async function refresh(action: "status" | "inject" | "clear"): Promise<void> {
        busy = true;
        error = "";
        try {
            status = await pgrepCall<DemoStatus>("pgrepDemoProfile", {
                action,
                profile,
            });
            if (status.profile) {
                profile = status.profile;
            }
        } catch (e) {
            error = `${e}`;
        } finally {
            busy = false;
        }
    }

    async function syncNow(): Promise<void> {
        syncing = true;
        syncMsg = "Syncing\u2026";
        try {
            await pgrepCall("pgrepSync", { url: serverURL });
            syncMsg =
                "Sync started. Watch the desktop for progress, then open the phone and sync down.";
        } catch (e) {
            syncMsg = `Sync failed. ${e}`;
        } finally {
            syncing = false;
        }
    }

    function pct(value: number | null): string {
        return value === null ? "n/a" : `${Math.round(value * 100)}%`;
    }

    function scaled(value: number | null): string {
        return value === null ? "n/a" : `${value}`;
    }

    $: profiles = status?.profiles ?? [
        { key: "strong", label: "Strong learner" },
        { key: "rusty", label: "Rusty learner" },
    ];

    onMount(() => {
        void refresh("status");
    });
</script>

<div>
    <header class="head">
        <h1>Demo control</h1>
        <p>
            Inject a hypothetical study history so the three scores light up on demand,
            then sync that account so the same data lands on the phone. This is a dev
            tool for hands-on testing and the desktop to mobile sync demo. It is never
            part of the shipped app, so real accounts still abstain until they earn a
            score.
        </p>
    </header>

    <section class="controls">
        <div class="control-row">
            <div class="seg" role="group" aria-label="Profile">
                {#each profiles as p (p.key)}
                    <button
                        class:on={profile === p.key}
                        disabled={busy}
                        on:click={() => (profile = p.key)}
                    >
                        {p.label}
                    </button>
                {/each}
            </div>
            <button
                class="btn strong"
                disabled={busy}
                on:click={() => refresh("inject")}
            >
                Inject profile
            </button>
            <button class="btn" disabled={busy} on:click={() => refresh("clear")}>
                Clear demo
            </button>
            {#if busy}
                <span class="hint">Working...</span>
            {/if}
        </div>
        {#if error}
            <p class="error">{error}</p>
        {/if}
    </section>

    {#if status}
        <section class="state">
            <div class="state-line">
                {#if status.injected}
                    <span class="dot on"></span>
                    <span>
                        Injected ({status.profile}). {status.demo_cards} demo cards,
                        {status.demo_attempts} attempts.
                    </span>
                {:else}
                    <span class="dot"></span>
                    <span>
                        No demo injected. The scores below abstain, as a real account
                        would.
                    </span>
                {/if}
            </div>
        </section>

        <section class="scores">
            <div class="score" style="--accent: var(--memory);">
                <div class="score-label">Memory</div>
                {#if status.scores.memory.abstain}
                    <div class="score-value abstain">Abstains</div>
                    <div class="score-sub">{status.scores.memory.reason}</div>
                {:else}
                    <div class="score-value">{pct(status.scores.memory.point)}</div>
                    <div class="score-sub">
                        {pct(status.scores.memory.low)} to {pct(
                            status.scores.memory.high,
                        )}
                    </div>
                {/if}
            </div>

            <div class="score" style="--accent: var(--performance);">
                <div class="score-label">Performance</div>
                {#if status.scores.performance.abstain}
                    <div class="score-value abstain">Abstains</div>
                    <div class="score-sub">{status.scores.performance.reason}</div>
                {:else}
                    <div class="score-value">
                        {pct(status.scores.performance.point)}
                    </div>
                    <div class="score-sub">
                        {pct(status.scores.performance.low)} to {pct(
                            status.scores.performance.high,
                        )}
                    </div>
                {/if}
            </div>

            <div class="score" style="--accent: var(--readiness);">
                <div class="score-label">Readiness</div>
                {#if status.scores.readiness.abstain}
                    <div class="score-value abstain">Abstains</div>
                    <div class="score-sub">{status.scores.readiness.reason}</div>
                {:else}
                    <div class="score-value">
                        {scaled(status.scores.readiness.scaled)}
                    </div>
                    <div class="score-sub">
                        {scaled(status.scores.readiness.low)} to {scaled(
                            status.scores.readiness.high,
                        )}
                    </div>
                {/if}
            </div>
        </section>

        <section class="coverage">
            <div class="coverage-head">
                <span>Blueprint coverage</span>
                <span class="mono">
                    {Math.round(status.coverage_pct * 100)}% of {Math.round(
                        status.coverage_gate * 100,
                    )}% gate
                </span>
            </div>
            <div class="bar">
                <div
                    class="bar-fill"
                    style="width: {status.coverage_pct * 100}%;"
                ></div>
                <div
                    class="bar-gate"
                    style="left: {status.coverage_gate * 100}%;"
                ></div>
            </div>
            <p class="caption">
                Readiness needs {Math.round(status.coverage_gate * 100)}% of the
                blueprint weight covered by scored topics. The demo covers {status
                    .covered_categories.length} areas and leaves the rest an honest gap.
            </p>
        </section>

        <section class="sync">
            <div class="sync-head">
                <span>Sync this account (desktop to phone)</span>
                <span class="mono">{account} @ {serverURL}</span>
            </div>
            <p class="caption">
                One click, no login form. The demo account and the self-hosted server
                are the defaults, so this behaves like a normal account sign-in. Start
                the server first with <code>just sync-server</code>.
            </p>
            <div class="sync-row">
                <button class="btn strong" disabled={syncing} on:click={syncNow}>
                    {syncing ? "Syncing\u2026" : "Sync now"}
                </button>
                {#if syncMsg}
                    <span class="hint">{syncMsg}</span>
                {/if}
            </div>
            <ol class="steps">
                <li>Inject a profile above, then Sync now to upload it.</li>
                <li>
                    On the phone, open pgrep Settings, keep the same server and account,
                    and sync down.
                </li>
                <li>The same lit-up scores appear on the phone. Clear to reset both.</li>
            </ol>
        </section>
    {/if}
</div>

<style lang="scss">
    .head {
        margin-bottom: var(--space-4);

        h1 {
            margin: 0 0 var(--space-1);
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        p {
            margin: 0;
            max-width: 74ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
        }
    }

    .controls {
        margin-bottom: var(--space-3);
    }

    .control-row {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
    }

    .seg {
        display: inline-flex;
        border: var(--hairline);
        border-radius: var(--radius-control);
        overflow: hidden;

        button {
            appearance: none;
            border: 0;
            background: var(--surface);
            color: var(--muted);
            font: inherit;
            font-size: var(--text-small);
            font-weight: 500;
            padding: 8px 16px;
            cursor: pointer;
            transition: var(--transition-calm);

            &.on {
                background: var(--action-bg);
                color: var(--action-fg);
            }

            &:not(.on):hover {
                background: var(--hover-wash);
                color: var(--text);
            }

            &:disabled {
                cursor: default;
                opacity: 0.6;
            }
        }
    }

    .btn {
        appearance: none;
        border: var(--hairline);
        background: var(--surface);
        color: var(--text);
        font: inherit;
        font-size: var(--text-small);
        font-weight: 500;
        padding: 8px 16px;
        border-radius: var(--radius-control);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            background: var(--hover-wash);
            border-color: var(--muted);
        }

        &.strong {
            border-color: var(--muted);
        }

        &:disabled {
            cursor: default;
            opacity: 0.6;
        }
    }

    .hint {
        font-size: var(--text-small);
        color: var(--muted);
    }

    .error {
        margin: var(--space-1) 0 0;
        font-size: var(--text-small);
        color: var(--error);
    }

    .state {
        margin-bottom: var(--space-3);
    }

    .state-line {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: var(--text-small);
        color: var(--muted);
    }

    .dot {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: var(--muted);
        flex: 0 0 auto;

        &.on {
            background: var(--readiness);
        }
    }

    .scores {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: var(--space-2);
        margin-bottom: var(--space-4);
    }

    .score {
        border: var(--hairline);
        border-radius: var(--radius-card);
        background: var(--surface);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
        border-top: 3px solid var(--accent);
    }

    .score-label {
        font-size: var(--text-caption);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--accent);
        margin-bottom: 8px;
    }

    .score-value {
        font-family: var(--font-mono);
        font-size: var(--text-title);
        font-weight: 600;
        letter-spacing: -0.02em;

        &.abstain {
            font-family: var(--font-ui);
            font-size: var(--text-emphasis);
            color: var(--muted);
        }
    }

    .score-sub {
        margin-top: 6px;
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .coverage {
        border: var(--hairline);
        border-radius: var(--radius-card);
        background: var(--surface);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
    }

    .coverage-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: var(--text-small);
        font-weight: 500;
        margin-bottom: 10px;
    }

    .mono {
        font-family: var(--font-mono);
        color: var(--muted);
    }

    .bar {
        position: relative;
        height: 10px;
        border-radius: var(--radius-pill);
        background: var(--elevated);
        overflow: hidden;
    }

    .bar-fill {
        height: 100%;
        background: var(--readiness);
        border-radius: var(--radius-pill);
        transition: width 240ms var(--ease-spring);
    }

    .bar-gate {
        position: absolute;
        top: -3px;
        bottom: -3px;
        width: 2px;
        background: var(--text);
        opacity: 0.55;
    }

    .caption {
        margin: 10px 0 0;
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    .sync {
        margin-top: var(--space-3);
        border: var(--hairline);
        border-radius: var(--radius-card);
        background: var(--surface);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
        border-top: 3px solid var(--readiness);
    }

    .sync-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
        flex-wrap: wrap;
        font-size: var(--text-small);
        font-weight: 600;
        margin-bottom: 6px;
    }

    .sync-row {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
        margin-top: var(--space-2);
    }

    code {
        font-family: var(--font-mono);
        font-size: 0.92em;
        padding: 1px 6px;
        border-radius: var(--radius-control);
        background: var(--elevated);
    }

    .steps {
        margin: var(--space-2) 0 0;
        padding-left: 1.2em;
        font-size: var(--text-small);
        line-height: 1.6;
        color: var(--muted);

        li {
            margin-bottom: 2px;
        }
    }

    @media (max-width: 720px) {
        .scores {
            grid-template-columns: 1fr;
        }
    }
</style>
