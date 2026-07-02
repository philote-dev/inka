<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Progress (L2.4). The coverage ledger: how much of the blueprint you have
started on. A single segmented bar (one segment per category, width by blueprint
weight, solid when covered and faded when not), the overall covered fraction
against the Readiness gate, and a per-category list that reuses each topic's
Memory point. Pure math over FSRS state and tags, no AI, no D3.
-->
<script lang="ts">
    import { onMount } from "svelte";

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
</script>

<section class="progress">
    <header class="head">
        <h1>Coverage</h1>
        <p class="sub">How much of the exam you have started on.</p>
    </header>

    {#if loading}
        <p class="muted">Loading Coverage.</p>
    {:else if errored}
        <div class="card">
            <p>Could not load Coverage.</p>
            <button class="btn" on:click={load}>Try again</button>
        </div>
    {:else if data}
        <div class="card coverage">
            <div
                class="covbar"
                role="img"
                aria-label={`Coverage ${pct(data.overall_pct)} percent of the blueprint`}
            >
                {#each topics as topic (topic.category)}
                    <div
                        class="seg"
                        class:covered={topic.covered}
                        style="width: {topic.blueprint * 100}%"
                        title={`${label(topic.category)} ${pct(topic.blueprint)}%`}
                    ></div>
                {/each}
            </div>

            <div class="num">
                {pct(data.overall_pct)}<span class="pctsign">%</span>
            </div>
            <p class="readout">
                Coverage {pct(data.overall_pct)}%. Readiness needs {pct(data.gate)}%.
            </p>
            <p class="muted small">{data.abstain_note}</p>

            <div class="legend muted small" aria-hidden="true">
                <span class="key"><span class="swatch covered"></span> covered</span>
                <span class="key"><span class="swatch"></span> not yet</span>
                <span>{coveredCount} of {topics.length} categories started.</span>
            </div>

            {#if !anyCards}
                <p class="muted small">Seed sample content to see your coverage.</p>
            {/if}
        </div>

        <ul class="topics">
            {#each topics as topic (topic.category)}
                <li class="topic" class:uncovered={!topic.covered}>
                    <div class="row">
                        <span class="name">{label(topic.category)}</span>
                        <span class="status" class:on={topic.covered}>
                            {topic.covered ? "Covered" : "Not covered"}
                        </span>
                    </div>
                    <div class="rowsub muted small">
                        <span>Blueprint {pct(topic.blueprint)}%</span>
                        <span>{cardCount(topic.n_cards)}</span>
                        {#if topic.memory_point !== null}
                            <span>Memory {pct(topic.memory_point)}%</span>
                        {/if}
                    </div>
                </li>
            {/each}
        </ul>

        <div class="actions">
            <button class="btn" on:click={seed} disabled={seeding}>
                {seeding ? "Seeding sample content" : "Seed sample content"}
            </button>
            <span class="muted small">A category counts once it has one reviewed card.</span>
        </div>
    {/if}
</section>

<style lang="scss">
    .progress {
        // Coverage is green (started vs not), distinct from Memory amber.
        --coverage-accent: #2f7d57;
        --coverage-faded: #d7e9df;

        max-width: 640px;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }

    :global(.night-mode) .progress {
        --coverage-accent: #8fce9f;
        --coverage-faded: #33413a;
    }

    .head {
        h1 {
            margin: 0;
            font-size: 1.25rem;
            color: var(--coverage-accent);
        }

        .sub {
            margin: 0.15rem 0 0;
            color: var(--fg-subtle);
        }
    }

    .card {
        padding: 1rem 1.1rem;
        background: var(--canvas-elevated);
        border: 1px solid var(--border);
        border-radius: var(--border-radius-medium, 12px);
    }

    .coverage {
        border-left: 3px solid var(--coverage-accent);
    }

    .covbar {
        display: flex;
        height: 16px;
        background: var(--canvas-inset, var(--canvas));
        border: 1px solid var(--border);
        border-radius: 999px;
        overflow: hidden;

        .seg {
            height: 100%;
            background: var(--coverage-faded);
            box-shadow: inset -1px 0 0 var(--canvas);

            &:last-child {
                box-shadow: none;
            }

            &.covered {
                background: var(--coverage-accent);
            }
        }
    }

    .num {
        margin-top: 0.7rem;
        font-size: 2.4rem;
        font-weight: 650;
        line-height: 1;
        font-variant-numeric: tabular-nums;

        .pctsign {
            font-size: 1.1rem;
            font-weight: 500;
            margin-left: 0.15rem;
            color: var(--fg-subtle);
        }
    }

    .readout {
        margin: 0.4rem 0 0;
        font-variant-numeric: tabular-nums;
    }

    .legend {
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem 1rem;
        margin-top: 0.6rem;
        align-items: center;

        .key {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
        }

        .swatch {
            display: inline-block;
            width: 0.8rem;
            height: 0.8rem;
            border-radius: 3px;
            background: var(--coverage-faded);

            &.covered {
                background: var(--coverage-accent);
            }
        }
    }

    .topics {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.6rem;
    }

    .topic {
        padding: 0.6rem 0.75rem;
        background: var(--canvas-elevated);
        border: 1px solid var(--border);
        border-radius: var(--border-radius-medium, 12px);

        &.uncovered {
            opacity: 0.72;
        }
    }

    .row {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 1rem;

        .name {
            font-weight: 550;
        }

        .status {
            font-size: 0.85rem;
            color: var(--fg-subtle);

            &.on {
                color: var(--coverage-accent);
                font-weight: 550;
            }
        }
    }

    .rowsub {
        display: flex;
        gap: 1rem;
        flex-wrap: wrap;
        margin-top: 0.35rem;
        font-variant-numeric: tabular-nums;
    }

    .actions {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        flex-wrap: wrap;
    }

    .btn {
        padding: 0.4rem 0.9rem;
        color: var(--fg);
        background: var(--canvas-elevated);
        border: 1px solid var(--border);
        border-radius: var(--border-radius, 6px);
        cursor: pointer;

        &:hover {
            border-color: var(--coverage-accent);
        }

        &:disabled {
            cursor: default;
            opacity: 0.6;
        }
    }

    .muted {
        color: var(--fg-subtle);
    }

    .small {
        font-size: 0.85rem;
    }
</style>
