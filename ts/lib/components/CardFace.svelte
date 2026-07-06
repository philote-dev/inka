<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep flashcard face. The Cards-door review card: a prominent centred surface
    with the Memory glyph, the prompt, and, once recalled, a divider and the
    answer. Ported from the Claude Design export (design/claude-design/Cards.dc.html).
    The prompt and answer are trusted card HTML from the collection, rendered
    inside the pgrep type and token system so they read as one calm card.
-->
<script lang="ts">
    import { renderMath } from "$lib/pgrep/math";

    export let questionHtml = "";
    export let answerHtml = "";
    export let answerShown = false;

    $: renderedQuestion = renderMath(questionHtml);
    $: renderedAnswer = renderMath(answerHtml);
</script>

<div class="card-face">
    <div class="face-glyph" aria-hidden="true">
        <svg
            width="22"
            height="22"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
        >
            <polyline points="3,10 10,6.5 17,10" />
            <polyline points="3,13.5 10,10 17,13.5" />
            <polygon points="10,3 14,5.2 10,7.4 6,5.2" />
        </svg>
    </div>

    <div class="prompt">{@html renderedQuestion}</div>

    {#if answerShown}
        <hr class="divider" />
        <div class="answer">{@html renderedAnswer}</div>
    {/if}
</div>

<style lang="scss">
    .card-face {
        background: var(--surface);
        border: var(--hairline);
        border-radius: 20px;
        padding: 40px 44px;
        box-shadow: var(--shadow-card);
        text-align: center;
        font-family: var(--font-ui);
        color: var(--text);
    }

    .face-glyph {
        display: flex;
        justify-content: center;
        margin-bottom: 20px;
        color: var(--memory-text);
    }

    .prompt {
        font-size: var(--text-content);
        line-height: 1.6;
        text-align: center;

        :global(p) {
            margin: 0 0 0.6em;
        }

        :global(p:last-child) {
            margin-bottom: 0;
        }
    }

    .divider {
        border: none;
        border-top: var(--hairline);
        margin: 28px 0;
    }

    .answer {
        font-size: var(--text-content);
        line-height: 1.6;
        text-align: center;
        color: var(--text);

        :global(p) {
            margin: 0 0 0.6em;
        }

        :global(p:last-child) {
            margin-bottom: 0;
        }
    }
</style>
