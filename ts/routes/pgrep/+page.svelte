<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep Home (Readiness). The manifold hero, the three score cards, and the
     Today card, on mock data. Ported from the Claude Design export
     (design/Home.dc.html). Real data wires in at build layer L2. -->
<script lang="ts">
    import Manifold from "$lib/components/Manifold.svelte";
    import ScoreCard from "$lib/components/ScoreCard.svelte";
    import { FULL_SURFACE } from "$lib/pgrep/manifold";

    const nav = [
        { name: "Home", active: true },
        { name: "Study", active: false },
        { name: "Progress", active: false },
        { name: "Library", active: false },
        { name: "Settings", active: false },
    ];

    const memorySpark = [0.3, 0.45, 0.42, 0.6, 0.55, 0.78, 0.75];
    const performanceSpark = [0.2, 0.32, 0.28, 0.5, 0.45, 0.6, 0.66];
</script>

<div class="home">
    <nav class="rail">
        <div class="brand">
            <svg width="30" height="30" viewBox="0 0 32 32" fill="none" aria-label="pgrep logo">
                <path d="M16 3.5 C22 3.5 28.5 7.5 28.5 14 C28.5 19 25 21 24 24.5 C23 27.5 20 29 16 28.5 C10.5 28 6.5 25.5 4.5 21 C2.5 16.5 3.5 10.5 7.5 7 C10 4.8 13 3.5 16 3.5 Z" stroke="currentColor" stroke-width="1.4" />
                <path d="M16 8 C20 8 24 10.5 24 14.5 C24 17.5 22 19 21.2 21.2 C20.5 23.2 18.5 24.3 16 24 C12.5 23.6 10 22 8.8 19 C7.6 16 8.2 12.5 10.6 10.3 C12.2 8.9 14 8 16 8 Z" stroke="currentColor" stroke-width="1.4" />
                <path d="M16 12.5 C18.2 12.5 20 13.8 20 15.8 C20 17.3 19 18.1 18.6 19.2 C18.2 20.2 17.2 20.8 16 20.6 C14.2 20.4 13 19.5 12.4 18 C11.8 16.5 12.1 14.8 13.3 13.7 C14.1 13 15 12.5 16 12.5 Z" stroke="currentColor" stroke-width="1.4" />
            </svg>
            <span>pgrep</span>
        </div>

        <div class="nav">
            {#each nav as item (item.name)}
                <a href={"#"} class="item" class:active={item.active}>
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                        {#if item.name === "Home"}
                            <path d="M3 9.5 L10 3.5 L17 9.5 V16 a1 1 0 0 1 -1 1 H4 a1 1 0 0 1 -1 -1 Z" />
                        {:else if item.name === "Study"}
                            <path d="M2.5 4.5 C4.5 3.3 7 3.3 9 4.5 V16 C7 14.8 4.5 14.8 2.5 16 Z" />
                            <path d="M17.5 4.5 C15.5 3.3 13 3.3 11 4.5 V16 C13 14.8 15.5 14.8 17.5 16 Z" />
                        {:else if item.name === "Progress"}
                            <polyline points="2.5,14.5 7,10 10,13 17.5,5" />
                            <polyline points="12.5,5 17.5,5 17.5,10" />
                        {:else if item.name === "Library"}
                            <path d="M3 3.5 h3 v13 h-3 z" />
                            <path d="M8 3.5 h3 v13 h-3 z" />
                            <path d="M13.2 4.2 l2.9 -0.8 3.4 12.6 -2.9 0.8 z" />
                        {:else}
                            <line x1="3" y1="5.5" x2="17" y2="5.5" />
                            <line x1="3" y1="10" x2="17" y2="10" />
                            <line x1="3" y1="14.5" x2="17" y2="14.5" />
                        {/if}
                    </svg>
                    {item.name}
                </a>
            {/each}
        </div>

        <div class="streak">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10 2.5 C10 6 6 7 6 11 a4 4 0 0 0 8 0 C14 8.5 11.5 7.5 11.5 5 C11 5.8 10 6.2 10 2.5 Z" />
            </svg>
            <span>12 day streak</span>
        </div>
    </nav>

    <main class="main">
        <header class="head">
            <h1>Good evening, Sam.</h1>
            <p>Your knowledge map, updated 2h ago.</p>
        </header>

        <div class="hero">
            <Manifold width={720} height={360} scale={156} grid={90} surface={FULL_SURFACE} />
        </div>

        <section class="cards">
            <section class="today">
                <div class="today-head">
                    <div class="today-label">
                        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="2,10 5.5,10 8,4.5 12,15.5 14.5,10 18,10" />
                        </svg>
                        <span>Today</span>
                    </div>
                    <span class="chip">High impact</span>
                </div>
                <div class="today-title">Thermodynamics focus drill</div>
                <div class="today-meta">About 25 min</div>
                <button type="button" class="start">
                    Start session
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="2" y1="8" x2="13" y2="8" />
                        <polyline points="9,4 13,8 9,12" />
                    </svg>
                </button>
            </section>

            <ScoreCard
                kind="memory"
                value={72}
                range={[68, 77]}
                howSure="Fairly sure"
                updated="Updated 2h ago"
                sparkline={memorySpark}
            />
            <ScoreCard
                kind="performance"
                value={68}
                range={[64, 74]}
                howSure="Somewhat sure"
                updated="Updated 2h ago"
                sparkline={performanceSpark}
            />
            <ScoreCard
                kind="readiness"
                abstain={{
                    missing:
                        "Coverage sits at 46 percent, below the 70 percent line. Readiness stays quiet until then.",
                }}
            />
        </section>
    </main>
</div>

<style lang="scss">
    .home {
        display: flex;
        min-height: 100vh;
        background: var(--canvas);
        color: var(--text);
    }

    .rail {
        width: 216px;
        flex: 0 0 216px;
        border-right: var(--hairline);
        display: flex;
        flex-direction: column;
        padding: 28px 16px 24px;
    }

    .brand {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 0 12px;
        margin-bottom: 36px;
        color: var(--text);

        span {
            font-size: 15px;
            font-weight: 600;
            letter-spacing: -0.01em;
        }
    }

    .nav {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 12px;
        border-radius: var(--radius-control);
        color: var(--muted);
        text-decoration: none;
        font-size: 14px;
        font-weight: 500;
        border: 1px solid transparent;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
        }

        &.active {
            color: var(--text);
            background: var(--surface);
            border-color: var(--border);
        }
    }

    .streak {
        margin-top: auto;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 12px;
        color: var(--muted);
        font-size: 13px;

        span {
            font-variant-numeric: tabular-nums;
        }
    }

    .main {
        flex: 1 1 auto;
        min-width: 0;
        padding: 32px 36px 36px;
        display: flex;
        flex-direction: column;
    }

    .head {
        h1 {
            margin: 0;
            font-size: var(--text-greeting);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        p {
            margin: 6px 0 0;
            font-size: 14px;
            color: var(--muted);
        }
    }

    .hero {
        flex: 0 0 auto;
        margin: 8px 0 16px;
    }

    .cards {
        display: grid;
        grid-template-columns: 1.4fr 1fr 1fr 1fr;
        gap: var(--space-2);
        align-items: stretch;
    }

    .today {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: 20px;
        display: flex;
        flex-direction: column;
        box-shadow: var(--shadow-card);
    }

    .today-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 14px;
    }

    .today-label {
        display: flex;
        align-items: center;
        gap: 10px;
        color: var(--text);

        span {
            font-size: 13px;
            font-weight: 500;
            color: var(--muted);
        }
    }

    .chip {
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
        font-variant-numeric: tabular-nums;
    }

    .start {
        margin-top: auto;
        align-self: flex-start;
        display: flex;
        align-items: center;
        gap: 8px;
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
</style>
