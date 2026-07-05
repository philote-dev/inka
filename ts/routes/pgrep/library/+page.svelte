<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
pgrep Library (L4.1 + L5.9), the forced-generation authoring surface
(design/ux-foundation.md 7.4). Two panels: on the left the learner authors one
seed card in their own words (the generation-effect act, works AI on or off); on
the right the AI-conformed siblings appear, each citing a named source and
carrying a Verified or Needs-review status, with the gold-set gate summarised
below. With AI off the seed still enters the deck and the right panel says so
plainly, pointing to Settings to turn AI back on. How the matching cards are
built (rephrasing a bundle vs drafting net-new siblings) is an internal AI
decision and is never surfaced as a user choice. Styled with the pgrep tokens;
card content is plain text until the shared math component lands (P1 owns math).
-->
<script lang="ts">
    import { onMount } from "svelte";

    import { pgrepCall } from "../lib/bridge";

    interface AiStatus {
        enabled: boolean;
        model: string | null;
        has_key: boolean;
        ready: boolean;
    }

    interface GenCard {
        front: string;
        back?: string;
        source_ref?: string | null;
        review_reason?: string | null;
        note_id?: number;
    }

    interface RefusedCard {
        reason?: string | null;
        front?: string | null;
    }

    interface SeedResult {
        added?: boolean;
        note_id?: number;
        topic?: string;
    }

    interface GenerateResult {
        ai: "off" | "error" | "on" | string;
        added?: GenCard[];
        review?: GenCard[];
        refused?: RefusedCard[];
        seed?: SeedResult | null;
        message?: string;
    }

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
    let front = "";
    let back = "";
    let busy = false;
    let result: GenerateResult | null = null;
    let error = "";
    // What the learner submitted, captured at build time so the saved-seed card
    // keeps showing the authored text even if the editor is edited afterwards.
    let savedFront = "";

    $: aiOn = status?.enabled ?? false;
    $: added = result?.added ?? [];
    $: review = result?.review ?? [];
    $: refused = result?.refused ?? [];
    $: seedSaved = result?.seed?.added ?? false;
    // The gate admitted a card once at least one sibling passed straight into the
    // deck; if some are still waiting, it is running; otherwise it stays idle.
    function gateState(
        addedCount: number,
        reviewCount: number,
    ): "passed" | "running" | "idle" {
        if (addedCount > 0) {
            return "passed";
        }
        if (reviewCount > 0) {
            return "running";
        }
        return "idle";
    }
    $: gate = gateState(added.length, review.length);

    onMount(loadStatus);

    async function loadStatus(): Promise<void> {
        try {
            status = await pgrepCall<AiStatus>("pgrepAiStatus", {});
        } catch {
            // If the status read fails, stay honest and treat AI as off rather
            // than surfacing a raw error. The AI-off path always works.
            status = null;
        }
    }

    async function generate(): Promise<void> {
        error = "";
        if (!front.trim() || !back.trim()) {
            error = "Write both the front and the back first.";
            return;
        }
        busy = true;
        result = null;
        try {
            // How the matching cards are built (rephrase vs net-new siblings) is
            // an internal AI decision, so the surface always asks for the
            // source-cited, gated build. The learner just writes a card.
            result = await pgrepCall<GenerateResult>("pgrepLibraryGenerate", {
                mode: "gap_fill",
                topic,
                seed_front: front,
                seed_back: back,
                n: 3,
            });
            savedFront = front.trim();
        } catch {
            // A thrown call (not an AI refusal, which comes back in the result)
            // means the build could not run. Keep it human, not a raw error.
            error = "Could not build cards just now. Try again.";
        } finally {
            busy = false;
        }
    }
</script>

<div class="library">
    <header class="head">
        <h1>Author a seed</h1>
        <p class="lede">
            Write one card in your own words. We scale the rest in your style.
        </p>
    </header>

    <div class="grid">
        <!-- Left: the seed editor -->
        <section class="editor" aria-label="Your seed">
            <div class="editor-head">
                <span class="topic-chip">
                    <span class="dot" aria-hidden="true"></span>
                    <select bind:value={topic} aria-label="Topic">
                        {#each TOPICS as t (t.tag)}
                            <option value={t.tag}>{t.label}</option>
                        {/each}
                    </select>
                </span>
                <span class="eyebrow">Your seed</span>
            </div>

            <label class="field">
                <span class="eyebrow">Front</span>
                <textarea
                    bind:value={front}
                    rows="2"
                    placeholder="What does this concept test?"
                ></textarea>
            </label>

            <label class="field">
                <span class="eyebrow">Back</span>
                <textarea
                    bind:value={back}
                    rows="4"
                    placeholder="Your concise answer, in your own words."
                ></textarea>
            </label>

            <div class="editor-foot">
                <button class="primary" on:click={generate} disabled={busy}>
                    {#if busy}
                        Working
                    {:else if aiOn}
                        Build matching cards
                    {:else}
                        Add my flashcard
                    {/if}
                </button>
                {#if error}
                    <p class="note-caution">{error}</p>
                {/if}
            </div>
        </section>

        <!-- Right: the AI-conformed siblings -->
        <section class="siblings" aria-label="Siblings">
            <div class="siblings-head">
                <svg
                    class="spark"
                    class:on={aiOn}
                    width="16"
                    height="16"
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                >
                    <path d="M10 2.5 L11.8 8.2 L17.5 10 L11.8 11.8 L10 17.5 L8.2 11.8 L2.5 10 L8.2 8.2 Z" />
                </svg>
                <h2>Siblings</h2>
                {#if !aiOn}
                    <span class="ai-pill">
                        <span class="ai-dot" aria-hidden="true"></span>
                        AI off
                    </span>
                {/if}
            </div>

            {#if !aiOn}
                {#if seedSaved}
                    <article class="sib">
                        <p class="sib-front">{savedFront}</p>
                        <div class="sib-foot">
                            <span class="src">Your seed, enters the deck as is</span>
                            <span class="when">Today</span>
                        </div>
                    </article>
                {/if}
                <div class="placeholder">
                    <p>
                        AI conforming is off, so no new siblings are drafted and the
                        gold set gate stays idle. Write siblings yourself, or turn AI
                        back on.
                    </p>
                    <a class="settings-link" href="/pgrep/settings">Open Settings</a>
                </div>
            {:else if busy}
                {#each [0, 1, 2] as row (row)}
                    <div class="sib skeleton" aria-hidden="true">
                        <span class="skel-line wide"></span>
                        <span class="skel-line"></span>
                        <div class="sib-foot">
                            <span class="skel-chip"></span>
                            <span class="skel-chip short"></span>
                        </div>
                    </div>
                {/each}
                <p class="building">Building matching cards from named sources.</p>
            {:else if !result}
                <div class="placeholder">
                    <p>
                        Write a seed on the left, then build matching cards from named
                        sources. Each one is checked before it joins your deck.
                    </p>
                </div>
            {:else if result.ai === "error"}
                {#if seedSaved}
                    <p class="saved">Your seed is saved.</p>
                {/if}
                <div class="placeholder caution">
                    <p>
                        Something went wrong building the matching cards. Your seed was
                        still saved, so nothing was lost.
                    </p>
                </div>
            {:else}
                {#if seedSaved}
                    <p class="saved">Your seed is saved.</p>
                {/if}

                {#each added as c (c.note_id ?? c.front)}
                    <article class="sib">
                        <p class="sib-front">{c.front}</p>
                        <div class="sib-foot">
                            <span class="src">
                                {#if c.source_ref}Cited from {c.source_ref}{:else}Source pending{/if}
                            </span>
                            <span class="status-pill verified">
                                <svg
                                    width="11"
                                    height="11"
                                    viewBox="0 0 12 12"
                                    fill="none"
                                    stroke="currentColor"
                                    stroke-width="1.5"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                >
                                    <polyline points="2,6.5 5,9.5 10,3" />
                                </svg>
                                Verified
                            </span>
                        </div>
                    </article>
                {/each}

                {#each review as c (c.note_id ?? c.front)}
                    <article class="sib review">
                        <p class="sib-front">{c.front}</p>
                        <div class="sib-foot">
                            <span class="src">
                                {#if c.source_ref}Cited from {c.source_ref}{:else}Source pending{/if}
                            </span>
                            <span class="status-pill needs-review">
                                <svg
                                    width="11"
                                    height="11"
                                    viewBox="0 0 12 12"
                                    fill="none"
                                    stroke="currentColor"
                                    stroke-width="1.5"
                                    stroke-linecap="round"
                                >
                                    <line x1="6" y1="2.5" x2="6" y2="7" />
                                    <circle
                                        cx="6"
                                        cy="9.6"
                                        r="0.6"
                                        fill="currentColor"
                                        stroke="none"
                                    />
                                </svg>
                                Needs review
                            </span>
                        </div>
                    </article>
                {/each}

                {#if refused.length}
                    <p class="left-out">
                        {refused.length}
                        {refused.length === 1 ? "card" : "cards"} left out. pgrep could not
                        ground {refused.length === 1 ? "it" : "them"} in a named source,
                        so {refused.length === 1 ? "it stays" : "they stay"} out of your deck.
                    </p>
                {/if}

                {#if !added.length && !review.length && !refused.length}
                    <div class="placeholder">
                        <p>No matching cards were built this time. Try another seed.</p>
                    </div>
                {/if}

                {#if gate !== "idle"}
                    <span class="gate-chip" class:running={gate === "running"}>
                        <span class="gate-dot" aria-hidden="true"></span>
                        {gate === "passed"
                            ? "Gold set gate passed"
                            : "Gold set gate running"}
                    </span>
                {/if}
            {/if}
        </section>
    </div>
</div>

<style lang="scss">
    .library {
        max-width: 980px;
        margin: 0 auto;
        padding: var(--space-5) var(--space-6) var(--space-6);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .head {
        margin-bottom: var(--space-4);

        h1 {
            margin: 0;
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        .lede {
            margin: var(--space-1) 0 0;
            font-size: var(--text-body);
            color: var(--muted);
            max-width: 60ch;
        }
    }

    .grid {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: var(--space-4);
        align-items: start;

        @media (max-width: 820px) {
            grid-template-columns: minmax(0, 1fr);
        }
    }

    /* Left: editor */
    .editor {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
    }

    .editor-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
        margin-bottom: var(--space-1);
    }

    /* The seed is a memory card, so its chip carries the reserved amber (Memory),
       a data language, not decoration. */
    .topic-chip {
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        border: 1px solid var(--memory-tint);
        border-radius: var(--radius-pill);
        padding: 4px 12px 4px 12px;
        max-width: 100%;
        min-width: 0;

        .dot {
            flex: 0 0 6px;
            width: 6px;
            height: 6px;
            border-radius: var(--radius-pill);
            background: var(--memory);
        }

        select {
            appearance: none;
            border: none;
            background: none;
            font-family: var(--font-ui);
            font-size: var(--text-small);
            font-weight: 500;
            color: var(--memory-text);
            padding: 0;
            padding-right: 14px;
            max-width: 100%;
            min-width: 0;
            text-overflow: ellipsis;
            cursor: pointer;
            /* A small caret so the chip still reads as a control. */
            background-image: linear-gradient(
                    45deg,
                    transparent 50%,
                    var(--memory-text) 50%
                ),
                linear-gradient(135deg, var(--memory-text) 50%, transparent 50%);
            background-position:
                right 4px top 55%,
                right 0 top 55%;
            background-size:
                5px 5px,
                5px 5px;
            background-repeat: no-repeat;

            &:focus {
                outline: none;
            }

            option {
                color: var(--text);
                background: var(--surface);
            }
        }
    }

    .eyebrow {
        font-size: var(--text-caption);
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .field {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);

        textarea {
            font: inherit;
            font-size: var(--text-emphasis);
            line-height: 1.6;
            color: var(--text);
            background: var(--elevated);
            border: var(--hairline);
            border-radius: var(--radius-control);
            padding: 12px 14px;
            resize: vertical;
            transition: var(--transition-calm);

            &::placeholder {
                color: var(--muted);
            }

            &:focus {
                outline: none;
                border-color: var(--muted);
            }
        }
    }

    .editor-foot {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        margin-top: var(--space-0);
    }

    .primary {
        align-self: flex-start;
        display: inline-flex;
        align-items: center;
        padding: 10px 18px;
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        border: 1px solid var(--action-bg);
        border-radius: var(--radius-control);
        background: var(--action-bg);
        color: var(--action-fg);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            background: var(--action-bg-hover);
            border-color: var(--action-bg-hover);
        }

        &:disabled {
            opacity: 0.55;
            cursor: default;
        }
    }

    /* Right: siblings */
    .siblings {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .siblings-head {
        display: flex;
        align-items: center;
        gap: var(--space-1);
        padding: 0 2px;
        margin-bottom: var(--space-0);

        h2 {
            margin: 0;
            font-size: var(--text-emphasis);
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        .spark {
            color: var(--muted);
            transition: var(--transition-calm);

            &.on {
                color: var(--memory-text);
            }
        }

        .ai-pill {
            margin-left: auto;
            display: inline-flex;
            align-items: center;
            gap: 7px;
            font-size: var(--text-caption);
            font-weight: 500;
            color: var(--muted);
            border: var(--hairline);
            border-radius: var(--radius-pill);
            padding: 3px 10px;
            white-space: nowrap;

            .ai-dot {
                width: 5px;
                height: 5px;
                border-radius: var(--radius-pill);
                background: var(--muted);
                opacity: 0.7;
            }
        }
    }

    .sib {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-row);
        box-shadow: var(--shadow-card);
        padding: 16px 18px;

        &.review {
            border-style: dashed;
            box-shadow: none;
        }
    }

    .sib-front {
        margin: 0;
        font-size: var(--text-body);
        line-height: 1.6;
    }

    .sib-foot {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
        margin-top: 14px;
    }

    .src {
        font-size: var(--text-small);
        color: var(--muted);
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .when {
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }

    /* Status pills carry state colour (a separate language from the score hues)
       on the text and glyph only; the border stays a neutral hairline. */
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        flex: 0 0 auto;
        font-size: var(--text-caption);
        font-weight: 500;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        padding: 3px 10px;
        white-space: nowrap;

        &.verified {
            color: var(--success);
        }

        &.needs-review {
            color: var(--caution);
        }
    }

    .saved {
        margin: 0 0 var(--space-0);
        font-size: var(--text-body);
        color: var(--text);
    }

    .left-out {
        margin: var(--space-0) 2px 0;
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    .placeholder {
        border: 1px dashed var(--border);
        border-radius: var(--radius-row);
        padding: 16px 18px;

        p {
            margin: 0;
            font-size: var(--text-small);
            line-height: 1.6;
            color: var(--muted);
        }

        &.caution p {
            color: var(--caution);
        }
    }

    .settings-link {
        display: inline-block;
        margin-top: var(--space-1);
        font-size: var(--text-small);
        color: var(--text);
        text-decoration: underline;
        text-underline-offset: 3px;
    }

    .building {
        margin: var(--space-0) 2px 0;
        font-size: var(--text-small);
        color: var(--muted);
    }

    .note-caution {
        margin: 0;
        font-size: var(--text-small);
        color: var(--caution);
    }

    .gate-chip {
        align-self: flex-start;
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        margin-top: var(--space-1);
        font-size: var(--text-small);
        color: var(--muted);
        border: var(--hairline);
        border-radius: var(--radius-pill);
        padding: 5px 14px;

        .gate-dot {
            width: 6px;
            height: 6px;
            border-radius: var(--radius-pill);
            background: var(--success);
        }

        &.running .gate-dot {
            background: var(--caution);
        }
    }

    /* Loading skeletons for the generating pass. */
    .skeleton {
        box-shadow: none;
    }

    .skel-line {
        display: block;
        height: 12px;
        border-radius: 6px;
        background: var(--elevated);
        animation: pgrep-skel 2.4s ease-in-out infinite;

        &.wide {
            width: 90%;
        }

        & + .skel-line {
            width: 60%;
            margin-top: 8px;
        }
    }

    .skel-chip {
        display: inline-block;
        width: 96px;
        height: 12px;
        border-radius: 6px;
        background: var(--elevated);
        animation: pgrep-skel 2.4s ease-in-out infinite;

        &.short {
            width: 60px;
        }
    }

    @keyframes pgrep-skel {
        0%,
        100% {
            opacity: 0.5;
        }
        50% {
            opacity: 0.85;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .skel-line,
        .skel-chip {
            animation: none;
        }
    }
</style>
