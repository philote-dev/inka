<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep study session chrome. Minimal top bar (a mono count, a topic chip
    toned to the door, a close button) over a focused single column. Ported
    from the Claude Design export (design/ux-foundation.md).
-->
<script lang="ts">
    export let count = "";
    export let topic = "";
    export let topicTone: "neutral" | "memory" | "performance" = "neutral";
    export let columnWidth = 640;
    export let onClose: (() => void) | undefined = undefined;
</script>

<div class="frame">
    <div class="bar">
        <span class="count">{count}</span>
        {#if topic}
            <span class="chip tone-{topicTone}">
                {#if topicTone !== "neutral"}<span class="dot"></span>{/if}
                {topic}
            </span>
        {:else}
            <span></span>
        {/if}
        {#if onClose}
            <button class="close" aria-label="Close session" on:click={onClose}>
                <svg
                    width="16"
                    height="16"
                    viewBox="0 0 16 16"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                >
                    <line x1="4" y1="4" x2="12" y2="12" />
                    <line x1="12" y1="4" x2="4" y2="12" />
                </svg>
            </button>
        {:else}
            <span></span>
        {/if}
    </div>
    <div class="column" style="max-width: {columnWidth}px;">
        <slot />
    </div>
</div>

<style lang="scss">
    .frame {
        display: flex;
        flex-direction: column;
        min-height: 100vh;
        background: var(--canvas);
        color: var(--text);
        font-family: var(--font-ui);
    }

    .bar {
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        align-items: center;
        padding: 20px 28px;
    }

    .count {
        font-family: var(--font-mono);
        font-size: 13px;
        color: var(--muted);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }

    .chip {
        justify-self: center;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        font-weight: 500;
        border-radius: var(--radius-pill);
        padding: 4px 12px;
        white-space: nowrap;
        color: var(--muted);
        border: var(--hairline);

        &.tone-memory {
            color: var(--memory-text);
            border-color: var(--memory-tint);
        }

        &.tone-performance {
            color: var(--performance-text);
            border-color: var(--performance-tint);
        }

        .dot {
            width: 6px;
            height: 6px;
            border-radius: var(--radius-pill);
            background: currentColor;
        }
    }

    .close {
        justify-self: end;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: none;
        border: none;
        border-radius: 8px;
        color: var(--muted);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            background: var(--hover-wash);
            color: var(--text);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
        }
    }

    .column {
        width: 100%;
        margin: 0 auto;
        padding: 24px 24px 64px;
        box-sizing: border-box;
        flex: 1 1 auto;
    }
</style>
