<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep decomposition subproblem. One gated step of the decomposition tutor a
    miss opens (feature-productive-failure.md, redesigned). The learner must
    answer the multiple-choice question correctly to advance (unlimited retries,
    a wrong pick shows only that distractor's rationale, never the key). With AI
    on a short "explain why" is then graded leniently and must pass to continue;
    with AI off that step is skipped. There is no skip control: advance only when
    the step is satisfied. The parent problem's answer is never shown here.

    Presentational: the parent owns the flow and the backend calls, so this
    renders a single step from props and reports actions through callbacks. That
    keeps it demoable in the component gallery without a session.
-->
<script lang="ts">
    import { renderMath } from "$lib/pgrep/math";

    import ChoiceList from "./ChoiceList.svelte";

    export let index = 1; // 1-based, for the step count
    export let total = 1;
    export let prompt = "";
    export let stemHtml = "";
    export let choices: { key: string; html: string }[] = [];
    export let selected = "";
    // mcq: the MCQ is open. explain: MCQ correct, the AI grades the explanation.
    // done: the step is satisfied and the learner may continue.
    export let phase: "mcq" | "explain" | "done" = "mcq";
    export let correctKey: string | null = null;
    export let mcqRationaleHtml = ""; // shown after a wrong pick (blue, never red)
    export let explainWhyHtml = ""; // the model rationale, revealed once satisfied
    export let aiOn = false;
    export let explanation = "";
    export let feedback = "";
    export let explanationOutcome: "pending" | "pass" | "fail" = "pending";
    export let busy = false;
    export let isLast = false;
    export let onSelect: ((key: string) => void) | undefined = undefined;
    export let onCheck: (() => void) | undefined = undefined;
    export let onGrade: (() => void) | undefined = undefined;
    export let onContinue: (() => void) | undefined = undefined;

    $: renderedPrompt = prompt ? renderMath(prompt) : "";
    $: renderedStem = stemHtml ? renderMath(stemHtml) : "";
    $: renderedRationale = mcqRationaleHtml ? renderMath(mcqRationaleHtml) : "";
    $: renderedExplainWhy = explainWhyHtml ? renderMath(explainWhyHtml) : "";
    $: locked = phase !== "mcq";
</script>

<section class="subproblem">
    <header class="sub-head">
        <span class="step">Step {index} of {total}</span>
        <div class="dots" aria-hidden="true">
            {#each Array(total) as _, i (i)}
                <span class="dot" class:on={i < index}></span>
            {/each}
        </div>
    </header>

    {#if prompt}
        <p class="sub-prompt">{@html renderedPrompt}</p>
    {/if}
    <div class="sub-stem">{@html renderedStem}</div>

    <ChoiceList
        {choices}
        {selected}
        committed={locked}
        correctKey={locked ? correctKey : null}
        onSelect={locked ? undefined : onSelect}
    />

    {#if phase === "mcq"}
        {#if mcqRationaleHtml}
            <div class="note miss">{@html renderedRationale}</div>
        {/if}
        <div class="actions">
            <button class="btn primary" on:click={onCheck} disabled={!selected || busy}>
                {busy ? "Checking" : "Check"}
            </button>
            <span class="muted small">
                Answer it correctly to go on. You can retry as many times as you like.
            </span>
        </div>
    {:else}
        <div class="verdict hit">That's right.</div>

        {#if phase === "explain" && aiOn}
            <div class="explain">
                <label for="sp-explanation-{index}">
                    In your own words, why is this the answer?
                </label>
                <textarea
                    id="sp-explanation-{index}"
                    bind:value={explanation}
                    rows="3"
                    placeholder="One or two lines is plenty."
                ></textarea>
                <div class="actions">
                    <button
                        class="btn primary"
                        on:click={onGrade}
                        disabled={busy || !explanation.trim()}
                    >
                        {busy ? "Checking" : "Check my explanation"}
                    </button>
                    <span class="muted small">
                        A good-enough explanation unlocks the next step.
                    </span>
                </div>
                {#if feedback}
                    <div class="note {explanationOutcome === 'pass' ? 'pass' : 'try'}">
                        {feedback}
                    </div>
                {/if}
            </div>
        {/if}

        {#if phase === "done"}
            {#if explainWhyHtml}
                <div class="explain-why">
                    <span class="why-label">Why</span>
                    <div class="why-body">{@html renderedExplainWhy}</div>
                </div>
            {/if}
            {#if feedback}
                <div class="note pass">{feedback}</div>
            {/if}
            <div class="actions">
                <button class="btn primary" on:click={onContinue} disabled={busy}>
                    {isLast ? "Finish" : "Next step"}
                </button>
            </div>
        {/if}
    {/if}
</section>

<style lang="scss">
    .subproblem {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: 24px;
        box-shadow: var(--shadow-card);
        font-family: var(--font-ui);
        color: var(--text);
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
    }

    .sub-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }

    .step {
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .dots {
        display: flex;
        align-items: center;
        gap: 5px;
    }

    .dot {
        width: 7px;
        height: 7px;
        border-radius: var(--radius-pill);
        border: 1px solid var(--muted);
        box-sizing: border-box;

        &.on {
            background: var(--performance);
            border-color: var(--performance);
        }
    }

    .sub-prompt {
        margin: 0;
        font-size: var(--text-body);
        line-height: 1.55;
        color: var(--muted);

        :global(p) {
            margin: 0 0 0.4em;
        }
    }

    .sub-stem {
        font-size: 16px;
        line-height: 1.55;

        :global(p) {
            margin: 0 0 0.5em;
        }
    }

    .verdict {
        font-size: var(--text-body);
        font-weight: 600;

        &.hit {
            color: var(--success);
        }
    }

    .explain {
        display: flex;
        flex-direction: column;
        gap: 8px;

        label {
            font-size: var(--text-small);
            color: var(--muted);
        }

        textarea {
            font-family: var(--font-ui);
            font-size: var(--text-body);
            color: var(--text);
            background: var(--canvas);
            border: var(--hairline);
            border-radius: var(--radius-control);
            padding: 8px 10px;
            resize: vertical;
        }
    }

    .explain-why {
        border-top: var(--hairline);
        padding-top: 14px;

        .why-label {
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--muted);
        }

        .why-body {
            margin-top: 6px;
            font-size: 15px;
            line-height: 1.55;

            :global(p) {
                margin: 0 0 0.5em;
            }
        }
    }

    .note {
        font-size: var(--text-body);
        line-height: 1.55;
        border-radius: var(--radius-control);
        padding: 10px 12px;
        border: var(--hairline);

        :global(p) {
            margin: 0 0 0.5em;

            &:last-child {
                margin-bottom: 0;
            }
        }

        /* Never red during learning. A miss or a "try again" reads calm blue. */
        &.miss,
        &.try {
            color: var(--performance-text);
            border-color: var(--performance-tint);
            background: var(--performance-wash);
        }

        &.pass {
            color: var(--text);
            border-color: var(--success);
            background: var(--success-wash);
        }
    }

    .actions {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
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
        padding: 11px 18px;
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
    }
</style>
