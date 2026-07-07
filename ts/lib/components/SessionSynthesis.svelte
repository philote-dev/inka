<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep session synthesis, the end-of-session consolidation screen for the Study
    door (design/claude-design/session-synthesis). Shown once when the last problem
    of a session is committed; it replaces the problem canvas and is not a modal.

    Truth first, warmth from reframing: the score is stated plainly and reframed
    honestly (desirable-difficulty study is supposed to feel worse than it went).
    The centre is patterns, not a question-by-question replay, because the pattern
    is the transferable unit. One card may credit a real strategy that worked; it
    is omitted, never invented, when there is none. One exit: Done.

    Presentational: the caller fetches the pgrepTutorSynthesis payload; this only
    displays it. Shared by the real Problems session end and the dev-lab preview.
-->
<script lang="ts">
    import { renderMath } from "$lib/pgrep/math";
    import type { SessionSynthesis } from "$lib/pgrep/synthesis";
    import { noDashes } from "$lib/pgrep/text";

    export let synthesis: SessionSynthesis;
    export let onDone: (() => void) | undefined = undefined;
    export let onClose: (() => void) | undefined = undefined;

    const LABELS: Record<string, string> = {
        mechanics: "Mechanics",
        electromagnetism: "E&M",
        quantum: "Quantum",
        thermodynamics: "Thermo",
        atomic: "Atomic",
        optics_waves: "Optics & waves",
        special_relativity: "Relativity",
        lab: "Lab methods",
        specialized: "Specialized",
    };
    function label(slug: string): string {
        return LABELS[slug] ?? slug.replace(/_/g, " ");
    }

    $: score = synthesis.score ?? { correct: 0, total: 0 };
    $: topics = synthesis.by_topic ?? [];
    $: patterns = synthesis.patterns ?? [];
    $: durationLabel =
        synthesis.duration_min >= 1
            ? `${synthesis.duration_min} min`
            : "under a minute";

    function pct(t: { correct: number; total: number }): number {
        return t.total ? Math.round((t.correct / t.total) * 100) : 0;
    }
    function countLabel(p: { count: number; kind: "miss" | "save" }): string {
        const noun = p.kind === "save" ? "save" : "miss";
        const plural = p.kind === "save" ? "saves" : "misses";
        return `${p.count} ${p.count === 1 ? noun : plural}`;
    }
</script>

<section class="screen">
    <header class="topbar">
        <span class="counter">{score.total} / {score.total}</span>
        <span class="pill">Session complete</span>
        <button
            class="close"
            type="button"
            aria-label="Close"
            on:click={() => onClose?.()}
        >
            <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
            >
                <line x1="4" y1="4" x2="12" y2="12" />
                <line x1="12" y1="4" x2="4" y2="12" />
            </svg>
        </button>
    </header>

    <div class="column">
        <div class="kicker">Session synthesis</div>
        <div class="score-row">
            <span class="score">{score.correct} / {score.total}</span>
            <span class="score-meta">correct · {durationLabel}</span>
        </div>
        {#if synthesis.reframe}
            <p class="reframe">{noDashes(synthesis.reframe)}</p>
        {/if}

        {#if topics.length}
            <div class="section">
                <h2>By topic</h2>
                <div class="topics">
                    {#each topics as t (t.topic)}
                        <div class="topic-row">
                            <span class="topic-name">{label(t.topic)}</span>
                            <div class="bar">
                                <div class="bar-fill" style="width: {pct(t)}%"></div>
                            </div>
                            <span class="topic-frac">{t.correct} / {t.total}</span>
                        </div>
                    {/each}
                </div>
            </div>
        {/if}

        {#if patterns.length}
            <div class="section">
                <h2>Patterns across the session</h2>
                <div class="cards">
                    {#each patterns as p (p.title)}
                        <section class="card">
                            <div class="card-head">
                                <h3 class="card-title">{noDashes(p.title)}</h3>
                                <span class="count-chip" class:save={p.kind === "save"}>
                                    {countLabel(p)}
                                </span>
                            </div>
                            {#if p.evidence}
                                <p class="evidence">
                                    {@html renderMath(noDashes(p.evidence))}
                                </p>
                            {/if}
                        </section>
                    {/each}
                </div>
            </div>
        {/if}

        <div class="footer">
            <span class="selector-note">
                Tomorrow's selector weights these patterns.
            </span>
            <button class="done" type="button" on:click={() => onDone?.()}>Done</button>
        </div>
    </div>
</section>

<style lang="scss">
    .screen {
        display: flex;
        flex-direction: column;
        flex: 1 1 auto;
        min-height: 100%;
        background: var(--canvas);
        color: var(--text);
        font-family: var(--font-ui);
        font-variant-numeric: tabular-nums;
        text-align: left;
    }

    .topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 20px 28px;
    }

    .counter {
        font-family: var(--font-mono);
        font-size: 13px;
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .pill {
        font-size: 12px;
        font-weight: 500;
        color: var(--performance-text);
        border: 1px solid var(--performance-tint);
        border-radius: var(--radius-pill);
        padding: 4px 12px;
    }

    .close {
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: none;
        border: none;
        border-radius: 8px;
        color: var(--muted);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            background: var(--elevated);
            color: var(--text);
        }
    }

    .column {
        width: 640px;
        max-width: 100%;
        margin: 0 auto;
        padding: 32px 24px 56px;
        flex: 1 1 auto;
        display: flex;
        flex-direction: column;
    }

    .kicker {
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .score-row {
        display: flex;
        align-items: baseline;
        gap: 14px;
        margin-top: 12px;
    }

    .score {
        font-family: var(--font-mono);
        font-size: 44px;
        letter-spacing: -0.02em;
        font-variant-numeric: tabular-nums;
    }

    .score-meta {
        font-size: 15px;
        color: var(--muted);
    }

    .reframe {
        margin: 12px 0 0;
        font-size: 15px;
        line-height: 1.6;
        color: var(--muted);
        max-width: 540px;
    }

    .section {
        margin-top: 36px;

        h2 {
            margin: 0 0 14px;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--muted);
        }
    }

    .topics {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .topic-row {
        display: grid;
        grid-template-columns: 150px 1fr 56px;
        align-items: center;
        gap: 16px;
    }

    .topic-name {
        font-size: 14px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .bar {
        height: 6px;
        border-radius: var(--radius-pill);
        background: var(--border);
        overflow: hidden;
    }

    .bar-fill {
        height: 100%;
        border-radius: var(--radius-pill);
        background: var(--performance);
    }

    .topic-frac {
        font-family: var(--font-mono);
        font-size: 13px;
        color: var(--muted);
        text-align: right;
        font-variant-numeric: tabular-nums;
    }

    .cards {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .card {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: 18px 20px;
        box-shadow: var(--shadow-card);
    }

    .card-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }

    .card-title {
        margin: 0;
        font-size: 15px;
        font-weight: 600;
        letter-spacing: -0.01em;
    }

    .count-chip {
        flex: 0 0 auto;
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--muted);
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        padding: 3px 10px;
        white-space: nowrap;

        &.save {
            color: var(--performance-text);
            border-color: var(--performance-tint);
        }
    }

    .evidence {
        margin: 8px 0 0;
        font-size: 14px;
        line-height: 1.6;
        color: var(--muted);

        :global(p) {
            margin: 0;
        }
    }

    .footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        margin-top: auto;
        padding-top: 36px;
    }

    .selector-note {
        font-size: 13px;
        color: var(--muted);
        opacity: 0.75;
    }

    .done {
        background: var(--action-bg);
        color: var(--action-fg);
        border: none;
        border-radius: 10px;
        padding: 11px 24px;
        font-family: var(--font-ui);
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            background: var(--action-bg-hover);
        }
    }

    @media (max-width: 640px) {
        .score {
            font-size: 36px;
        }

        .topic-row {
            grid-template-columns: 110px 1fr 52px;
            gap: 12px;
        }
    }
</style>
