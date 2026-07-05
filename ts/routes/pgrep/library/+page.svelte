<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
pgrep Library (L4.1), the forced-generation authoring surface (ux-foundation.md
7.4). The learner authors one conceptual seed in their own words. That seed
enters the pool (the generation-effect act, works AI on or off) and, with AI on,
either stylizes the bundle's cards into their voice or gap-fills net-new siblings
from the corpus. Every generated card cites a named source, shows its
verification status, and low confidence routes to review rather than the deck.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import { pgrepCall } from "../lib/bridge";

    type AiStatus = {
        enabled: boolean;
        model: string | null;
        has_key: boolean;
        ready: boolean;
    };

    // The 20 blueprint topic tags, grouped for the selector.
    const TOPICS: { tag: string; label: string }[] = [
        {
            tag: "topic::mechanics::dynamics_energy",
            label: "Mechanics / Dynamics, work and energy",
        },
        { tag: "topic::mechanics::oscillations", label: "Mechanics / Oscillations" },
        {
            tag: "topic::mechanics::rotation",
            label: "Mechanics / Rotation and rigid bodies",
        },
        {
            tag: "topic::mechanics::central_forces",
            label: "Mechanics / Central forces and orbits",
        },
        {
            tag: "topic::mechanics::lagrangian_hamiltonian",
            label: "Mechanics / Lagrangian and Hamiltonian",
        },
        {
            tag: "topic::electromagnetism::electrostatics",
            label: "E and M / Electrostatics",
        },
        {
            tag: "topic::electromagnetism::magnetostatics",
            label: "E and M / Magnetostatics",
        },
        {
            tag: "topic::electromagnetism::induction_maxwell",
            label: "E and M / Induction and Maxwell",
        },
        {
            tag: "topic::electromagnetism::em_waves",
            label: "E and M / Electromagnetic waves",
        },
        { tag: "topic::electromagnetism::circuits", label: "E and M / Circuits" },
        { tag: "topic::quantum::formalism", label: "Quantum / Formalism" },
        {
            tag: "topic::quantum::schrodinger_solutions",
            label: "Quantum / Schrodinger solutions",
        },
        {
            tag: "topic::quantum::angular_momentum_spin",
            label: "Quantum / Angular momentum and spin",
        },
        {
            tag: "topic::quantum::perturbation_symmetry",
            label: "Quantum / Perturbation and symmetry",
        },
        {
            tag: "topic::thermodynamics",
            label: "Thermodynamics and statistical mechanics",
        },
        { tag: "topic::atomic", label: "Atomic physics" },
        { tag: "topic::optics_waves", label: "Optics and wave phenomena" },
        { tag: "topic::special_relativity", label: "Special relativity" },
        { tag: "topic::lab", label: "Laboratory methods" },
        { tag: "topic::specialized", label: "Specialized topics" },
    ];

    let status: AiStatus | null = null;
    let topic = TOPICS[0].tag;
    let seedFront = "";
    let seedBack = "";
    let mode: "gap_fill" | "stylize" = "gap_fill";
    let busy = false;
    let result: any = null;
    let error = "";

    onMount(loadStatus);

    async function loadStatus() {
        try {
            status = await pgrepCall<AiStatus>("pgrepAiStatus", {});
        } catch (e) {
            error = String(e);
        }
    }

    async function toggleAi() {
        if (!status) {
            return;
        }
        try {
            status = await pgrepCall<AiStatus>("pgrepAiSetEnabled", {
                enabled: !status.enabled,
            });
        } catch (e) {
            error = String(e);
        }
    }

    async function generate() {
        error = "";
        result = null;
        if (!seedFront.trim() || !seedBack.trim()) {
            error = "Write both the front and the back of your seed card first.";
            return;
        }
        busy = true;
        try {
            result = await pgrepCall("pgrepLibraryGenerate", {
                mode,
                topic,
                seed_front: seedFront,
                seed_back: seedBack,
                n: 3,
            });
        } catch (e) {
            error = String(e);
        } finally {
            busy = false;
        }
    }
</script>

<div class="library">
    <header>
        <h1>Library</h1>
        <p class="lede">
            Author a seed in your own words. It enters your pool, and with AI on it
            stylizes the bundle into your voice or gap-fills net-new siblings from the
            corpus.
        </p>
    </header>

    {#if status}
        <div class="ai-row">
            <span class="pill" class:on={status.enabled}>
                {status.enabled ? "AI on" : "AI off"}
            </span>
            <button class="ghost" on:click={toggleAi}>
                {status.enabled ? "Turn AI off" : "Turn AI on"}
            </button>
            {#if status.enabled && !status.has_key}
                <span class="warn">
                    No API key found. Set OPENAI_API_KEY to generate.
                </span>
            {/if}
            {#if status.enabled && status.model}
                <span class="muted">model: {status.model}</span>
            {/if}
        </div>
    {/if}

    <section class="card">
        <label class="field">
            <span>Topic</span>
            <select bind:value={topic}>
                {#each TOPICS as t (t.tag)}
                    <option value={t.tag}>{t.label}</option>
                {/each}
            </select>
        </label>
        <label class="field">
            <span>Seed front (the prompt, in your words)</span>
            <textarea
                bind:value={seedFront}
                rows="2"
                placeholder="What does this concept test?"
            ></textarea>
        </label>
        <label class="field">
            <span>Seed back (the answer, in your words)</span>
            <textarea
                bind:value={seedBack}
                rows="3"
                placeholder="Your concise answer."
            ></textarea>
        </label>

        <div class="modes">
            <label>
                <input type="radio" bind:group={mode} value="gap_fill" />
                Gap-fill (net-new from corpus, graded)
            </label>
            <label>
                <input type="radio" bind:group={mode} value="stylize" />
                Stylize (rephrase the bundle, shown live)
            </label>
        </div>

        <button class="primary" on:click={generate} disabled={busy}>
            {busy ? "Working..." : "Author and generate"}
        </button>
        {#if error}<p class="warn">{error}</p>{/if}
    </section>

    {#if result}
        <section class="results">
            {#if result.seed?.added}
                <p class="ok">Your seed card entered the pool.</p>
            {/if}

            {#if result.ai === "off"}
                <p class="muted">{result.message}</p>
            {:else if result.ai === "error"}
                <p class="warn">{result.message}</p>
            {:else if result.mode === "stylize"}
                <h2>Stylized ({result.count})</h2>
                {#each result.cards as c}
                    <div class="gen">
                        <div class="front">{c.front}</div>
                        <div class="back">{c.back}</div>
                        <div class="meta">
                            <span class="tag" class:good={c.facts_locked}>
                                {c.facts_locked ? "facts locked" : "kept original"}
                            </span>
                            <span class="src">{c.provenance}</span>
                        </div>
                    </div>
                {/each}
            {:else}
                <h2>Gap-fill</h2>
                {#if result.added?.length}
                    <h3>Added to your pool ({result.added.length})</h3>
                    {#each result.added as c}
                        <div class="gen">
                            <div class="front">{c.front}</div>
                            <div class="back">{c.back}</div>
                            <div class="meta">
                                <span class="tag good">
                                    confidence {(c.confidence ?? 0).toFixed(2)}
                                </span>
                                <span class="src">Source: {c.source_ref}</span>
                            </div>
                        </div>
                    {/each}
                {/if}
                {#if result.review?.length}
                    <h3>Routed to review ({result.review.length})</h3>
                    {#each result.review as c}
                        <div class="gen review">
                            <div class="front">{c.front}</div>
                            <div class="meta">
                                <span class="tag warn-tag">{c.review_reason}</span>
                                <span class="src">Source: {c.source_ref}</span>
                            </div>
                        </div>
                    {/each}
                {/if}
                {#if result.refused?.length}
                    <h3>Refused ({result.refused.length})</h3>
                    {#each result.refused as c}
                        <div class="gen refused">
                            <span class="tag warn-tag">{c.reason}</span>
                        </div>
                    {/each}
                {/if}
                {#if !result.added?.length && !result.review?.length && !result.refused?.length}
                    <p class="muted">No siblings were produced.</p>
                {/if}
            {/if}
        </section>
    {/if}
</div>

<style lang="scss">
    .library {
        max-width: 760px;
        padding: 40px 48px;
        font-family: var(--font-ui);
        color: var(--text);
    }

    h1 {
        font-size: 22px;
        margin: 0 0 6px;
        letter-spacing: -0.01em;
    }
    h2 {
        font-size: 16px;
        margin: 18px 0 8px;
    }
    h3 {
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--muted);
        margin: 16px 0 6px;
    }
    .lede {
        color: var(--muted);
        font-size: 14px;
        margin: 0 0 20px;
        max-width: 60ch;
    }

    .ai-row {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 18px;
        flex-wrap: wrap;
    }
    .pill {
        font-size: 12px;
        padding: 3px 10px;
        border-radius: 999px;
        border: 1px solid var(--border);
        color: var(--muted);
    }
    .pill.on {
        color: var(--text);
        border-color: var(--text);
    }
    .muted {
        color: var(--muted);
        font-size: 13px;
    }
    .warn {
        color: #b4553b;
        font-size: 13px;
    }

    .card {
        border: 1px solid var(--border);
        border-radius: var(--radius-control, 10px);
        background: var(--surface);
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 14px;
    }
    .field {
        display: flex;
        flex-direction: column;
        gap: 6px;
        font-size: 13px;
    }
    .field span {
        color: var(--muted);
    }
    select,
    textarea {
        font: inherit;
        color: var(--text);
        background: var(--canvas);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 8px 10px;
        resize: vertical;
    }
    .modes {
        display: flex;
        flex-direction: column;
        gap: 6px;
        font-size: 13px;
        color: var(--text);
    }

    button {
        font: inherit;
        cursor: pointer;
        border-radius: 8px;
    }
    .primary {
        align-self: flex-start;
        padding: 9px 18px;
        border: 1px solid var(--text);
        background: var(--text);
        color: var(--canvas);
        font-weight: 500;
    }
    .primary:disabled {
        opacity: 0.6;
        cursor: default;
    }
    .ghost {
        padding: 5px 12px;
        border: 1px solid var(--border);
        background: transparent;
        color: var(--text);
    }

    .results {
        margin-top: 24px;
    }
    .ok {
        color: var(--text);
        font-size: 14px;
    }
    .gen {
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 8px;
        background: var(--surface);
    }
    .gen.review {
        border-style: dashed;
    }
    .gen.refused {
        color: var(--muted);
    }
    .front {
        font-weight: 600;
        font-size: 14px;
    }
    .back {
        font-size: 14px;
        color: var(--text);
        margin-top: 4px;
        white-space: pre-wrap;
    }
    .meta {
        display: flex;
        gap: 10px;
        align-items: center;
        margin-top: 8px;
        flex-wrap: wrap;
    }
    .tag {
        font-size: 11px;
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid var(--border);
        color: var(--muted);
    }
    .tag.good {
        color: var(--text);
        border-color: var(--text);
    }
    .warn-tag {
        font-size: 11px;
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid #b4553b;
        color: #b4553b;
    }
    .src {
        font-size: 12px;
        color: var(--muted);
    }
</style>
