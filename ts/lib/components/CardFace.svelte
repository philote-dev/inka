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

    // Anki renders the answer as {{FrontSide}}<hr id=answer>{{Back}}, so the raw
    // answer repeats the prompt. Keep only what follows the answer divider, so the
    // front shows once. The provenance appended to the Back ("... Source: <ref>")
    // is peeled off and shown as a small tag rather than inline body text.
    function splitAnswer(html: string): { body: string; source: string } {
        const afterDivider = html.replace(
            /^[\s\S]*<hr\s+id=["']?answer["']?[^>]*>/i,
            "",
        );
        const match = afterDivider.match(/(?:<br\s*\/?>|\s)*Source:\s*([\s\S]+?)\s*$/i);
        if (match && match.index !== undefined) {
            return {
                body: afterDivider.slice(0, match.index).trim(),
                source: match[1].trim(),
            };
        }
        return { body: afterDivider.trim(), source: "" };
    }

    $: renderedQuestion = renderMath(questionHtml);
    $: answerParts = splitAnswer(answerHtml);
    $: renderedAnswer = renderMath(answerParts.body);
    $: answerSource = answerParts.source;
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
        {#if answerSource}
            <p class="source">
                <span class="source-tag">Source</span>
                {answerSource}
            </p>
        {/if}
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

    .source {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        justify-content: center;
        gap: 8px;
        margin: var(--space-2) 0 0;
        font-size: var(--text-caption);
        line-height: 1.5;
        color: var(--muted);
    }

    .source-tag {
        padding: 2px 8px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 600;
    }
</style>
