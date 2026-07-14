<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Library, two states (card-sets plan §3):

  - Calibration walkthrough (Walkthrough.svelte) while AI is on and calibration
    is incomplete. This is the generation-effect act, and with AI on it is the
    gate in front of Study.
  - The Card Sets wheel (CardWheel.svelte) once calibrated, or whenever AI is
    off. For AI-off, uncalibrated learners the wheel shows immediately with a
    dismissible "Teach pgrep your style" entry that launches the walkthrough
    voluntarily (never a wall).

Selection rule: show the walkthrough when (aiEnabled && !calibrated), else the
wheel. Authoring the last category's card completes calibration and flips the
surface to the wheel; turning AI off in Settings relaxes the gate on the next
visit.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import { goto } from "$app/navigation";
    import CardWheel from "$lib/components/CardWheel.svelte";

    import { pgrepCall } from "../lib/bridge";
    import Walkthrough from "./Walkthrough.svelte";

    interface WheelCard {
        note_id?: number;
        front: string;
        back?: string;
    }
    interface CardSet {
        category: string;
        name: string;
        cards: WheelCard[];
    }

    let sets: CardSet[] = [];
    let aiEnabled = false;
    let calibrated = false;
    let loaded = false;
    let error = false;
    // AI-off, uncalibrated learners can opt into the walkthrough voluntarily.
    let walkthroughByChoice = false;
    let entryDismissed = false;

    // The gate: AI on and not yet calibrated forces the walkthrough. AI-off
    // learners can still choose it. Everyone else gets the wheel.
    $: showWalkthrough = (aiEnabled && !calibrated) || walkthroughByChoice;
    $: showTeachEntry =
        loaded &&
        !error &&
        !showWalkthrough &&
        !aiEnabled &&
        !calibrated &&
        !entryDismissed;

    onMount(async () => {
        try {
            const [ai, cal] = await Promise.all([
                pgrepCall<{ enabled: boolean }>("pgrepAiStatus", {}),
                pgrepCall<{ calibrated: boolean }>("pgrepCalibrationStatus", {}),
            ]);
            aiEnabled = ai.enabled;
            calibrated = cal.calibrated;
            sets = await pgrepCall<CardSet[]>("pgrepCardSets", {});
        } catch {
            error = true;
        } finally {
            loaded = true;
        }
    });

    // After the walkthrough authors a card, re-check coverage. Completing it
    // calibrates the collection, so the surface returns to the wheel (freshly
    // reloaded so the just-authored cards are there).
    async function onAuthored(): Promise<void> {
        try {
            const cal = await pgrepCall<{ calibrated: boolean }>(
                "pgrepCalibrationStatus",
                {},
            );
            calibrated = cal.calibrated;
            if (calibrated) {
                walkthroughByChoice = false;
                sets = await pgrepCall<CardSet[]>("pgrepCardSets", {});
            }
        } catch {
            // Leave the walkthrough in place if the re-check fails.
        }
    }

    // "Study this set" enters that category's focus drill through the deep link
    // Study already handles on mount (?topic=<slug>).
    function studySet(category: string): void {
        void goto(`/pgrep/study?topic=${encodeURIComponent(category)}`);
    }

    // "Add a card" authors the learner's own front/back as-is into the set (no
    // AI), then appends it locally so the grid and counts update without a
    // refetch. Categories are stable, so the open set stays put.
    async function addCard(
        category: string,
        front: string,
        back: string,
    ): Promise<void> {
        const res = await pgrepCall<{ note_id: number; category: string }>(
            "pgrepAddCard",
            { category, front, back },
        );
        sets = sets.map((s) =>
            s.category === category
                ? { ...s, cards: [...s.cards, { note_id: res.note_id, front, back }] }
                : s,
        );
    }
</script>

{#if !loaded}
    <div class="library-wheel">
        <p class="state">Reading your sets.</p>
    </div>
{:else if error}
    <div class="library-wheel">
        <div class="state">
            <p class="lead">Could not load your library.</p>
        </div>
    </div>
{:else if showWalkthrough}
    <Walkthrough {onAuthored} />
{:else}
    <div class="library-wheel">
        {#if showTeachEntry}
            <div class="teach-entry">
                <div class="teach-copy">
                    <span class="teach-title">Teach pgrep your style</span>
                    <span class="teach-sub">
                        Write one card per topic in your own words. It is the fastest
                        way to make this stick.
                    </span>
                </div>
                <div class="teach-actions">
                    <button
                        class="teach-start"
                        on:click={() => (walkthroughByChoice = true)}
                    >
                        Start
                    </button>
                    <button
                        class="teach-dismiss"
                        aria-label="Dismiss"
                        on:click={() => (entryDismissed = true)}
                    >
                        <svg
                            width="14"
                            height="14"
                            viewBox="0 0 16 16"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.5"
                            stroke-linecap="round"
                            aria-hidden="true"
                        >
                            <line x1="4" y1="4" x2="12" y2="12" />
                            <line x1="12" y1="4" x2="4" y2="12" />
                        </svg>
                    </button>
                </div>
            </div>
        {/if}
        <div class="wheel-holder">
            <CardWheel {sets} onStudySet={studySet} onAddCard={addCard} />
        </div>
    </div>
{/if}

<style lang="scss">
    /* Full surface height (the rail sits beside this in the shell), so the wheel's
       perspective stage has the vertical room its geometry is tuned for. */
    .library-wheel {
        display: flex;
        flex-direction: column;
        height: 100%;
    }

    .wheel-holder {
        flex: 1 1 auto;
        min-height: 0;
    }

    .state {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
        gap: var(--space-1);
        color: var(--muted);
        font-family: var(--font-ui);
        font-size: var(--text-body);
        text-align: center;
    }

    .lead {
        margin: 0;
        font-size: var(--text-emphasis);
        font-weight: 600;
        color: var(--text);
    }

    /* AI-off, uncalibrated entry into the walkthrough. A calm strip, never a wall. */
    .teach-entry {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
        margin: var(--space-2) var(--space-3) 0;
        padding: 12px 14px 12px 18px;
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        font-family: var(--font-ui);
    }

    .teach-copy {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }

    .teach-title {
        font-size: var(--text-body);
        font-weight: 600;
        color: var(--text);
    }

    .teach-sub {
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    .teach-actions {
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        flex: 0 0 auto;
    }

    .teach-start {
        padding: 8px 16px;
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        border: 1px solid var(--action-bg);
        border-radius: var(--radius-control);
        background: var(--action-bg);
        color: var(--action-fg);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            background: var(--action-bg-hover);
            border-color: var(--action-bg-hover);
        }
    }

    .teach-dismiss {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 30px;
        height: 30px;
        padding: 0;
        border: none;
        border-radius: var(--radius-control);
        background: none;
        color: var(--muted);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
        }
    }
</style>
