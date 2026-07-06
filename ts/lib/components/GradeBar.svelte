<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep FSRS grade row for the Cards door. Equal monochrome buttons, optional
    next-interval hint under each. Ported from the Claude Design export
    (design/ux-foundation.md).
-->
<script lang="ts">
    import { onDestroy, onMount } from "svelte";

    export let grades: Array<{ label: string; value: number; interval?: string }> = [];
    export let showIntervals = false;
    export let disabled = false;
    export let onGrade: ((value: number) => void) | undefined = undefined;

    // Number-key grading (1..N). A study session shows one grade row at a time,
    // so a window listener is safe. Ignored while disabled or while typing in a
    // field (the AI self-explanation inputs), so it never steals those keys.
    function handleKey(event: KeyboardEvent): void {
        if (disabled) {
            return;
        }
        const target = event.target as HTMLElement | null;
        if (
            target &&
            (target.tagName === "INPUT" ||
                target.tagName === "TEXTAREA" ||
                target.isContentEditable)
        ) {
            return;
        }
        const n = Number(event.key);
        if (Number.isInteger(n) && n >= 1 && n <= grades.length) {
            event.preventDefault();
            onGrade?.(grades[n - 1].value);
        }
    }

    onMount(() => window.addEventListener("keydown", handleKey));
    onDestroy(() => window.removeEventListener("keydown", handleKey));
</script>

<div class="grades" style="grid-template-columns: repeat({grades.length}, 1fr);">
    {#each grades as g (g.value)}
        <button
            type="button"
            class="grade"
            {disabled}
            on:click={() => onGrade && onGrade(g.value)}
        >
            <span class="label">{g.label}</span>
            {#if showIntervals && g.interval}
                <span class="interval">{g.interval}</span>
            {/if}
        </button>
    {/each}
</div>

<style lang="scss">
    .grades {
        display: grid;
        gap: 12px;
        font-family: var(--font-ui);
    }

    .grade {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 3px;
        background: none;
        border: var(--hairline);
        border-radius: var(--radius-control);
        padding: 12px 0 10px;
        color: var(--text);
        font-family: inherit;
        cursor: pointer;
        transition: var(--transition-calm);

        &:not([disabled]):hover {
            background: var(--hover-wash);
            border-color: var(--muted);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
        }

        &[disabled] {
            cursor: default;
            opacity: 0.55;
        }

        .label {
            font-size: 14px;
            font-weight: 500;
        }

        .interval {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--muted);
            font-variant-numeric: tabular-nums;
        }
    }
</style>
