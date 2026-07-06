<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Flashcard face + math rendering (review fixture). Shows the CardFace in its two
     states with math-rich content, and a raw-versus-rendered panel that runs the
     real MathJax renderer (ts/lib/pgrep/math.ts) over the delimited LaTeX our card
     content carries. Only the \( ... \) and \[ ... \] spans typeset; the prose
     around them is left untouched. No bridge calls, so it renders anywhere. -->
<script lang="ts">
    import CardFace from "$lib/components/CardFace.svelte";
    import { renderMath } from "$lib/pgrep/math";

    // A computational card in delimited LaTeX; MathJax typesets each \( ... \) span
    // while the surrounding prose is left as plain text.
    const questionHtml =
        "<p>A bead of mass \\(m\\) rides inside a vertical loop of radius \\(R\\). What minimum speed \\(v\\) at the top keeps it on the track, and what is its kinetic energy \\(K\\) there?</p>";
    const answerBody =
        "<p>At the top, gravity alone supplies the centripetal force, so \\(mg=\\frac{mv^2}{R}\\) and \\(v=\\sqrt{gR}\\). The kinetic energy is then \\(K=\\tfrac{1}{2}mv^2=\\tfrac{1}{2}mgR\\). Over the descent the work-energy theorem \\(W_{\\mathrm{net}}=\\Delta K\\) fixes the release height.</p>";
    const sourceRef =
        "OpenStax University Physics Volume 1, pp. 337-338, §7.3 Work-Energy Theorem";
    // card.answer() renders {{FrontSide}}<hr id=answer>{{Back}}, so the raw answer
    // repeats the prompt and trails the source. CardFace shows the front once and
    // lifts the source into a tag.
    const answerHtml = `${questionHtml}\n\n<hr id=answer>\n\n${answerBody}\n\nSource: ${sourceRef}`;

    // Raw LaTeX spans drawn from the card above, to show raw versus typeset.
    const samples = [
        "\\(K=\\tfrac{1}{2}mv^2\\)",
        "\\(v=\\sqrt{gR}\\)",
        "\\(W_{\\mathrm{net}}=\\Delta K\\)",
        "\\(mg=\\frac{mv^2}{R}\\)",
        "\\(K_f-K_i\\)",
        "\\(p=\\frac{h}{\\lambda}\\)",
        "\\(v_0,\\ x_i,\\ \\omega_0\\)",
        "\\(E=hf\\)",
    ];
</script>

<div class="pgrep night-mode shell">
    <div>
        <header class="head">
            <h1>Flashcard face and math</h1>
            <p>
                The Cards-door review card with math-rich content, plus a
                raw-versus-rendered check of the MathJax renderer. On reveal the front
                shows once and the source moves to a tag. Delimited LaTeX typesets
                through CardFace while the surrounding prose stays plain.
            </p>
        </header>

        <div class="cols">
            <div class="col">
                <span class="state">Prompt, before reveal</span>
                <div class="frame">
                    <CardFace {questionHtml} {answerHtml} answerShown={false} />
                </div>
            </div>
            <div class="col">
                <span class="state">Revealed</span>
                <div class="frame">
                    <CardFace {questionHtml} {answerHtml} answerShown={true} />
                </div>
            </div>
        </div>

        <section class="notation">
            <h2>Notation</h2>
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

    .cols {
        display: grid;
        grid-template-columns: 1fr;
        gap: var(--space-4, 32px);
        margin-bottom: var(--space-5, 40px);
    }

    @media (min-width: 900px) {
        .cols {
            grid-template-columns: 1fr 1fr;
        }
    }

    .col {
        display: flex;
        flex-direction: column;
        gap: var(--space-1, 8px);
    }

    .state {
        font-size: var(--text-caption);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--muted);
    }

    .frame {
        max-width: 640px;
        width: 100%;
    }

    .notation {
        h2 {
            margin: 0 0 var(--space-2, 16px);
            font-size: var(--text-emphasis);
            font-weight: 600;
        }
    }

    .rows {
        display: grid;
        gap: var(--space-1, 8px);
        max-width: 640px;
    }

    .row {
        display: grid;
        grid-template-columns: 220px 24px 1fr;
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
    }

    .arrow {
        color: var(--muted);
        text-align: center;
    }

    .rendered {
        font-size: var(--text-content);
    }
</style>
