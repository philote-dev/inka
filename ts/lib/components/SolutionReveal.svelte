<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep worked-solution reveal. Shown after a miss on a Problem that carries no
    gated decomposition: there is nothing to gate and the item is not re-queued,
    so hiding the answer would only strand the learner. The correct choice is
    revealed by the ChoiceList above; this walks the stored solution steps (each a
    sub-goal and its rubric) so the learner leaves with the idea, then moves on.

    Presentational: the steps arrive as props, so this renders the same in a
    running session and in the component gallery, with no session or backend call.
-->
<script lang="ts">
    import { renderMath } from "$lib/pgrep/math";
    import { noDashes } from "$lib/pgrep/text";

    export let steps: { subgoal: string; rubric: string }[] = [];
    export let heading = "Here's how it works";
</script>

<section class="reveal" aria-label="Worked solution">
    <span class="eyebrow">Worked solution</span>
    <p class="lead">{heading}</p>
    <ol class="steps">
        {#each steps as step, i (i)}
            <li>
                {#if step.subgoal}
                    <span class="goal">{noDashes(step.subgoal)}</span>
                {/if}
                {#if step.rubric}
                    <span class="rubric">
                        {@html renderMath(noDashes(step.rubric))}
                    </span>
                {/if}
            </li>
        {/each}
    </ol>
</section>

<style lang="scss">
    .reveal {
        margin-top: var(--space-2);
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: 20px 24px;
        box-shadow: var(--shadow-card);
        font-family: var(--font-ui);
        color: var(--text);
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .eyebrow {
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .lead {
        margin: 0;
        font-size: var(--text-body);
        font-weight: 600;
    }

    .steps {
        margin: 4px 0 0;
        padding: 0;
        list-style: none;
        counter-reset: step;
        display: flex;
        flex-direction: column;
        gap: 14px;
    }

    .steps li {
        counter-increment: step;
        position: relative;
        padding-left: 34px;
    }

    .steps li::before {
        content: counter(step);
        position: absolute;
        left: 0;
        top: 0;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        font-family: var(--font-mono);
        font-size: 12px;
        color: var(--muted);
    }

    .goal {
        display: block;
        font-size: 15px;
        font-weight: 600;
        line-height: 1.45;
    }

    .rubric {
        display: block;
        margin-top: 3px;
        font-size: 15px;
        line-height: 1.55;
        color: var(--muted);

        :global(p) {
            margin: 0 0 0.4em;

            &:last-child {
                margin-bottom: 0;
            }
        }
    }
</style>
