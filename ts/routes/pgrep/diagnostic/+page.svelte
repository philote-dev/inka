<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Diagnostic v0 (L2.3). A light, re-runnable placement flow. Step through the
blueprint topics a few at a time and answer one objective quick check each, then
place every topic strong or rusty. Placement combines the fresh quick check with
the FSRS-R Memory prior on the backend. The persona is post-undergraduate, so
there is no cold bucket. No AI, no confidence or self-rating.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import { pgrepCall } from "../lib/bridge";

    type Placement = "strong" | "rusty";

    interface DiagnosticTopic {
        category: string;
        blueprint: number;
        placement: Placement | null;
        n_cards: number;
    }

    interface TopicsData {
        topics: DiagnosticTopic[];
    }

    interface PlacedTopic {
        category: string;
        placement: Placement;
    }

    interface PlaceData {
        topics: PlacedTopic[];
    }

    interface QuickCheck {
        prompt: string;
        choices: string[];
        answer: number;
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

    // One objective, single-answer quick check per category. These are checks
    // with a correct answer, never a confidence or self-rating.
    const QUICK_CHECKS: Record<string, QuickCheck> = {
        mechanics: {
            prompt: "A ball is dropped from rest. Ignoring air resistance, its speed after a time t is",
            choices: ["g t", "half g t squared", "2 g t", "g t squared"],
            answer: 0,
        },
        electromagnetism: {
            prompt: "The electric field from a point charge changes with distance r as",
            choices: ["1 over r", "1 over r squared", "1 over r cubed", "it stays constant"],
            answer: 1,
        },
        quantum: {
            prompt: "The commutator of position and momentum, written [x, p], equals",
            choices: ["0", "i h-bar", "h-bar", "1"],
            answer: 1,
        },
        thermodynamics: {
            prompt: "For an ideal gas, the pressure times the volume P V equals",
            choices: ["n R T", "n R over T", "R T over n", "n R T squared"],
            answer: 0,
        },
        atomic: {
            prompt: "The energy of a photon of frequency f is",
            choices: ["h f", "h over f", "f over h", "h f squared"],
            answer: 0,
        },
        optics_waves: {
            prompt: "For any wave, the speed equals the frequency times the",
            choices: ["wavelength", "period", "amplitude", "phase"],
            answer: 0,
        },
        special_relativity: {
            prompt: "As the speed approaches the speed of light, the Lorentz factor gamma",
            choices: ["approaches 1", "approaches 0", "grows without bound", "stays constant"],
            answer: 2,
        },
        lab: {
            prompt: "Averaging N independent measurements shrinks the standard error by a factor of",
            choices: ["N", "the square root of N", "N squared", "1"],
            answer: 1,
        },
        specialized: {
            prompt: "After one half-life, the amount of a radioactive sample falls to",
            choices: ["one half", "one quarter", "zero", "1 over e"],
            answer: 0,
        },
    };

    // A few topics per step, so the flow steps through rather than showing all at once.
    const BATCH_SIZE = 3;

    type Screen = "loading" | "intro" | "check" | "results" | "error";

    let screen: Screen = "loading";
    let topicsData: TopicsData | null = null;
    let placeData: PlaceData | null = null;
    let busy = false;

    // category -> selected choice index for the current pass.
    let answers: Record<string, number> = {};
    let stepIndex = 0;

    interface CheckItem extends QuickCheck {
        category: string;
    }

    async function loadTopics(): Promise<void> {
        screen = "loading";
        try {
            topicsData = await pgrepCall<TopicsData>("pgrepDiagnosticTopics", {});
            screen = "intro";
        } catch {
            screen = "error";
        }
    }

    onMount(loadTopics);

    function label(slug: string): string {
        return CATEGORY_LABELS[slug] ?? slug.replace(/_/g, " ");
    }

    function startCheck(): void {
        answers = {};
        stepIndex = 0;
        placeData = null;
        screen = "check";
    }

    function pick(category: string, choice: number): void {
        answers = { ...answers, [category]: choice };
    }

    function back(): void {
        if (stepIndex > 0) {
            stepIndex -= 1;
        } else {
            screen = "intro";
        }
    }

    function next(): void {
        if (stepIndex < batches.length - 1) {
            stepIndex += 1;
        }
    }

    async function submit(): Promise<void> {
        if (busy) {
            return;
        }
        busy = true;
        const results = checks
            .filter((c) => answers[c.category] !== undefined)
            .map((c) => ({
                category: c.category,
                outcome: answers[c.category] === c.answer ? "correct" : "wrong",
            }));
        try {
            placeData = await pgrepCall<PlaceData>("pgrepDiagnosticPlace", { results });
            screen = "results";
        } catch {
            screen = "error";
        } finally {
            busy = false;
        }
    }

    $: checks = (() => {
        const out: CheckItem[] = [];
        for (const t of topicsData?.topics ?? []) {
            const check = QUICK_CHECKS[t.category];
            if (check) {
                out.push({ category: t.category, ...check });
            }
        }
        return out;
    })();

    $: batches = (() => {
        const out: CheckItem[][] = [];
        for (let i = 0; i < checks.length; i += BATCH_SIZE) {
            out.push(checks.slice(i, i + BATCH_SIZE));
        }
        return out;
    })();

    $: currentBatch = batches[stepIndex] ?? [];
    $: batchComplete = currentBatch.every((c) => answers[c.category] !== undefined);
    $: isLastStep = stepIndex >= batches.length - 1;
    $: priorPlaced = (topicsData?.topics ?? []).filter((t) => t.placement !== null);
    $: strongCount = placeData
        ? placeData.topics.filter((t) => t.placement === "strong").length
        : 0;
</script>

<section class="diagnostic">
    <header class="head">
        <h1>Diagnostic</h1>
        <p class="sub">Place each topic strong or rusty.</p>
    </header>

    {#if screen === "loading"}
        <p class="muted">Loading the diagnostic.</p>
    {:else if screen === "error"}
        <div class="card">
            <p>Something went wrong.</p>
            <button class="btn" on:click={loadTopics}>Try again</button>
        </div>
    {:else if screen === "intro"}
        <div class="card intro">
            <p class="lead">Answer one quick check per topic.</p>
            <p class="muted">
                We combine each answer with what your reviews already show, then place every
                topic strong or rusty. Run it again whenever you like.
            </p>
        </div>

        {#if priorPlaced.length > 0}
            <div class="prior">
                <p class="muted small">Your last placement</p>
                <ul class="grid">
                    {#each priorPlaced as topic (topic.category)}
                        <li class="chip" class:strong={topic.placement === "strong"} class:rusty={topic.placement === "rusty"}>
                            <span class="chip-name">{label(topic.category)}</span>
                            <span class="pill">{topic.placement}</span>
                        </li>
                    {/each}
                </ul>
            </div>
        {/if}

        <div class="actions">
            <button class="btn primary" on:click={startCheck}>
                {priorPlaced.length > 0 ? "Run again" : "Start"}
            </button>
        </div>
    {:else if screen === "check"}
        <div class="progressrow muted small">
            <span>Step {stepIndex + 1} of {batches.length}</span>
        </div>

        <ol class="questions">
            {#each currentBatch as item (item.category)}
                <li class="question">
                    <div class="qtopic">{label(item.category)}</div>
                    <div class="qprompt">{item.prompt}</div>
                    <ul class="choices">
                        {#each item.choices as choice, i}
                            <li>
                                <button
                                    class="choice"
                                    class:picked={answers[item.category] === i}
                                    on:click={() => pick(item.category, i)}
                                >
                                    <span class="letter">{String.fromCharCode(65 + i)}</span>
                                    <span class="choice-text">{choice}</span>
                                </button>
                            </li>
                        {/each}
                    </ul>
                </li>
            {/each}
        </ol>

        <div class="actions">
            <button class="btn ghost" on:click={back} disabled={busy}>Back</button>
            {#if isLastStep}
                <button class="btn primary" on:click={submit} disabled={!batchComplete || busy}>
                    {busy ? "Placing" : "See placement"}
                </button>
            {:else}
                <button class="btn primary" on:click={next} disabled={!batchComplete}>Next</button>
            {/if}
            <span class="muted small">Pick an answer for each check to continue.</span>
        </div>
    {:else if screen === "results" && placeData}
        <div class="card summary">
            <p class="lead">{strongCount} of {placeData.topics.length} topics placed strong.</p>
            <p class="muted small">Saved. Reviews keep refining this, and you can run it again.</p>
        </div>

        <ul class="grid">
            {#each placeData.topics as topic (topic.category)}
                <li class="chip" class:strong={topic.placement === "strong"} class:rusty={topic.placement === "rusty"}>
                    <span class="chip-name">{label(topic.category)}</span>
                    <span class="pill">{topic.placement}</span>
                </li>
            {/each}
        </ul>

        <div class="legend muted small" aria-hidden="true">
            <span class="key"><span class="swatch strong"></span> strong</span>
            <span class="key"><span class="swatch rusty"></span> rusty, needs work</span>
        </div>

        <div class="actions">
            <button class="btn primary" on:click={startCheck}>Run again</button>
        </div>
    {/if}
</section>

<style lang="scss">
    .diagnostic {
        // Diagnostic is violet, distinct from Memory amber and Coverage green.
        --diagnostic-accent: #6b4fa3;
        --strong-accent: #2f7d57;
        --rusty-accent: #a9752a;

        max-width: 680px;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }

    :global(.night-mode) .diagnostic {
        --diagnostic-accent: #b48ead;
        --strong-accent: #8fce9f;
        --rusty-accent: #ebcb8b;
    }

    .head {
        h1 {
            margin: 0;
            font-size: 1.25rem;
            color: var(--diagnostic-accent);
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

    .intro {
        border-left: 3px solid var(--diagnostic-accent);
    }

    .summary {
        border-left: 3px solid var(--strong-accent);
    }

    .lead {
        margin: 0 0 0.25rem;
        font-size: 1.1rem;
        font-weight: 600;
    }

    .prior {
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }

    .progressrow {
        display: flex;
        justify-content: space-between;
    }

    .questions {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .question {
        padding: 0.75rem 0.9rem;
        background: var(--canvas-elevated);
        border: 1px solid var(--border);
        border-radius: var(--border-radius-medium, 12px);
        border-left: 3px solid var(--diagnostic-accent);

        .qtopic {
            font-size: 0.8rem;
            font-weight: 550;
            color: var(--diagnostic-accent);
        }

        .qprompt {
            margin: 0.25rem 0 0.6rem;
            font-size: 1.05rem;
            line-height: 1.45;
        }
    }

    .choices {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }

    .choice {
        display: flex;
        gap: 0.6rem;
        align-items: baseline;
        width: 100%;
        text-align: left;
        padding: 0.45rem 0.7rem;
        color: var(--fg);
        background: var(--canvas);
        border: 1px solid var(--border);
        border-radius: var(--border-radius, 6px);
        cursor: pointer;

        &:hover {
            border-color: var(--diagnostic-accent);
        }

        &.picked {
            border-color: var(--diagnostic-accent);
            box-shadow: inset 0 0 0 1px var(--diagnostic-accent);
        }

        .letter {
            font-weight: 700;
            min-width: 1.1rem;
            color: var(--fg-subtle);
        }
    }

    .grid {
        list-style: none;
        margin: 0;
        padding: 0;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
        gap: 0.5rem;
    }

    .chip {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 0.7rem;
        background: var(--canvas-elevated);
        border: 1px solid var(--border);
        border-radius: var(--border-radius, 6px);
        border-left: 3px solid var(--border);

        &.strong {
            border-left-color: var(--strong-accent);
        }

        &.rusty {
            border-left-color: var(--rusty-accent);
        }

        .chip-name {
            font-weight: 550;
        }

        .pill {
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            color: var(--fg-subtle);
        }

        &.strong .pill {
            color: var(--strong-accent);
        }

        &.rusty .pill {
            color: var(--rusty-accent);
        }
    }

    .legend {
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem 1rem;
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
            background: var(--border);

            &.strong {
                background: var(--strong-accent);
            }

            &.rusty {
                background: var(--rusty-accent);
            }
        }
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
            border-color: var(--diagnostic-accent);
        }

        &:disabled {
            cursor: default;
            opacity: 0.6;
        }

        &.primary {
            border-color: var(--diagnostic-accent);
        }

        &.ghost {
            background: transparent;
        }
    }

    .muted {
        color: var(--fg-subtle);
    }

    .small {
        font-size: 0.85rem;
    }
</style>
