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
    import { onDestroy } from "svelte";

    import { renderMath } from "$lib/pgrep/math";
    import { noDashes } from "$lib/pgrep/text";

    import ChoiceList from "./ChoiceList.svelte";

    export let index = 1; // 1-based, for the step count
    export let total = 1;
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

    $: renderedStem = stemHtml ? renderMath(noDashes(stemHtml)) : "";
    $: renderedRationale = mcqRationaleHtml
        ? renderMath(noDashes(mcqRationaleHtml))
        : "";
    $: renderedExplainWhy = explainWhyHtml ? renderMath(noDashes(explainWhyHtml)) : "";
    $: locked = phase !== "mcq";

    // Anti-spam. Shuffle and re-letter the MCQ on each retry so cycling by
    // position or a remembered letter both fail, and hold the Check button after
    // a burst of rapid wrong picks. The hold grows while the burst continues and
    // re-arms on release, so a spammer who resumes at once is caught again (and
    // longer), while a considered gap forgets the burst entirely. The display
    // letter maps back to the stored key before onSelect, so grading is
    // unchanged. Presentational only; scoring already excludes tutor retries.
    const LETTERS = ["A", "B", "C", "D", "E"];
    const RAPID_MS = 4000; // a second Check this soon after the last is "rapid"
    const RAPID_LIMIT = 2; // rapid checks in a row before the button holds
    const HOLD_BASE_MS = 4000; // first hold; each hold in the burst adds a step
    const HOLD_STEP_MS = 3000;

    function shuffle(keys: string[]): string[] {
        const a = [...keys];
        for (let i = a.length - 1; i > 0; i -= 1) {
            const j = Math.floor(Math.random() * (i + 1));
            [a[i], a[j]] = [a[j], a[i]];
        }
        return a;
    }

    let order: string[] = [];
    let shuffledForIndex = -1;
    let lastRationale = "";
    let lastCheckAt = 0;
    let rapidCount = 0;
    let holdCount = 0;
    let held = false;
    let holdTimer: ReturnType<typeof setTimeout> | undefined;
    let nudge = "";

    $: trueKeys = choices.map((c) => c.key);
    $: byHtml = new Map(choices.map((c) => [c.key, c.html]));

    // A fresh subproblem: shuffle once and clear the anti-spam counters.
    $: if (index !== shuffledForIndex && trueKeys.length) {
        shuffledForIndex = index;
        order = shuffle(trueKeys);
        lastRationale = "";
        lastCheckAt = 0;
        rapidCount = 0;
        holdCount = 0;
        held = false;
        nudge = "";
        clearTimeout(holdTimer);
    }

    // A new wrong pick: reshuffle so the next attempt cannot be cycled by position.
    $: if (mcqRationaleHtml !== lastRationale) {
        lastRationale = mcqRationaleHtml;
        if (mcqRationaleHtml && trueKeys.length) {
            order = shuffle(trueKeys);
        }
    }

    $: safeOrder =
        order.length === trueKeys.length && order.every((k) => byHtml.has(k))
            ? order
            : trueKeys;
    $: displayChoices = safeOrder.map((trueKey, pos) => ({
        key: LETTERS[pos] ?? trueKey,
        trueKey,
        html: noDashes(byHtml.get(trueKey) ?? ""),
    }));
    $: selectedDisplay = displayChoices.find((d) => d.trueKey === selected)?.key ?? "";
    $: correctDisplay = correctKey
        ? (displayChoices.find((d) => d.trueKey === correctKey)?.key ?? null)
        : null;

    function selectDisplay(displayKey: string): void {
        const d = displayChoices.find((x) => x.key === displayKey);
        if (d) {
            onSelect?.(d.trueKey);
        }
    }

    function handleCheck(): void {
        if (held) {
            return;
        }
        const now = Date.now();
        const rapid = lastCheckAt !== 0 && now - lastCheckAt < RAPID_MS;
        lastCheckAt = now;
        if (rapid) {
            rapidCount += 1;
        } else {
            // A considered gap: forget the burst and its escalation.
            rapidCount = 0;
            holdCount = 0;
        }
        if (rapidCount >= RAPID_LIMIT) {
            holdCount += 1;
            held = true;
            nudge = "Slow down and read the options. You can try again in a moment.";
            clearTimeout(holdTimer);
            holdTimer = setTimeout(
                () => {
                    held = false;
                    nudge = "";
                    // Re-arm: restart the clock and leave the burst one short of
                    // the limit, so an immediate repeat holds again, and longer.
                    lastCheckAt = Date.now();
                    rapidCount = RAPID_LIMIT - 1;
                },
                HOLD_BASE_MS + HOLD_STEP_MS * (holdCount - 1),
            );
            return;
        }
        nudge = "";
        onCheck?.();
    }

    // The AI feedback types out letter by letter, as if the tutor is speaking
    // back. Reduced motion shows it at once.
    let displayedFeedback = "";
    let typeTimer: ReturnType<typeof setInterval> | undefined;
    const reduceMotion =
        typeof window !== "undefined" &&
        !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    $: cleanFeedback = feedback ? noDashes(feedback) : "";
    function runTypewriter(text: string): void {
        clearInterval(typeTimer);
        if (!text) {
            displayedFeedback = "";
            return;
        }
        if (reduceMotion) {
            displayedFeedback = text;
            return;
        }
        displayedFeedback = "";
        let i = 0;
        typeTimer = setInterval(() => {
            i += 1;
            displayedFeedback = text.slice(0, i);
            if (i >= text.length) {
                clearInterval(typeTimer);
            }
        }, 16);
    }
    $: runTypewriter(cleanFeedback);

    // The wrong-pick rationale (the red hint) types out too. It can carry math,
    // so instead of typing raw HTML it reveals the already-rendered markup: text
    // nodes appear a character at a time and each KaTeX block appears whole
    // (typing an equation's glyphs would look broken). Cheap: one small DOM write
    // per tick, and the math is rendered once up front, never re-rendered.
    function revealHtml(root: HTMLElement): ReturnType<typeof setInterval> | undefined {
        type Unit =
            | { kind: "text"; node: Text; text: string; upto: number }
            | { kind: "el"; el: HTMLElement };
        const units: Unit[] = [];
        const visit = (node: Node): void => {
            for (const child of Array.from(node.childNodes)) {
                if (child.nodeType === Node.TEXT_NODE) {
                    const tn = child as Text;
                    const text = tn.data;
                    tn.data = "";
                    for (let i = 1; i <= text.length; i += 1) {
                        units.push({ kind: "text", node: tn, text, upto: i });
                    }
                } else if (child.nodeType === Node.ELEMENT_NODE) {
                    const el = child as HTMLElement;
                    if (
                        el.classList.contains("katex") ||
                        el.classList.contains("katex-display")
                    ) {
                        el.style.visibility = "hidden";
                        units.push({ kind: "el", el });
                    } else {
                        visit(el);
                    }
                }
            }
        };
        visit(root);
        if (!units.length) {
            return undefined;
        }
        let i = 0;
        const timer = setInterval(() => {
            const u = units[i];
            if (u.kind === "text") {
                u.node.data = u.text.slice(0, u.upto);
            } else {
                u.el.style.visibility = "visible";
            }
            i += 1;
            if (i >= units.length) {
                clearInterval(timer);
            }
        }, 14);
        return timer;
    }

    function typeHtml(node: HTMLElement, html: string) {
        let timer: ReturnType<typeof setInterval> | undefined;
        const render = (h: string): void => {
            clearInterval(timer);
            node.innerHTML = h;
            if (h && !reduceMotion) {
                timer = revealHtml(node);
            }
        };
        render(html);
        return {
            update(h: string): void {
                render(h);
            },
            destroy(): void {
                clearInterval(timer);
            },
        };
    }

    onDestroy(() => {
        clearInterval(typeTimer);
        clearTimeout(holdTimer);
    });
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

    <div class="sub-stem">{@html renderedStem}</div>

    <ChoiceList
        choices={displayChoices}
        selected={selectedDisplay}
        committed={locked}
        correctKey={locked ? correctDisplay : null}
        onSelect={locked ? undefined : selectDisplay}
    />

    {#if phase === "mcq"}
        {#if mcqRationaleHtml}
            <div class="note miss" use:typeHtml={renderedRationale}></div>
            <p class="muted small">Try again.</p>
        {/if}
        <div class="actions">
            <button
                class="btn primary"
                on:click={handleCheck}
                disabled={!selected || busy || held}
            >
                {busy ? "Checking" : "Check"}
            </button>
            {#if nudge}
                <span class="muted small">{nudge}</span>
            {/if}
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
                        Check my explanation
                    </button>
                    {#if busy}
                        <span class="thinking" aria-label="Thinking">
                            <span></span>
                            <span></span>
                            <span></span>
                        </span>
                    {/if}
                </div>
                {#if displayedFeedback}
                    <div class="note {explanationOutcome === 'pass' ? 'pass' : 'try'}">
                        {displayedFeedback}
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
            {#if displayedFeedback}
                <div class="note pass">{displayedFeedback}</div>
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

        /* Experiment: a miss or a failed explanation reads pastel red (diverges
           from the calm-blue honesty rule, under review). */
        &.miss,
        &.try {
            color: var(--error);
            border-color: var(--error-tint);
            background: var(--error-wash);
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

    /* The tutor "thinking" while the AI grades the explanation. */
    .thinking {
        display: inline-flex;
        align-items: center;
        gap: 5px;

        span {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--muted);
            animation: sp-thinking 1.2s infinite ease-in-out both;
        }

        span:nth-child(2) {
            animation-delay: 0.15s;
        }

        span:nth-child(3) {
            animation-delay: 0.3s;
        }
    }

    @keyframes sp-thinking {
        0%,
        80%,
        100% {
            opacity: 0.25;
            transform: translateY(0);
        }
        40% {
            opacity: 1;
            transform: translateY(-3px);
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .thinking span {
            animation: none;
            opacity: 0.6;
        }
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
