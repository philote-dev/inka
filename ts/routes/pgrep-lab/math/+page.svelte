<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Math rendering (review fixture). Our content is plain-text physics notation,
     not LaTeX, so ts/lib/pgrep/math.ts typesets it: superscripts, subscripts,
     radicals with a vinculum, and simple stacked fractions. This shows the
     renderer on a real card and on a raw-versus-rendered notation panel. No
     bridge calls, so it renders anywhere. -->
<script lang="ts">
    import CardFace from "$lib/components/CardFace.svelte";
    import { renderMath } from "$lib/pgrep/math";

    // The content will carry delimited LaTeX after the conversion pass; this shows
    // how MathJax typesets it. \\( \\) is inline, \\[ \\] is display.
    const questionHtml =
        "<p>A car of mass \\(m\\) rounds a vertical loop of radius \\(R\\). What minimum speed at the top keeps it on the track, and from what release height \\(h\\) must it start?</p>";
    const answerHtml =
        "<p>At the threshold of contact the track force is zero, so gravity alone supplies the centripetal force: \\(mg = \\frac{mv^2}{R}\\), giving \\(v^2 = gR\\) and \\(v = \\sqrt{gR}\\). Energy conservation from height \\(h\\) gives \\(mgh = \\tfrac{1}{2}mv^2 + mg(2R)\\), so the minimum height is \\(h = \\tfrac{5R}{2}\\).</p>";

    // Sample LaTeX, from the notation our content uses, plus one display formula.
    const samples = [
        "\\(\\frac{mv^2}{R}\\)",
        "\\(v^2 = gR\\)",
        "\\(\\sqrt{2gR}\\)",
        "\\(\\tfrac{1}{2}mv^2\\)",
        "\\(\\frac{p^2}{2m}\\)",
        "\\(K_f - K_i\\)",
        "\\(v_0,\\ x_i,\\ \\omega_c\\)",
        "\\(E = hf,\\quad p = \\frac{h}{\\lambda}\\)",
        "\\[\\oint \\vec{E}\\cdot d\\vec{A} = \\frac{Q_{\\text{enc}}}{\\varepsilon_0}\\]",
    ];
</script>

<div class="pgrep night-mode shell">
    <div>
        <header class="head">
            <h1>Math rendering</h1>
            <p>
                Real MathJax typesetting, the same engine Anki's reviewer uses. Once the
                content carries delimited LaTeX, this is how the math renders across
                cards, problems, and exams: aligned fractions, radicals, and Greek.
            </p>
        </header>

        <div class="showcase">
            <div class="card-col">
                <span class="state">In a card</span>
                <div class="frame">
                    <CardFace {questionHtml} {answerHtml} answerShown={true} />
                </div>
            </div>

            <section class="notation">
                <span class="state">LaTeX, typeset</span>
                <div class="rows">
                    {#each samples as raw (raw)}
                        <div class="row">
                            <code class="raw">{raw}</code>
                            <span class="arrow" aria-hidden="true">&rarr;</span>
                            <span class="rendered">{@html renderMath(raw)}</span>
                        </div>
                    {/each}
                </div>
            </section>
        </div>
    </div>
</div>

<style lang="scss">
    .shell {
        min-height: 100vh;
        background: var(--canvas);
        color: var(--text);
    }

    .head {
        margin-bottom: var(--space-4, 32px);

        h1 {
            margin: 0 0 var(--space-1, 8px);
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        p {
            margin: 0;
            max-width: 74ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
        }
    }

    .showcase {
        display: grid;
        grid-template-columns: 1fr;
        gap: var(--space-4, 32px);
        align-items: start;
    }

    @media (min-width: 960px) {
        .showcase {
            grid-template-columns: 1fr 1fr;
        }
    }

    .card-col,
    .notation {
        display: flex;
        flex-direction: column;
        gap: var(--space-1, 8px);
        min-width: 0;
    }

    .state {
        font-size: var(--text-caption);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--muted);
    }

    .frame {
        max-width: 560px;
        width: 100%;
    }

    .rows {
        display: grid;
        gap: var(--space-1, 8px);
    }

    .row {
        display: grid;
        grid-template-columns: 180px 20px 1fr;
        align-items: center;
        gap: var(--space-2, 16px);
        padding: 10px 14px;
        border: var(--hairline);
        border-radius: var(--radius-row);
        background: var(--surface);
    }

    .raw {
        font-family: var(--font-mono);
        font-size: var(--text-small);
        color: var(--muted);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .arrow {
        color: var(--muted);
        text-align: center;
    }

    .rendered {
        font-size: var(--text-content);
        line-height: 1.8;
    }
</style>
