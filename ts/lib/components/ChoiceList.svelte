<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep choice list. Monochrome by default, a thin blue outline for the live
    selection. After commit the row locks: the correct choice takes a calm
    success outline, a wrong commit dims and wears a blue "not correct" tag.
    Never red. Ported from the Claude Design export
    (design/ux-foundation.md), extended with the correct-answer
    reveal the committed backend provides.
-->
<script lang="ts">
    import { renderMath } from "$lib/pgrep/math";

    export let choices: Array<{ key: string; html: string }> = [];
    export let selected = "";
    export let committed = false;
    export let correctKey: string | null = null;
    export let onSelect: ((key: string) => void) | undefined = undefined;

    type RowState = "default" | "selected" | "correct" | "wrong" | "locked";

    function rowState(
        key: string,
        sel: string,
        isCommitted: boolean,
        correct: string | null,
    ): RowState {
        if (!isCommitted) {
            return key === sel ? "selected" : "default";
        }
        if (correct && key === correct) {
            return "correct";
        }
        if (key === sel) {
            return "wrong";
        }
        return "locked";
    }

    // Typeset the choice HTML and resolve each row's state here, referencing
    // selected/committed/correctKey directly so Svelte re-runs it the moment the
    // selection changes. A rowState() call inside an {@const} would not re-run on
    // a selection change (the dependency hides inside the function), so the live
    // blue highlight never appeared until commit.
    $: renderedChoices = choices.map((c) => ({
        key: c.key,
        html: renderMath(c.html),
        state: rowState(c.key, selected, committed, correctKey),
    }));

    // The choices are a single-select radio group: one row is tabbable (the
    // selected one, else the first), arrow keys move and select, and a letter
    // key jumps straight to that choice. Committing locks the group.
    const radios: HTMLButtonElement[] = [];

    function pick(index: number): void {
        const choice = choices[index];
        if (!choice || committed) {
            return;
        }
        onSelect?.(choice.key);
        radios[index]?.focus();
    }

    function tabindexFor(key: string, index: number): number {
        if (selected) {
            return key === selected ? 0 : -1;
        }
        return index === 0 ? 0 : -1;
    }

    function onKeydown(event: KeyboardEvent, index: number): void {
        if (committed) {
            return;
        }
        const n = choices.length;
        let target = -1;
        switch (event.key) {
            case "ArrowDown":
            case "ArrowRight":
                target = (index + 1) % n;
                break;
            case "ArrowUp":
            case "ArrowLeft":
                target = (index - 1 + n) % n;
                break;
            case "Home":
                target = 0;
                break;
            case "End":
                target = n - 1;
                break;
            default: {
                const letter = event.key.toUpperCase();
                const found = choices.findIndex((c) => c.key.toUpperCase() === letter);
                if (found >= 0) {
                    target = found;
                }
            }
        }
        if (target >= 0) {
            event.preventDefault();
            pick(target);
        }
    }
</script>

<div class="choices" role="radiogroup" aria-label="Answer choices">
    {#each renderedChoices as c, i (c.key)}
        <button
            type="button"
            class="choice state-{c.state}"
            role="radio"
            aria-checked={c.key === selected}
            tabindex={committed ? -1 : tabindexFor(c.key, i)}
            disabled={committed}
            bind:this={radios[i]}
            on:click={() => pick(i)}
            on:keydown={(e) => onKeydown(e, i)}
        >
            <span class="key">{c.key}</span>
            <span class="content">{@html c.html}</span>
            {#if c.state === "wrong"}
                <span class="tag wrong">Not correct</span>
            {/if}
        </button>
    {/each}
</div>

<style lang="scss">
    .choices {
        display: flex;
        flex-direction: column;
        gap: 10px;
        font-family: var(--font-ui);
    }

    .choice {
        display: flex;
        align-items: center;
        gap: 16px;
        width: 100%;
        text-align: left;
        border: var(--hairline);
        background: none;
        border-radius: var(--radius-row);
        padding: 14px 18px;
        color: var(--text);
        cursor: pointer;
        transition: var(--transition-calm);

        &:not([disabled]):hover {
            border-color: var(--muted);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
        }

        &[disabled] {
            cursor: default;
        }
    }

    .state-selected {
        border-color: var(--performance);
        border-width: 2px;
        background: var(--performance-wash);
        box-shadow: inset 0 0 0 1px var(--performance);
    }

    .state-correct {
        border-color: var(--success);
        border-width: 2px;
        background: rgba(163, 190, 140, 0.3);
        box-shadow:
            inset 0 0 0 3px var(--success),
            0 0 0 4px rgba(163, 190, 140, 0.5);
    }

    /* Experiment: a wrong pick reads pastel red (diverges from the calm-blue
       honesty rule, under review). */
    .state-wrong {
        border-color: var(--error-tint);
        border-width: 2px;
        background: var(--error-wash);
        box-shadow: inset 0 0 0 1px var(--error-tint);
    }

    .state-locked {
        opacity: 0.5;
    }

    .key {
        flex: 0 0 26px;
        width: 26px;
        height: 26px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: var(--hairline);
        border-radius: 8px;
        font-family: var(--font-mono);
        font-size: 12px;
        color: var(--muted);
    }

    .state-selected .key {
        border-color: var(--performance);
        color: var(--performance-text);
    }

    .state-correct .key {
        border-color: var(--success);
        background: var(--success);
        color: var(--action-bg);
        font-weight: 600;
    }

    .state-wrong .key {
        border-color: var(--error-tint);
        color: var(--error);
    }

    .content {
        font-size: 16px;
        line-height: 1.5;
        color: var(--text);

        :global(p) {
            margin: 0;
        }
    }

    .tag {
        margin-left: auto;
        flex: 0 0 auto;
        font-size: 11px;
        border-radius: var(--radius-pill);
        padding: 3px 10px;
        white-space: nowrap;

        &.wrong {
            color: var(--error);
            border: 1px solid var(--error-tint);
        }
    }
</style>
