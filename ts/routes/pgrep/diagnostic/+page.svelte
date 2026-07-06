<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Diagnostic v0 (L2.3). A light, re-runnable placement flow. Step through the
blueprint topics a few at a time and answer one objective quick check each, then
place every topic strong or rusty. Placement combines the fresh quick check with
the FSRS-R Memory prior on the backend. The persona is post-undergraduate, so
there is no cold bucket. No AI, no confidence or self-rating. Styled with the
pgrep design system (ChoiceList, state colors); the pgrepCall flow is unchanged.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import ChoiceList from "$lib/components/ChoiceList.svelte";

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

    const CHOICE_LETTERS = ["A", "B", "C", "D", "E"];

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
            choices: [
                "1 over r",
                "1 over r squared",
                "1 over r cubed",
                "it stays constant",
            ],
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
            choices: [
                "approaches 1",
                "approaches 0",
                "grows without bound",
                "stays constant",
            ],
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

    function letterFor(index: number): string {
        return CHOICE_LETTERS[index] ?? String(index + 1);
    }

    function choiceItems(item: CheckItem): Array<{ key: string; html: string }> {
        return item.choices.map((c, i) => ({ key: letterFor(i), html: c }));
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

    // The selected letter per category, derived from answers so the highlight
    // stays reactive. A template expression that only calls a helper would track
    // the helper, not answers, so the selection must come from a value that
    // references answers directly.
    $: selectedKeys = Object.fromEntries(
        checks.map((c) => [
            c.category,
            answers[c.category] === undefined ? "" : letterFor(answers[c.category]),
        ]),
    );

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
        <div class="panel notice">
            <p class="lead">Something went wrong.</p>
            <button class="btn" on:click={loadTopics}>Try again</button>
        </div>
    {:else if screen === "intro"}
        <div class="panel">
            <p class="lead">Answer one quick check per topic.</p>
            <p class="muted">
                We combine each answer with what your reviews already show, then place
                every topic strong or rusty. Run it again whenever you like.
            </p>
        </div>

        {#if priorPlaced.length > 0}
            <div class="prior">
                <p class="muted small">Your last placement</p>
                <ul class="grid">
                    {#each priorPlaced as topic (topic.category)}
                        <li
                            class="chip"
                            class:strong={topic.placement === "strong"}
                            class:rusty={topic.placement === "rusty"}
                        >
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
        <div class="progressrow">
            <span class="muted small">Step {stepIndex + 1} of {batches.length}</span>
        </div>

        <ol class="questions">
            {#each currentBatch as item (item.category)}
                <li class="question">
                    <div class="qtopic">{label(item.category)}</div>
                    <div class="qprompt">{item.prompt}</div>
                    <ChoiceList
                        choices={choiceItems(item)}
                        selected={selectedKeys[item.category] ?? ""}
                        committed={false}
                        correctKey={null}
                        onSelect={(key) =>
                            pick(item.category, CHOICE_LETTERS.indexOf(key))}
                    />
                </li>
            {/each}
        </ol>

        <div class="actions">
            <button class="btn ghost" on:click={back} disabled={busy}>Back</button>
            {#if isLastStep}
                <button
                    class="btn primary"
                    on:click={submit}
                    disabled={!batchComplete || busy}
                >
                    {busy ? "Placing" : "See placement"}
                </button>
            {:else}
                <button class="btn primary" on:click={next} disabled={!batchComplete}>
                    Next
                </button>
            {/if}
            <span class="muted small">Pick an answer for each check to continue.</span>
        </div>
    {:else if screen === "results" && placeData}
        <div class="panel">
            <p class="lead">
                {strongCount} of {placeData.topics.length} topics placed strong.
            </p>
            <p class="muted small">
                Saved. Reviews keep refining this, and you can run it again.
            </p>
        </div>

        <ul class="grid">
            {#each placeData.topics as topic (topic.category)}
                <li
                    class="chip"
                    class:strong={topic.placement === "strong"}
                    class:rusty={topic.placement === "rusty"}
                >
                    <span class="chip-name">{label(topic.category)}</span>
                    <span class="pill">{topic.placement}</span>
                </li>
            {/each}
        </ul>

        <div class="legend" aria-hidden="true">
            <span class="key">
                <span class="swatch strong"></span>
                strong
            </span>
            <span class="key">
                <span class="swatch rusty"></span>
                rusty, needs work
            </span>
        </div>

        <div class="actions">
            <button class="btn primary" on:click={startCheck}>Run again</button>
        </div>
    {/if}
</section>

<style lang="scss">
    .diagnostic {
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

    .panel {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
    }

    .notice {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--space-1);
    }

    .lead {
        margin: 0 0 4px;
        font-size: var(--text-emphasis);
        font-weight: 600;
    }

    .prior {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
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
        gap: var(--space-2);
    }

    .question {
        padding: var(--space-2);
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);

        .qtopic {
            font-size: var(--text-caption);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--muted);
        }

        .qprompt {
            margin: 6px 0 var(--space-2);
            font-size: var(--text-content);
            line-height: 1.5;
        }
    }

    .grid {
        list-style: none;
        margin: 0;
        padding: 0;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
        gap: var(--space-1);
    }

    .chip {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: var(--space-1);
        padding: 10px 14px;
        background: var(--surface);
        border: var(--hairline);
        border-left: 3px solid var(--border);
        border-radius: var(--radius-row);

        &.strong {
            border-left-color: var(--success);
        }

        &.rusty {
            border-left-color: var(--caution);
        }

        .chip-name {
            font-weight: 500;
            font-size: var(--text-body);
        }

        .pill {
            font-size: var(--text-caption);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: var(--muted);
        }

        &.strong .pill {
            color: var(--success);
        }

        &.rusty .pill {
            color: var(--caution);
        }
    }

    .legend {
        display: flex;
        flex-wrap: wrap;
        gap: 6px var(--space-2);
        align-items: center;
        font-size: var(--text-small);
        color: var(--muted);

        .key {
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .swatch {
            width: 12px;
            height: 12px;
            border-radius: 3px;
            background: var(--border);

            &.strong {
                background: var(--success);
            }

            &.rusty {
                background: var(--caution);
            }
        }
    }

    .actions {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
        margin-top: var(--space-1);
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

        &.primary {
            background: var(--action-bg);
            color: var(--action-fg);
            border-color: transparent;

            &:hover:not(:disabled) {
                background: var(--action-bg-hover);
            }
        }

        &.ghost {
            background: none;
            border-color: var(--muted);
        }
    }
</style>
