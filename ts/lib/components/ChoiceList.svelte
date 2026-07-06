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

    // Typeset any delimited LaTeX in the choice HTML (no-op on plain text).
    $: renderedChoices = choices.map((c) => ({ ...c, html: renderMath(c.html) }));

    type RowState = "default" | "selected" | "correct" | "wrong" | "locked";

    function rowState(key: string): RowState {
        if (!committed) {
            return key === selected ? "selected" : "default";
        }
        if (correctKey && key === correctKey) {
            return "correct";
        }
        if (key === selected) {
            return "wrong";
        }
        return "locked";
    }

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
        {@const state = rowState(c.key)}
        <button
            type="button"
            class="choice state-{state}"
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
            {#if state === "correct"}
                <span class="tag correct">Correct answer</span>
            {:else if state === "wrong"}
                <span class="tag wrong">Your answer, not correct</span>
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
        border-width: 1.5px;
        background: var(--performance-wash);
    }

    .state-correct {
        border-color: var(--success);
        border-width: 1.5px;
        background: var(--success-wash);
    }

    .state-wrong {
        opacity: 0.62;
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
        color: var(--text);
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

        &.correct {
            color: var(--text);
            border: 1px solid var(--success);
        }

        &.wrong {
            color: var(--performance-text);
            border: 1px solid var(--performance-tint);
        }
    }
</style>
