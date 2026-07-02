<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep hint rung. One calm step of the wrong-answer ladder: a stored sub-goal
    prompt, blue budget dots, and a reveal that shows only this step. The final
    answer never appears before the reveal rung. Never red. Ported from the
    Claude Design export (design/components/study/HintRung.jsx), adapted to the
    committed static ladder (a prompt and an optional revealed step).
-->
<script lang="ts">
    export let title = "Break it down";
    export let index = 1;
    export let total = 3;
    export let prompt = "";
    export let revealHtml: string | undefined = undefined;
    export let shown = false;
    export let onShow: (() => void) | undefined = undefined;
</script>

<section class="rung">
    <div class="rung-head">
        <h3>{title}</h3>
        <div class="budget">
            <div class="dots">
                {#each Array(total) as _, i (i)}
                    <span class="dot" class:on={i < index}></span>
                {/each}
            </div>
            <span class="count">{index} of {total}</span>
        </div>
    </div>
    <div class="step">Step {index} of {total}</div>
    {#if prompt}
        <div class="prompt">{@html prompt}</div>
    {/if}
    {#if revealHtml !== undefined}
        {#if shown}
            <div class="reveal">{@html revealHtml}</div>
        {:else}
            <div class="reveal-action">
                <button type="button" class="ghost" on:click={onShow}>Show the step</button>
            </div>
        {/if}
    {/if}
</section>

<style lang="scss">
    .rung {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: 24px;
        box-shadow: var(--shadow-card);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .rung-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
        gap: 12px;

        h3 {
            margin: 0;
            font-size: 16px;
            font-weight: 600;
            letter-spacing: -0.01em;
        }
    }

    .budget {
        display: flex;
        align-items: center;
        gap: 10px;

        .count {
            font-size: 12px;
            color: var(--muted);
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
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

    .step {
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 8px;
    }

    .prompt {
        font-size: 16px;
        line-height: 1.55;

        :global(p) {
            margin: 0 0 0.5em;
        }
    }

    .reveal {
        margin-top: 14px;
        padding-top: 14px;
        border-top: var(--hairline);
        font-size: 15px;
        line-height: 1.55;

        :global(p) {
            margin: 0 0 0.5em;
        }
    }

    .reveal-action {
        margin-top: 16px;
    }

    .ghost {
        background: none;
        color: var(--text);
        border: 1px solid var(--muted);
        border-radius: var(--radius-control);
        padding: 10px 18px;
        font-family: inherit;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            background: var(--hover-wash);
        }
    }
</style>
