<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep Home (Readiness). The manifold hero + three score cards. All three are
     wired to their real engines (pgrepMemoryScore, pgrepPerformanceScore,
     pgrepReadinessScore) and abstain honestly on thin data, naming what is
     missing. No mock scores. The shared nav lives in +layout.svelte. -->
<script lang="ts">
    import { goto } from "$app/navigation";
    import { onMount } from "svelte";

    import CompactScoreCard from "$lib/components/CompactScoreCard.svelte";
    import Manifold3D from "$lib/components/Manifold3D.svelte";
    import ManifoldTopView from "$lib/components/ManifoldTopView.svelte";
    import { FULL_SURFACE, type Surface } from "$lib/pgrep/manifold";
    import { supportsWebGL } from "$lib/pgrep/manifold3d";
    import { manifoldView, type ManifoldView } from "$lib/pgrep/prefs";

    import { pgrepCall } from "./lib/bridge";

    // Tapping a manifold topic (label or region) opens the Study focus drill
    // scoped to it (ux-foundation 5). Study reads the topic from the query and
    // the learner then picks the Cards or Problems door.
    function openFocusDrill(topic: string): void {
        void goto(`/pgrep/study?topic=${encodeURIComponent(topic)}`);
    }

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

    interface PerformanceData {
        overall: OverallScore;
        k_perf: number;
        coverage_pct: number;
        coverage_gate: number;
        last_updated: number | null;
    }

    interface ReadinessData {
        scaled: number | null;
        low: number | null;
        high: number | null;
        coverage_pct: number;
        coverage_gate: number;
        abstain: boolean;
        reason: string | null;
        uncovered_topics: string[];
        last_updated: number | null;
    }

    // Device capability, read on mount. The manifold view preference (Settings)
    // then decides the projection: "auto" shows the 3D wireframe where WebGL and
    // motion allow and the flat top-down map otherwise; "wire"/"map" force one.
    let canWebGL = false;
    let reduceMotion = false;
    function manifoldMode(
        pref: ManifoldView,
        gl: boolean,
        reduce: boolean,
    ): "wire" | "map" {
        if (pref === "wire") {
            return "wire";
        }
        if (pref === "map") {
            return "map";
        }
        return gl && !reduce ? "wire" : "map";
    }
    $: heroMode = manifoldMode($manifoldView, canWebGL, reduceMotion);

    // The hero fills the content column (bound to its measured width), so it never
    // sits as a fixed island beside a wider card row. Height tracks width at the
    // reference's roughly 2:1 framing.
    let heroWidth = 960;
    $: heroHeight = Math.max(240, Math.round(heroWidth * 0.5));

    // Diagnostic is first-run and re-runnable (ux-foundation 7.6). Show the
    // prompt only until it has been completed once. null while unknown so a
    // completed learner never sees a flash of the prompt; a failed read falls
    // open to showing it, so a first-run learner always has the entry.
    let diagnosticDone: boolean | null = null;

    // Each card owns its own loading/error/data so one slow or failed call
    // abstains its own card rather than blocking the surface. All three scores
    // are pure AI-off math and return well within the 100ms feel.
    let mem: MemoryData | null = null;
    let memLoading = true;
    let memError = false;

    let perf: PerformanceData | null = null;
    let perfLoading = true;
    let perfError = false;

    let ready: ReadinessData | null = null;
    let readyLoading = true;
    let readyError = false;

    // The manifold hero starts on the static syllabus surface, then swaps to the
    // live one built from real Memory and the diagnostic (an untouched area stays
    // unlit, a studied area rises and glows). The static surface is only the
    // pre-load and error fallback, so the hero is never blank.
    let surface: Surface = FULL_SURFACE;

    async function loadScores(): Promise<void> {
        await Promise.all([
            pgrepCall<MemoryData>("pgrepMemoryScore", {})
                .then((d) => {
                    mem = d;
                })
                .catch(() => {
                    memError = true;
                })
                .finally(() => {
                    memLoading = false;
                }),
            pgrepCall<PerformanceData>("pgrepPerformanceScore", {})
                .then((d) => {
                    perf = d;
                })
                .catch(() => {
                    perfError = true;
                })
                .finally(() => {
                    perfLoading = false;
                }),
            pgrepCall<ReadinessData>("pgrepReadinessScore", {})
                .then((d) => {
                    ready = d;
                })
                .catch(() => {
                    readyError = true;
                })
                .finally(() => {
                    readyLoading = false;
                }),
        ]);
    }

    async function loadDiagnosticStatus(): Promise<void> {
        try {
            const status = await pgrepCall<{ completed: boolean }>(
                "pgrepDiagnosticStatus",
                {},
            );
            diagnosticDone = status.completed;
        } catch {
            diagnosticDone = false;
        }
    }

    async function loadManifold(): Promise<void> {
        try {
            surface = await pgrepCall<Surface>("pgrepManifold", {});
        } catch {
            // Keep the static syllabus surface if the live read fails.
        }
    }

    onMount(() => {
        reduceMotion =
            window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
        canWebGL = supportsWebGL();
        void loadScores();
        void loadDiagnosticStatus();
        void loadManifold();
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
    $: memValue =
        mem && mem.overall.point !== null ? pct(mem.overall.point) : undefined;
    $: memRange =
        mem && mem.overall.low !== null && mem.overall.high !== null
            ? ([pct(mem.overall.low), pct(mem.overall.high)] as [number, number])
            : undefined;
    $: memHowSure =
        mem && mem.overall.low !== null && mem.overall.high !== null
            ? howSure(mem.overall.low, mem.overall.high)
            : "";

    $: perfAbstain = !perf || perf.overall.abstain || perf.overall.point === null;
    $: perfValue =
        perf && perf.overall.point !== null ? pct(perf.overall.point) : undefined;
    $: perfRange =
        perf && perf.overall.low !== null && perf.overall.high !== null
            ? ([pct(perf.overall.low), pct(perf.overall.high)] as [number, number])
            : undefined;
    $: perfHowSure =
        perf && perf.overall.low !== null && perf.overall.high !== null
            ? howSure(perf.overall.low, perf.overall.high)
            : "";

    // Readiness ships a 200..990 scaled score (not a percent), so its value and
    // range pass through untouched. The how-sure read is coverage, the gate it
    // lives under.
    $: readyAbstain = !ready || ready.abstain || ready.scaled === null;
    $: readyValue = ready && ready.scaled !== null ? ready.scaled : undefined;
    $: readyRange =
        ready && ready.low !== null && ready.high !== null
            ? ([ready.low, ready.high] as [number, number])
            : undefined;
    $: readyHowSure =
        ready && !ready.abstain ? `${pct(ready.coverage_pct)} percent covered` : "";

    // Short abstain lines for the compact Home tiles. The full "what is missing"
    // text and its link stay on the Progress ScoreCard; here we keep one honest,
    // compact phrase (never a fabricated number).
    function reasonShort(loading: boolean, errored: boolean, thin: string): string {
        if (loading) {
            return "Loading";
        }
        if (errored) {
            return "Unavailable";
        }
        return thin;
    }
    $: memReasonShort = reasonShort(memLoading, memError, "Not enough yet");
    $: perfReasonShort = reasonShort(perfLoading, perfError, "Not enough yet");
    $: readyReasonShort = reasonShort(readyLoading, readyError, "Low coverage");
</script>

<div class="main">
    <header class="head">
        <div class="head-text">
            <h1>Your knowledge map</h1>
        </div>
        {#if diagnosticDone === false}
            <a class="diag-link" href="/pgrep/diagnostic">
                <svg
                    width="16"
                    height="16"
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                >
                    <polyline points="2,10 5.5,10 8,4.5 12,15.5 14.5,10 18,10" />
                </svg>
                Run the diagnostic
            </a>
        {/if}
    </header>

    <div class="hero" bind:clientWidth={heroWidth}>
        {#if heroMode === "wire"}
            <Manifold3D
                width={heroWidth}
                height={heroHeight}
                grid={90}
                heightScale={1.2}
                vibrance={0.7}
                labelLayout="radial"
                chipStrength={0.6}
                distance={4.4}
                {surface}
                onTopic={openFocusDrill}
            />
        {:else}
            <ManifoldTopView
                width={heroWidth}
                height={heroHeight}
                {surface}
                showReadouts={false}
                showLegend={false}
                onTopic={openFocusDrill}
            />
        {/if}
    </div>

    <section class="today band">
        <div class="band-text">
            <div class="today-label">
                <svg
                    width="20"
                    height="20"
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                >
                    <polygon points="5,3.5 16,10 5,16.5" />
                </svg>
                <span>Today</span>
            </div>
            <div class="today-meta">Cards and problems, interleaved</div>
        </div>
        <a class="start" href="/pgrep/study">
            Start session
            <svg
                width="14"
                height="14"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
            >
                <line x1="2" y1="8" x2="13" y2="8" />
                <polyline points="9,4 13,8 9,12" />
            </svg>
        </a>
    </section>

    <!-- Home shows the compact score tiles (three-across, shrinking to fit). The
         full ScoreCard anatomy, with the missing text and link, lives on Progress. -->
    <section class="scores">
        <CompactScoreCard
            kind="memory"
            value={memValue}
            range={memRange}
            howSure={memHowSure}
            abstain={memAbstain}
            reason={memReasonShort}
        />
        <CompactScoreCard
            kind="performance"
            value={perfValue}
            range={perfRange}
            howSure={perfHowSure}
            abstain={perfAbstain}
            reason={perfReasonShort}
        />
        <CompactScoreCard
            kind="readiness"
            value={readyValue}
            range={readyRange}
            howSure={readyHowSure}
            abstain={readyAbstain}
            reason={readyReasonShort}
        />
    </section>
</div>

<style lang="scss">
    .main {
        min-height: 100%;
        padding: 32px 36px 36px;
        display: flex;
        flex-direction: column;
        /* Cap and left-anchor the content next to the rail, matching the mockup's
           ~1150px column, so nothing stretches on wide windows. The column is a
           size container, so the score row reflows by its own width. */
        max-width: 1150px;
        container-type: inline-size;
    }

    .head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--space-2);

        h1 {
            margin: 0;
            font-size: var(--text-greeting);
            font-weight: 600;
            letter-spacing: -0.02em;
        }
    }

    /* Diagnostic is a re-runnable flow, not a rail tab, so Home offers a quiet
       monochrome entry into it. It seeds the manifold above. */
    .diag-link {
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px;
        border: var(--hairline);
        border-radius: var(--radius-control);
        color: var(--muted);
        text-decoration: none;
        font-size: var(--text-body);
        font-weight: 500;
        white-space: nowrap;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
            border-color: var(--muted);
        }
    }

    .hero {
        flex: 0 0 auto;
        width: 100%;
        margin: 8px 0 16px;
    }

    /* The three compact score tiles stay side by side and shrink to fit, so a
       moderately narrow window still shows all three without a long scroll.
       They reflow only when the content column gets genuinely tiny: two up
       first, then a single column. minmax(0, 1fr) lets each tile shrink below
       its content width (paired with min-width: 0 and ellipsis in the tile). */
    .scores {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: var(--space-1);
        align-items: stretch;
    }

    @container (max-width: 360px) {
        .scores {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }

    @container (max-width: 220px) {
        .scores {
            grid-template-columns: 1fr;
        }
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

    /* Option C: Today leads as a full-width band, the session action on the right.
       Stacks the action under the text when the column is narrow. */
    .today.band {
        flex-direction: row;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
        margin-bottom: var(--space-2);
    }

    .band-text {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 0;
    }

    @container (max-width: 520px) {
        .today.band {
            flex-direction: column;
            align-items: flex-start;
        }
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

    .today-meta {
        font-size: 13px;
        color: var(--muted);
    }

    .today.band .start {
        margin-top: 0;
        align-self: center;
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
