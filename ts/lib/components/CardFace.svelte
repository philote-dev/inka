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
    import MemoryGlyph from "$lib/components/MemoryGlyph.svelte";
    import { renderMath } from "$lib/pgrep/math";

    export let questionHtml = "";
    export let answerHtml = "";
    export let answerShown = false;
    // The source rides behind a pill and starts collapsed. A consumer (the dev
    // gallery) can seed it open to show the revealed layout without a click.
    export let sourceOpenByDefault = false;

    // Anki renders the answer as {{FrontSide}}<hr id=answer>{{Back}}, so the raw
    // answer repeats the prompt. Keep only what follows the answer divider, so the
    // front shows once. The provenance appended to the Back ("... Source: <ref>")
    // is peeled off and tucked behind a click-to-expand pill, not inline body text.
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

    let sourceOpen = sourceOpenByDefault;
    // Collapse whenever the answer is hidden, so the next card never inherits the
    // previous card's expanded source.
    $: if (!answerShown) {
        sourceOpen = false;
    }
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
            <MemoryGlyph />
        </svg>
    </div>

    <div class="prompt">{@html renderedQuestion}</div>

    {#if answerShown}
        <hr class="divider" />
        <div class="answer">{@html renderedAnswer}</div>
        {#if answerSource}
            <div class="source">
                <button
                    type="button"
                    class="source-pill"
                    class:open={sourceOpen}
                    aria-expanded={sourceOpen}
                    on:click={() => (sourceOpen = !sourceOpen)}
                >
                    <span class="source-pill__label">Source</span>
                    <svg
                        class="source-pill__caret"
                        width="10"
                        height="10"
                        viewBox="0 0 16 16"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="1.75"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        aria-hidden="true"
                    >
                        <polyline points="6,3.5 11,8 6,12.5" />
                    </svg>
                </button>
                <div class="source-reveal" class:open={sourceOpen}>
                    <span class="source-ref" title={answerSource}>{answerSource}</span>
                </div>
            </div>
        {/if}
    {/if}
</div>

<style lang="scss">
    .card-face {
        background: var(--surface);
        border: var(--hairline);
        border-radius: 20px;
        padding: 28px 44px;
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
        align-items: center;
        justify-content: center;
        gap: 8px;
        margin-top: var(--space-2);
        font-size: var(--text-caption);
        line-height: 1.5;
        color: var(--muted);
        text-align: left;
    }

    .source-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        flex: 0 0 auto;
        padding: 2px 8px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        background: none;
        color: var(--muted);
        font-family: var(--font-ui);
        font-size: var(--text-caption);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            border-color: var(--muted);
            background: var(--hover-wash);
        }

        &:focus-visible {
            outline: 2px solid var(--action-bg);
            outline-offset: 2px;
        }
    }

    .source-pill__caret {
        flex: 0 0 auto;
        transition: transform var(--duration-calm) var(--ease-spring);
    }

    .source-pill.open .source-pill__caret {
        transform: rotate(90deg);
    }

    /* Horizontal reveal: the citation grows in beside the pill. The 0fr -> 1fr
       grid column animates its width from 0 to the text's content width. */
    .source-reveal {
        display: grid;
        grid-template-columns: 0fr;
        min-width: 0;
        opacity: 0;
        transition:
            grid-template-columns var(--duration-calm) var(--ease-spring),
            opacity var(--duration-calm) var(--ease-spring);
    }

    .source-reveal.open {
        grid-template-columns: 1fr;
        opacity: 1;
    }

    .source-ref {
        overflow: hidden;
        min-width: 0;
        /* The citation stays on one line the whole time, so only the width
           animates and the row height never changes (a wrapping citation would
           balloon in height at the narrow mid-open widths, then snap back). A
           citation wider than the card ellipsizes; the full text is on the title. */
        white-space: nowrap;
        text-overflow: ellipsis;
    }

    @media (prefers-reduced-motion: reduce) {
        .source-pill,
        .source-pill__caret,
        .source-reveal {
            transition: none;
        }
    }
</style>
