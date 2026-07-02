<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Home (L2.2). The honest Memory card: P(recall now) as a point, an 80%
likely range, a how-sure read, and a per-topic breakdown that abstains where
data is thin. Memory is amber. Pure math over FSRS state and tags, no AI.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import { pgrepCall } from "./lib/bridge";

    interface TopicScore {
        category: string;
        blueprint: number;
        point: number | null;
        low: number | null;
        high: number | null;
        n_cards: number;
        abstain: boolean;
        reason: string | null;
    }

    interface OverallScore {
        point: number | null;
        low: number | null;
        high: number | null;
        abstain: boolean;
        reason: string | null;
    }

    interface MemoryData {
        overall: OverallScore;
        by_topic: TopicScore[];
        k_mem: number;
        last_updated: number | null;
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

    let data: MemoryData | null = null;
    let loading = true;
    let seeding = false;
    let errored = false;

    async function load(): Promise<void> {
        loading = true;
        errored = false;
        try {
            data = await pgrepCall<MemoryData>("pgrepMemoryScore", {});
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

    function howSure(low: number, high: number): string {
        const width = high - low;
        if (width <= 0.12) {
            return "Fairly sure.";
        }
        if (width <= 0.25) {
            return "Roughly sure.";
        }
        return "Not very sure.";
    }

    $: topics = data ? data.by_topic : [];
    $: scoredCount = topics.filter((t) => !t.abstain).length;
    $: anyCards = topics.some((t) => t.n_cards > 0);
</script>

<section class="home">
    <header class="head">
        <h1>Memory</h1>
        <p class="sub">How much is in your head right now.</p>
    </header>

    {#if loading}
        <p class="muted">Loading Memory.</p>
    {:else if errored}
        <div class="card">
            <p>Could not load Memory.</p>
            <button class="btn" on:click={load}>Try again</button>
        </div>
    {:else if data}
        {@const o = data.overall}
        <div class="card memory">
            {#if o.point !== null}
                {@const low = o.low ?? 0}
                {@const high = o.high ?? 0}
                <div class="num">{pct(o.point)}<span class="pctsign">%</span></div>
                <p class="range">likely {pct(low)} to {pct(high)}.</p>
                <div class="rangebar" aria-hidden="true">
                    <div
                        class="band"
                        style="left: {pct(low)}%; right: {100 - pct(high)}%"
                    ></div>
                    <div class="marker" style="left: {pct(o.point)}%"></div>
                </div>
                <p class="reads">
                    <span>{howSure(low, high)}</span>
                    <span class="muted"
                        >Scored over {scoredCount} of {topics.length} topics.</span
                    >
                    {#if data.last_updated !== null}
                        <span class="muted">Updated just now.</span>
                    {/if}
                </p>
            {:else}
                <p class="abstain">{anyCards ? "Not enough cards yet." : "No cards yet."}</p>
                <p class="muted">
                    {anyCards
                        ? "Review a few more cards to see your Memory."
                        : "Seed sample content to see your Memory."}
                </p>
            {/if}
        </div>

        <ul class="topics">
            {#each topics as topic (topic.category)}
                <li class="topic" class:abstained={topic.abstain}>
                    <div class="row">
                        <span class="name">{label(topic.category)}</span>
                        <span class="value">
                            {#if topic.point !== null}
                                {pct(topic.point)}%
                            {:else}
                                <span class="muted small">
                                    {topic.reason ?? "Not enough cards yet."}
                                </span>
                            {/if}
                        </span>
                    </div>
                    <div class="bar" aria-hidden="true">
                        {#if topic.point !== null}
                            <div class="fill" style="width: {pct(topic.point)}%"></div>
                        {/if}
                    </div>
                    <div class="rowsub muted small">
                        <span>{cardCount(topic.n_cards)}</span>
                        {#if topic.point !== null}
                            <span>likely {pct(topic.low ?? 0)} to {pct(topic.high ?? 0)}</span>
                        {/if}
                    </div>
                </li>
            {/each}
        </ul>

        <div class="actions">
            <button class="btn" on:click={seed} disabled={seeding}>
                {seeding ? "Seeding sample content" : "Seed sample content"}
            </button>
            <span class="muted small">Topics need {data.k_mem} cards to score.</span>
        </div>
    {/if}
</section>

<style lang="scss">
    .home {
        // Memory is amber. Readable on both themes (text-on-light and fill).
        --memory-accent: #a9752a;

        max-width: 640px;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }

    :global(.night-mode) .home {
        --memory-accent: #ebcb8b;
    }

    .head {
        h1 {
            margin: 0;
            font-size: 1.25rem;
            color: var(--memory-accent);
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

    .memory {
        border-left: 3px solid var(--memory-accent);
    }

    .num {
        font-size: 3rem;
        font-weight: 650;
        line-height: 1;
        font-variant-numeric: tabular-nums;

        .pctsign {
            font-size: 1.25rem;
            font-weight: 500;
            margin-left: 0.15rem;
            color: var(--fg-subtle);
        }
    }

    .range {
        margin: 0.5rem 0 0;
        font-variant-numeric: tabular-nums;
    }

    .rangebar {
        position: relative;
        height: 10px;
        margin-top: 0.6rem;
        background: var(--canvas-inset, var(--canvas));
        border: 1px solid var(--border);
        border-radius: 999px;

        .band {
            position: absolute;
            top: 0;
            bottom: 0;
            background: var(--memory-accent);
            opacity: 0.3;
            border-radius: 999px;
        }

        .marker {
            position: absolute;
            top: -2px;
            bottom: -2px;
            width: 2px;
            background: var(--memory-accent);
        }
    }

    .reads {
        display: flex;
        flex-wrap: wrap;
        gap: 0.25rem 1rem;
        margin: 0.7rem 0 0;
    }

    .abstain {
        margin: 0;
        font-size: 1.25rem;
        font-weight: 600;
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

        &.abstained {
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

        .value {
            font-variant-numeric: tabular-nums;
        }
    }

    .bar {
        height: 6px;
        margin: 0.4rem 0;
        background: var(--canvas-inset, var(--canvas));
        border: 1px solid var(--border);
        border-radius: 999px;
        overflow: hidden;

        .fill {
            height: 100%;
            background: var(--memory-accent);
            opacity: 0.6;
        }
    }

    .rowsub {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
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
            border-color: var(--memory-accent);
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
