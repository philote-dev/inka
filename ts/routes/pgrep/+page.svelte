<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep Home (Readiness). The manifold hero + three score cards. Memory is
     wired to the real engine (pgrepMemoryScore); Performance and Readiness
     abstain honestly until their models exist. No mock scores. The shared nav
     lives in +layout.svelte. -->
<script lang="ts">
    import { onMount } from "svelte";

    import Manifold from "$lib/components/Manifold.svelte";
    import Manifold3D from "$lib/components/Manifold3D.svelte";
    import ScoreCard from "$lib/components/ScoreCard.svelte";
    import { FULL_SURFACE } from "$lib/pgrep/manifold";
    import { supportsWebGL } from "$lib/pgrep/manifold3d";

    import { pgrepCall } from "./lib/bridge";

    interface OverallScore {
        point: number | null;
        low: number | null;
        high: number | null;
        abstain: boolean;
        reason: string | null;
    }

    interface MemoryData {
        overall: OverallScore;
        k_mem: number;
        last_updated: number | null;
    }

    // The 3D hero on capable devices, the Canvas 2D fallback otherwise or when
    // the learner prefers reduced motion. Both draw the same FULL_SURFACE.
    let use3d = false;
    let mem: MemoryData | null = null;
    let memLoading = true;
    let memError = false;

    async function loadMemory(): Promise<void> {
        memLoading = true;
        memError = false;
        try {
            mem = await pgrepCall<MemoryData>("pgrepMemoryScore", {});
        } catch {
            memError = true;
        } finally {
            memLoading = false;
        }
    }

    onMount(() => {
        const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
        use3d = supportsWebGL() && !reduce;
        void loadMemory();
    });

    function pct(value: number): number {
        return Math.round(value * 100);
    }

    function howSure(low: number, high: number): string {
        const width = high - low;
        if (width <= 0.12) {
            return "Fairly sure";
        }
        if (width <= 0.25) {
            return "Roughly sure";
        }
        return "Not very sure";
    }

    $: memAbstain = !mem || mem.overall.abstain || mem.overall.point === null;
    $: memValue = mem && mem.overall.point !== null ? pct(mem.overall.point) : undefined;
    $: memRange =
        mem && mem.overall.low !== null && mem.overall.high !== null
            ? ([pct(mem.overall.low), pct(mem.overall.high)] as [number, number])
            : undefined;
    $: memHowSure =
        mem && mem.overall.low !== null && mem.overall.high !== null
            ? howSure(mem.overall.low, mem.overall.high)
            : "";
    $: memUpdated = mem && mem.last_updated ? "Updated just now" : "";
    $: memMissing = memError
        ? "Could not load Memory. Try reopening the app."
        : (mem?.overall.reason ??
          "Review a few cards per topic to see your Memory. Seed sample content from the Study tab to start.");
</script>

<div class="main">
    <header class="head">
        <h1>Your knowledge map</h1>
        <p>Memory, performance, and readiness, shown honestly.</p>
    </header>

    <div class="hero">
        {#if use3d}
            <Manifold3D width={720} height={380} grid={84} heightScale={1.2} surface={FULL_SURFACE} />
        {:else}
            <Manifold width={720} height={360} scale={156} grid={90} surface={FULL_SURFACE} />
        {/if}
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
            </div>
            <div class="today-title">Start today's session</div>
            <div class="today-meta">Cards and problems, topics interleaved</div>
            <a class="start" href="/pgrep/study">
                Start session
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="2" y1="8" x2="13" y2="8" />
                    <polyline points="9,4 13,8 9,12" />
                </svg>
            </a>
        </section>

        {#if memAbstain}
            <ScoreCard
                kind="memory"
                abstain={{
                    message: memLoading ? "Loading Memory" : "Not enough reviews yet",
                    missing: memMissing,
                }}
            />
        {:else}
            <ScoreCard
                kind="memory"
                value={memValue}
                range={memRange}
                howSure={memHowSure}
                updated={memUpdated}
            />
        {/if}

        <ScoreCard
            kind="performance"
            abstain={{
                message: "No performance model yet",
                missing:
                    "Performance comes online with the AI problem set. It stays quiet until then.",
            }}
        />
        <ScoreCard
            kind="readiness"
            abstain={{
                missing:
                    "Readiness needs performance data and 70 percent topic coverage first. It stays quiet until then.",
            }}
        />
    </section>
</div>

<style lang="scss">
    .main {
        min-height: 100vh;
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
        text-decoration: none;
        transition: var(--transition-calm);

        &:hover {
            background: var(--action-bg-hover);
        }
    }
</style>
