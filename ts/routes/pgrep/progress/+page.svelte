<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Progress (L2.4). The coverage ledger: how much of the blueprint you have
started on (a segmented bar, one segment per category weighted by the blueprint,
filled when covered), the overall fraction against the Readiness gate, and a
per-category list that reuses each topic's Memory point. Calibration lives here
too, but abstains until the model has enough graded predictions to plot. Pure
math over FSRS state and tags, no AI. Styled with the pgrep design system
(CoverageBar, ReliabilityDiagram); the pgrepCall data flow is unchanged.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import CoverageBar from "$lib/components/CoverageBar.svelte";
    import ReliabilityDiagram from "$lib/components/ReliabilityDiagram.svelte";

    import { pgrepCall } from "../lib/bridge";

    interface CoverageTopic {
        category: string;
        blueprint: number;
        covered: boolean;
        n_cards: number;
        memory_point: number | null;
    }

    interface CoverageData {
        overall_pct: number;
        gate: number;
        by_topic: CoverageTopic[];
        abstain_note: string;
    }

    const CATEGORY_LABELS: Record<string, string> = {
        mechanics: "Mechanics",
        electromagnetism: "Electromagnetism",
        quantum: "Quantum",
        thermodynamics: "Thermodynamics",
        atomic: "Atomic physics",
        optics_waves: "Optics and waves",
        special_relativity: "Special relativity",
        lab: "Lab methods",
        specialized: "Specialized",
    };

    let data: CoverageData | null = null;
    let loading = true;
    let seeding = false;
    let errored = false;

    async function load(): Promise<void> {
        loading = true;
        errored = false;
        try {
            data = await pgrepCall<CoverageData>("pgrepCoverage", {});
        } catch {
            errored = true;
        } finally {
            loading = false;
        }
    }

    async function seed(): Promise<void> {
        seeding = true;
        errored = false;
        try {
            await pgrepCall("pgrepSeed", {});
            await load();
        } catch {
            errored = true;
        } finally {
            seeding = false;
        }
    }

    onMount(load);

    function pct(value: number): number {
        return Math.round(value * 100);
    }

    function label(slug: string): string {
        return CATEGORY_LABELS[slug] ?? slug.replace(/_/g, " ");
    }

    function cardCount(n: number): string {
        return `${n} ${n === 1 ? "card" : "cards"}`;
    }

    $: topics = data ? data.by_topic : [];
    $: coveredCount = topics.filter((t) => t.covered).length;
    $: anyCards = topics.some((t) => t.n_cards > 0);
    $: segments = topics.map((t) => ({ topic: label(t.category), weight: t.blueprint, covered: t.covered ? 1 : 0 }));
</script>

<section class="progress">
    <header class="head">
        <div class="head-text">
            <h1>Progress</h1>
            <p class="sub">Coverage gates Readiness. Calibration shows how honest the model is.</p>
        </div>
        <a class="diag-link" href="/pgrep/diagnostic">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="2,10 5.5,10 8,4.5 12,15.5 14.5,10 18,10" />
            </svg>
            Run the diagnostic
        </a>
    </header>

    {#if loading}
        <p class="muted">Loading coverage.</p>
    {:else if errored}
        <div class="panel notice">
            <p class="lead">Could not load coverage.</p>
            <button class="btn" on:click={load}>Try again</button>
        </div>
    {:else if data}
        <div class="panel">
            <div class="panel-head">
                <h2>Coverage</h2>
                <span class="count">{coveredCount} of {topics.length} categories started</span>
            </div>

            <CoverageBar
                {segments}
                coveredPct={pct(data.overall_pct)}
                threshold={pct(data.gate)}
                note={data.abstain_note}
            />

            <ul class="topics">
                {#each topics as topic (topic.category)}
                    <li class="topic" class:uncovered={!topic.covered}>
                        <div class="row">
                            <span class="name">{label(topic.category)}</span>
                            <span class="status" class:on={topic.covered}>
                                {topic.covered ? "Covered" : "Not covered"}
                            </span>
                        </div>
                        <div class="rowsub">
                            <span>Blueprint {pct(topic.blueprint)} percent</span>
                            <span>{cardCount(topic.n_cards)}</span>
                            {#if topic.memory_point !== null}
                                <span class="mem">Memory {pct(topic.memory_point)} percent</span>
                            {/if}
                        </div>
                    </li>
                {/each}
            </ul>

            {#if !anyCards}
                <p class="muted small seed-hint">Seed sample content to see your coverage.</p>
            {/if}

            <div class="actions">
                <button class="btn" on:click={seed} disabled={seeding}>
                    {seeding ? "Seeding sample content" : "Seed sample content"}
                </button>
                <span class="muted small">A category counts once it has one reviewed card.</span>
            </div>
        </div>

        <div class="panel">
            <div class="panel-head">
                <h2>Calibration</h2>
                <span class="count">Performance model</span>
            </div>
            <div class="calib">
                <ReliabilityDiagram points={[]} read="Not enough graded reviews yet" tone="performance" />
                <p class="muted small calib-note">
                    Calibration compares the model's predicted chance of a correct answer against what actually
                    happened. The closer the line sits to the diagonal, the more honest the model. It appears once
                    you have enough graded reviews.
                </p>
            </div>
        </div>
    {/if}
</section>

<style lang="scss">
    .progress {
        max-width: 680px;
        margin: 0 auto;
        padding: 48px 24px 64px;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .head {
        margin-bottom: var(--space-1);
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--space-2);

        h1 {
            margin: 0;
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        .sub {
            margin: 6px 0 0;
            color: var(--muted);
            font-size: var(--text-body);
        }
    }

    /* Diagnostic is a re-runnable flow, not a rail tab. Progress hosts a quiet
       monochrome re-run entry beside the coverage it informs. */
    .diag-link {
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px;
        border: var(--hairline);
        border-radius: var(--radius-control);
        color: var(--muted);
        text-decoration: none;
        font-size: var(--text-body);
        font-weight: 500;
        white-space: nowrap;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
            border-color: var(--muted);
        }
    }

    .panel {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
    }

    .panel-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--space-2);
        margin-bottom: var(--space-2);

        h2 {
            margin: 0;
            font-size: var(--text-emphasis);
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        .count {
            font-size: var(--text-small);
            color: var(--muted);
            font-variant-numeric: tabular-nums;
        }
    }

    .topics {
        list-style: none;
        margin: var(--space-2) 0 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .topic {
        padding: 12px 14px;
        border: var(--hairline);
        border-radius: var(--radius-row);

        &.uncovered {
            opacity: 0.68;
        }
    }

    .row {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--space-2);

        .name {
            font-weight: 500;
            font-size: var(--text-body);
        }

        .status {
            font-size: var(--text-small);
            color: var(--muted);

            &.on {
                color: var(--text);
                font-weight: 500;
            }
        }
    }

    .rowsub {
        display: flex;
        gap: var(--space-2);
        flex-wrap: wrap;
        margin-top: 6px;
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;

        .mem {
            color: var(--memory-text);
        }
    }

    .calib {
        display: flex;
        gap: var(--space-3);
        align-items: center;
        flex-wrap: wrap;
    }

    .calib-note {
        flex: 1 1 240px;
        min-width: 220px;
        line-height: 1.55;
    }

    .actions {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
        margin-top: var(--space-2);
    }

    .seed-hint {
        margin: var(--space-2) 0 0;
    }

    .notice {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--space-1);
    }

    .lead {
        margin: 0;
        font-size: var(--text-emphasis);
        font-weight: 600;
    }

    .muted {
        color: var(--muted);
    }

    .small {
        font-size: var(--text-small);
    }

    .btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 16px;
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        border-radius: var(--radius-control);
        border: var(--hairline);
        background: var(--surface);
        color: var(--text);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            background: var(--hover-wash);
            border-color: var(--muted);
        }

        &:disabled {
            cursor: default;
            opacity: 0.55;
        }
    }
</style>
