<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Home card-row layout options (review fixture). The live Home packs Today plus
     the three score cards into a fixed four-across row that squishes and stretches
     on resize. This surface shows three responsive alternatives side by side with
     the real ScoreCard component and synthetic data, so the layout can be chosen
     from screenshots. Each option's card row is a size container, so it reflows by
     its own width exactly as it will inside the Home content area. No bridge calls,
     so it renders anywhere without the API-access gate. -->
<script lang="ts">
    import ScoreCard from "$lib/components/ScoreCard.svelte";

    type Hue = "memory" | "performance" | "readiness";

    const scores: {
        kind: Hue;
        value: number;
        range: [number, number];
        howSure: string;
        updated: string;
        sparkline: number[];
    }[] = [
        {
            kind: "memory",
            value: 74,
            range: [68, 79],
            howSure: "Fairly sure",
            updated: "Updated 2h ago",
            sparkline: [0.3, 0.42, 0.38, 0.5, 0.55, 0.64, 0.72],
        },
        {
            kind: "performance",
            value: 63,
            range: [57, 70],
            howSure: "Still forming",
            updated: "Updated 1h ago",
            sparkline: [0.5, 0.46, 0.52, 0.58, 0.55, 0.6, 0.66],
        },
        {
            kind: "readiness",
            value: 69,
            range: [61, 76],
            howSure: "Fairly sure",
            updated: "Updated 2h ago",
            sparkline: [0.4, 0.45, 0.5, 0.52, 0.6, 0.64, 0.69],
        },
    ];
</script>

<div class="pgrep night-mode shell">
    <div>
        <header class="head">
            <h1>Home card-row layouts</h1>
            <p>
                Today plus the three score cards, shown three ways. Each row is a size
                container, so it reflows by its own width just as it will on Home. Pick
                the behaviour you want and I will wire it into the real surface.
            </p>
        </header>

        <!-- Option A: responsive, capped to the mockup width -->
        <section class="option">
            <div class="opt-head">
                <span class="tag">Option A</span>
                <h2>Responsive, capped</h2>
                <p>
                    Content caps at 1150px and centres. Cards go four across on wide,
                    two by two when narrower, then one column. Never crushed. Matches
                    Home.dc.html at desktop.
                </p>
            </div>
            <div class="cardwrap capped">
                <div class="cards four">
                    <section class="today">
                        <div class="today-head">
                            <span class="today-eyebrow">Today</span>
                            <span class="today-chip">High impact</span>
                        </div>
                        <div class="today-title">Thermodynamics focus drill</div>
                        <div class="today-meta">About 25 min</div>
                        <button class="start">Start session</button>
                    </section>
                    {#each scores as s (s.kind)}
                        <ScoreCard
                            kind={s.kind}
                            value={s.value}
                            range={s.range}
                            howSure={s.howSure}
                            updated={s.updated}
                            sparkline={s.sparkline}
                        />
                    {/each}
                </div>
            </div>
        </section>

        <!-- Option B: fully fluid, no cap -->
        <section class="option">
            <div class="opt-head">
                <span class="tag">Option B</span>
                <h2>Fully fluid</h2>
                <p>
                    Same reflow, but no width cap. The row fills whatever width is
                    available, so cards get very wide on large monitors.
                </p>
            </div>
            <div class="cardwrap">
                <div class="cards four">
                    <section class="today">
                        <div class="today-head">
                            <span class="today-eyebrow">Today</span>
                            <span class="today-chip">High impact</span>
                        </div>
                        <div class="today-title">Thermodynamics focus drill</div>
                        <div class="today-meta">About 25 min</div>
                        <button class="start">Start session</button>
                    </section>
                    {#each scores as s (s.kind)}
                        <ScoreCard
                            kind={s.kind}
                            value={s.value}
                            range={s.range}
                            howSure={s.howSure}
                            updated={s.updated}
                            sparkline={s.sparkline}
                        />
                    {/each}
                </div>
            </div>
        </section>

        <!-- Option C: Today band on top, scores in their own row -->
        <section class="option">
            <div class="opt-head">
                <span class="tag">Option C</span>
                <h2>Restructured</h2>
                <p>
                    Today becomes a full-width band with the session call to action, and
                    the three scores sit in their own equal row below. A clearer split
                    between "do this now" and "here is where you stand".
                </p>
            </div>
            <div class="cardwrap capped">
                <section class="today band">
                    <div class="band-text">
                        <div class="today-head">
                            <span class="today-eyebrow">Today</span>
                            <span class="today-chip">High impact</span>
                        </div>
                        <div class="today-title">Thermodynamics focus drill</div>
                        <div class="today-meta">
                            Cards and problems, topics interleaved. About 25 min.
                        </div>
                    </div>
                    <button class="start">Start session</button>
                </section>
                <div class="scores-three">
                    {#each scores as s (s.kind)}
                        <ScoreCard
                            kind={s.kind}
                            value={s.value}
                            range={s.range}
                            howSure={s.howSure}
                            updated={s.updated}
                            sparkline={s.sparkline}
                        />
                    {/each}
                </div>
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

    .option {
        margin-bottom: var(--space-5, 48px);
    }

    .opt-head {
        margin-bottom: var(--space-2, 16px);

        .tag {
            display: inline-block;
            font-size: var(--text-caption);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--muted);
            border: var(--hairline);
            border-radius: var(--radius-pill);
            padding: 2px 10px;
            margin-bottom: 8px;
        }

        h2 {
            margin: 0 0 4px;
            font-size: var(--text-emphasis);
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        p {
            margin: 0;
            max-width: 74ch;
            font-size: var(--text-small);
            line-height: 1.5;
            color: var(--muted);
        }
    }

    /* Each row is its own size container, so it reflows by its own width the same
       way it will inside the Home content area (which is narrower than the window
       by the nav rail). */
    .cardwrap {
        container-type: inline-size;
        width: 100%;
    }

    .cardwrap.capped {
        max-width: 1150px;
    }

    .cards {
        display: grid;
        grid-template-columns: 1fr;
        gap: var(--space-2, 16px);
        align-items: stretch;
    }

    .cards.four {
        @container (min-width: 640px) {
            grid-template-columns: 1fr 1fr;
        }

        @container (min-width: 980px) {
            grid-template-columns: 1.25fr 1fr 1fr 1fr;
        }
    }

    .scores-three {
        display: grid;
        grid-template-columns: 1fr;
        gap: var(--space-2, 16px);

        @container (min-width: 620px) {
            grid-template-columns: repeat(3, 1fr);
        }
    }

    /* Today card, mirroring the live Home styling so the comparison is honest. */
    .today {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: 20px;
        display: flex;
        flex-direction: column;
        box-shadow: var(--shadow-card);
    }

    .today.band {
        flex-direction: row;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2, 16px);
        margin-bottom: var(--space-2, 16px);
    }

    .today-head {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 14px;
    }

    .today.band .today-head {
        margin-bottom: 8px;
    }

    .today-eyebrow {
        font-size: 13px;
        font-weight: 500;
        color: var(--muted);
    }

    .today-chip {
        font-size: 11px;
        color: var(--muted);
        border: var(--hairline);
        border-radius: var(--radius-pill);
        padding: 2px 8px;
        white-space: nowrap;
    }

    .today-title {
        font-size: 16px;
        font-weight: 600;
        letter-spacing: -0.01em;
    }

    .today-meta {
        font-size: 13px;
        color: var(--muted);
        margin-top: 6px;
    }

    .start {
        margin-top: auto;
        align-self: flex-start;
        background: var(--action-bg);
        color: var(--action-fg);
        border: none;
        border-radius: var(--radius-control);
        padding: 11px 18px;
        font-family: var(--font-ui);
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        white-space: nowrap;
        transition: var(--transition-calm);

        &:hover {
            background: var(--action-bg-hover);
        }
    }

    .today.band .start {
        margin-top: 0;
    }
</style>
