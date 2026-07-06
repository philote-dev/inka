<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Progress (L2.4 + L5.5). The coverage ledger: how much of the blueprint you
have started on (a segmented bar, one segment per category weighted by the
blueprint, filled when covered), the overall fraction against the Readiness gate,
and a per-category list that reuses each topic's Memory point. It then shows the
coverage-gated Readiness score (point + 80% range when covered, an honest abstain
that names the uncovered exam otherwise) and the Calibration evidence: a
reliability diagram plus Brier for Memory and for Performance, from the embedded
offline evaluations (never the private content/ tree). Pure math over FSRS state,
tags, and embedded constants, no AI. Styled with the pgrep design system
(CoverageBar, ReliabilityDiagram, ScoreCard); the pgrepCall data flow is unchanged.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import CoverageBar from "$lib/components/CoverageBar.svelte";
    import ReliabilityDiagram from "$lib/components/ReliabilityDiagram.svelte";
    import ScoreCard from "$lib/components/ScoreCard.svelte";

    import { pgrepCall } from "../lib/bridge";

    interface CoverageTopic {
        category: string;
        blueprint: number;
        covered: boolean;
        n_cards: number;
        memory_point: number | null;
    }

    interface CoverageData {
        overall_pct: number;
        gate: number;
        by_topic: CoverageTopic[];
        abstain_note: string;
    }

    interface RelPoint {
        p: number;
        o: number;
    }

    interface CalibrationLayer {
        points: RelPoint[];
        brier: number | null;
        n: number;
        note: string;
        source: string;
        method: string;
        date: string;
    }

    interface CalibrationData {
        memory: CalibrationLayer;
        performance: CalibrationLayer;
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

    const CATEGORY_LABELS: Record<string, string> = {
        mechanics: "Mechanics",
        electromagnetism: "Electromagnetism",
        quantum: "Quantum",
        thermodynamics: "Thermodynamics",
        atomic: "Atomic physics",
        optics_waves: "Optics and waves",
        special_relativity: "Special relativity",
        lab: "Lab methods",
        specialized: "Specialized",
    };

    let data: CoverageData | null = null;
    let calibration: CalibrationData | null = null;
    let memory: MemoryData | null = null;
    let performance: PerformanceData | null = null;
    let readiness: ReadinessData | null = null;
    let loading = true;
    let seeding = false;
    let errored = false;
    // A calibration fetch that FAILS is distinct from a layer that genuinely has
    // no evidence: the former says "unavailable" (honest about the fetch), the
    // latter says "no evidence yet". Tracked so the panel never implies the model
    // is uncalibrated when it simply could not be loaded.
    let calibrationErrored = false;

    // Progress is split into tabs so each facet of the evidence lives in its own
    // home and the graphs are one click away, not a long scroll down the page.
    type Tab = "coverage" | "scores" | "calibration";
    let activeTab: Tab = "coverage";
    const TABS: { id: Tab; label: string }[] = [
        { id: "coverage", label: "Coverage" },
        { id: "scores", label: "Scores" },
        { id: "calibration", label: "Calibration" },
    ];

    async function load(): Promise<void> {
        loading = true;
        errored = false;
        calibrationErrored = false;
        try {
            // Coverage is the primary read; Performance, calibration (embedded
            // evidence), and Readiness are secondary, so a hiccup on any abstains
            // its own panel rather than failing the whole surface. All are pure
            // math and return well within the 100ms feel.
            const [coverage, mem, perf, calib, ready] = await Promise.all([
                pgrepCall<CoverageData>("pgrepCoverage", {}),
                pgrepCall<MemoryData>("pgrepMemoryScore", {}).catch(() => null),
                pgrepCall<PerformanceData>("pgrepPerformanceScore", {}).catch(
                    () => null,
                ),
                pgrepCall<CalibrationData>("pgrepCalibration", {}).catch(() => null),
                pgrepCall<ReadinessData>("pgrepReadinessScore", {}).catch(() => null),
            ]);
            data = coverage;
            memory = mem;
            performance = perf;
            calibration = calib;
            calibrationErrored = calib === null;
            readiness = ready;
        } catch {
            errored = true;
        } finally {
            loading = false;
        }
    }

    async function seed(): Promise<void> {
        seeding = true;
        errored = false;
        try {
            await pgrepCall("pgrepSeed", {});
            await load();
        } catch {
            errored = true;
        } finally {
            seeding = false;
        }
    }

    onMount(() => {
        void load();
    });

    function pct(value: number): number {
        return Math.round(value * 100);
    }

    function round3(value: number): number {
        return Math.round(value * 1000) / 1000;
    }

    // How-sure read from the 80% interval width (on the 0..1 scale), matching
    // Home. A tighter range reads as more confident.
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

    function formatN(value: number): string {
        return value.toLocaleString("en-US");
    }

    // Last-updated read for the score cards, from an epoch-seconds timestamp
    // (performance.py writes int(time.time())). Empty when there is nothing to
    // date yet, so the card never invents a freshness it does not have.
    function formatUpdated(ts: number | null | undefined): string {
        if (ts == null) {
            return "";
        }
        const seconds = Math.floor(Date.now() / 1000 - ts);
        if (!Number.isFinite(seconds) || seconds < 0) {
            return "";
        }
        if (seconds < 90) {
            return "Updated just now";
        }
        const minutes = Math.round(seconds / 60);
        if (minutes < 60) {
            return `Updated ${minutes}m ago`;
        }
        const hours = Math.round(minutes / 60);
        if (hours < 24) {
            return `Updated ${hours}h ago`;
        }
        const days = Math.round(hours / 24);
        return `Updated ${days}d ago`;
    }

    function label(slug: string): string {
        return CATEGORY_LABELS[slug] ?? slug.replace(/_/g, " ");
    }

    function cardCount(n: number): string {
        return `${n} ${n === 1 ? "card" : "cards"}`;
    }

    // One reliability view per model layer. Honors the abstain rule with an honest
    // three-way split: a FAILED fetch says "unavailable" (we could not load it), a
    // layer with genuinely no evidence says "no evidence yet", and a scored layer
    // draws its curve with a rounded Brier, an honest caption, and its provenance.
    interface CalibView {
        kind: "memory" | "performance";
        title: string;
        read: string;
        caption: string;
        points: RelPoint[];
        brier: number | null;
        meta: string;
        source: string;
        method: string;
    }

    function calibView(
        kind: "memory" | "performance",
        title: string,
        read: string,
        layer: CalibrationLayer | undefined,
        failed: boolean,
    ): CalibView {
        if (failed) {
            // Fetch failure, not an absence of evidence: mirror how Readiness
            // reports "unavailable" rather than implying the model is uncalibrated.
            return {
                kind,
                title,
                read: "Calibration unavailable",
                caption:
                    "Calibration could not be loaded right now. Reload to try again.",
                points: [],
                brier: null,
                meta: "",
                source: "",
                method: "",
            };
        }
        if (!layer || layer.points.length === 0) {
            return {
                kind,
                title,
                read: "Not enough graded evidence yet",
                caption: "No calibration evidence for this layer yet.",
                points: [],
                brier: null,
                meta: "",
                source: "",
                method: "",
            };
        }
        return {
            kind,
            title,
            read,
            caption: layer.note,
            points: layer.points,
            brier: layer.brier != null ? round3(layer.brier) : null,
            meta: `n ${formatN(layer.n)} · ${layer.date}`,
            source: layer.source,
            method: layer.method,
        };
    }

    // Memory abstains honestly on thin data: with no reviews yet every topic is
    // below k_mem, so the overall abstains and names what is missing (reviews in
    // the Cards door). Same engine as Home's Memory card, so they never disagree.
    function memoryAbstainState(
        m: MemoryData | null,
    ): { message: string; missing?: string } | undefined {
        if (!m) {
            return { message: "Memory is unavailable right now." };
        }
        if (!m.overall.abstain && m.overall.point !== null) {
            return undefined;
        }
        return {
            message: m.overall.reason ?? "Not enough reviews yet",
            missing: "Review cards in the Cards door to build this.",
        };
    }

    // Performance abstains honestly on thin data: with today's empty attempt log
    // every topic is below k_perf, so the overall abstains and names what is
    // missing (attempts through the Problems door), never a fabricated number.
    function performanceAbstainState(
        p: PerformanceData | null,
    ): { message: string; missing?: string } | undefined {
        if (!p) {
            return { message: "Performance is unavailable right now." };
        }
        if (!p.overall.abstain && p.overall.point !== null) {
            return undefined;
        }
        return {
            message: p.overall.reason ?? "Not enough attempts yet",
            missing: "Work problems in the Problems door to build this.",
        };
    }

    function readinessAbstainState(
        r: ReadinessData | null,
    ): { message: string; missing?: string } | undefined {
        if (!r) {
            return { message: "Readiness is unavailable right now." };
        }
        if (!r.abstain) {
            return undefined;
        }
        const names = r.uncovered_topics.map(label).join(", ");
        return {
            message: r.reason ?? "Not enough of the exam is covered yet",
            missing: names ? `Cover ${names} to unlock Readiness.` : undefined,
        };
    }

    $: topics = data ? data.by_topic : [];
    $: coveredCount = topics.filter((t) => t.covered).length;
    $: anyCards = topics.some((t) => t.n_cards > 0);
    $: segments = topics.map((t) => ({
        topic: label(t.category),
        weight: t.blueprint,
        covered: t.covered ? 1 : 0,
    }));

    $: calibViews = [
        calibView(
            "memory",
            "Memory",
            "Held-out reviews",
            calibration?.memory,
            calibrationErrored,
        ),
        calibView(
            "performance",
            "Performance",
            "Held-out synthetic",
            calibration?.performance,
            calibrationErrored,
        ),
    ];

    // Live Memory: the overall FSRS retrievability as a percent with an 80% range
    // and a how-sure from the interval, or an honest abstain on thin data. The
    // same engine as Home's Memory card, so the two never disagree.
    $: memoryCovered =
        !!memory && !memory.overall.abstain && memory.overall.point !== null;
    $: memoryValue =
        memoryCovered && memory && memory.overall.point !== null
            ? pct(memory.overall.point)
            : undefined;
    $: memoryRange =
        memoryCovered &&
        memory &&
        memory.overall.low !== null &&
        memory.overall.high !== null
            ? ([pct(memory.overall.low), pct(memory.overall.high)] as [number, number])
            : undefined;
    $: memoryHowSure =
        memoryCovered &&
        memory &&
        memory.overall.low !== null &&
        memory.overall.high !== null
            ? howSure(memory.overall.low, memory.overall.high)
            : "";
    $: memoryAbstain = memoryAbstainState(memory);
    $: memoryUpdated = memoryCovered ? formatUpdated(memory?.last_updated) : "";

    // Live Performance: the overall P(correct) as a percent with an 80% range and
    // a how-sure read from the interval, or an honest abstain on thin data. This
    // is the transfer signal Readiness leans on, so it reads just above it.
    $: performanceCovered =
        !!performance &&
        !performance.overall.abstain &&
        performance.overall.point !== null;
    $: performanceValue =
        performanceCovered && performance && performance.overall.point !== null
            ? pct(performance.overall.point)
            : undefined;
    $: performanceRange =
        performanceCovered &&
        performance &&
        performance.overall.low !== null &&
        performance.overall.high !== null
            ? ([pct(performance.overall.low), pct(performance.overall.high)] as [
                  number,
                  number,
              ])
            : undefined;
    $: performanceHowSure =
        performanceCovered &&
        performance &&
        performance.overall.low !== null &&
        performance.overall.high !== null
            ? howSure(performance.overall.low, performance.overall.high)
            : "";
    $: performanceAbstain = performanceAbstainState(performance);
    $: performanceUpdated = performanceCovered
        ? formatUpdated(performance?.last_updated)
        : "";

    // Coverage-gated Readiness: a scaled point + 80% range when covered, an honest
    // abstain that names the uncovered exam otherwise (the n=1 reality today).
    $: readinessCovered = !!readiness && !readiness.abstain && readiness.scaled != null;
    $: readinessRange =
        readinessCovered && readiness
            ? ([readiness.low, readiness.high] as [number, number])
            : undefined;
    $: readinessHowSure =
        readinessCovered && readiness
            ? `${pct(readiness.coverage_pct)} percent covered`
            : "";
    $: readinessAbstain = readinessAbstainState(readiness);
    $: readinessUpdated = readinessCovered
        ? formatUpdated(readiness?.last_updated)
        : "";
</script>

<section class="progress">
    <header class="head">
        <div class="head-text">
            <h1>Progress</h1>
            <p class="sub">
                Coverage gates Readiness. Calibration shows how honest the model is.
            </p>
        </div>
    </header>

    {#if loading}
        <div class="panel skel" aria-hidden="true">
            <div class="skel-head">
                <span class="skel-block title"></span>
                <span class="skel-block count"></span>
            </div>
            <span class="skel-block bar"></span>
            <div class="skel-rows">
                <span class="skel-block row"></span>
                <span class="skel-block row"></span>
                <span class="skel-block row"></span>
                <span class="skel-block row"></span>
            </div>
        </div>
        <p class="muted small skel-note">Reading your coverage.</p>
    {:else if errored}
        <div class="panel notice">
            <p class="lead">Could not load coverage.</p>
            <button class="btn" on:click={load}>Try again</button>
        </div>
    {:else if data}
        <div class="tabs" role="tablist" aria-label="Progress sections">
            {#each TABS as t (t.id)}
                <button
                    class="tab"
                    class:on={activeTab === t.id}
                    role="tab"
                    aria-selected={activeTab === t.id}
                    on:click={() => (activeTab = t.id)}
                >
                    {t.label}
                </button>
            {/each}
        </div>

        {#if activeTab === "coverage"}
            <div class="panel">
                <div class="panel-head">
                    <h2>Coverage</h2>
                    <span class="count">
                        {coveredCount} of {topics.length} categories started
                    </span>
                </div>

                <div class="cov-hero">
                    <div class="cov-figure">
                        <div class="cov-pct">
                            <span class="cov-num">{pct(data.overall_pct)}</span>
                            <span class="cov-unit">%</span>
                        </div>
                        <div class="cov-cap">of the exam covered</div>
                    </div>
                    <div class="cov-track">
                        <span class="cov-gate">
                            Readiness needs {pct(data.gate)} percent
                        </span>
                        <CoverageBar
                            {segments}
                            coveredPct={pct(data.overall_pct)}
                            threshold={pct(data.gate)}
                            showHead={false}
                            showLabels={false}
                        />
                    </div>
                </div>

                <p class="cov-note">
                    Reviewed coverage. Readiness gates separately on questions
                    attempted, not cards reviewed.
                </p>

                <ul class="topics">
                    {#each topics as topic (topic.category)}
                        <li class="topic" class:uncovered={!topic.covered}>
                            <div class="row">
                                <span class="name">{label(topic.category)}</span>
                                <span class="status" class:on={topic.covered}>
                                    {topic.covered ? "Covered" : "Not covered"}
                                </span>
                            </div>
                            <div class="rowsub">
                                <span>Blueprint {pct(topic.blueprint)} percent</span>
                                <span>{cardCount(topic.n_cards)}</span>
                                {#if topic.memory_point !== null}
                                    <span class="mem">
                                        Memory {pct(topic.memory_point)} percent
                                    </span>
                                {/if}
                            </div>
                        </li>
                    {/each}
                </ul>

                {#if !anyCards}
                    <p class="muted small seed-hint">
                        Seed sample content to see your coverage.
                    </p>
                {/if}

                <div class="actions">
                    <button class="btn" on:click={seed} disabled={seeding}>
                        {seeding ? "Seeding sample content" : "Seed sample content"}
                    </button>
                    <span class="muted small">
                        A category counts once it has one reviewed card.
                    </span>
                </div>
            </div>
        {/if}

        {#if activeTab === "scores"}
            <div class="memory-block">
                <ScoreCard
                    kind="memory"
                    value={memoryValue}
                    range={memoryRange}
                    howSure={memoryHowSure}
                    updated={memoryUpdated}
                    abstain={memoryAbstain}
                />
                <p class="muted small memory-note">
                    Memory is your recall on the cards you have reviewed (FSRS
                    retrievability). It abstains until a topic has enough reviews.
                </p>
            </div>

            <div class="performance-block">
                <ScoreCard
                    kind="performance"
                    value={performanceValue}
                    range={performanceRange}
                    howSure={performanceHowSure}
                    updated={performanceUpdated}
                    abstain={performanceAbstain}
                />
                <p class="muted small performance-note">
                    Performance is your chance on a new, unseen problem, read from the
                    problems you attempt (not cards reviewed). It abstains until a topic
                    has at least {performance?.k_perf ?? 8} attempts.
                </p>
            </div>

            <div class="readiness-block">
                <ScoreCard
                    kind="readiness"
                    value={readiness?.scaled ?? undefined}
                    range={readinessRange}
                    howSure={readinessHowSure}
                    updated={readinessUpdated}
                    abstain={readinessAbstain}
                />
                <p class="muted small readiness-note">
                    Readiness leans on Performance under exam conditions, gated on
                    questions attempted (not cards reviewed). It abstains until at least {pct(
                        readiness?.coverage_gate ?? 0.7,
                    )} percent of the exam has been attempted.
                </p>
            </div>
        {/if}

        {#if activeTab === "calibration"}
            <div class="panel">
                <div class="panel-head">
                    <h2>Calibration</h2>
                    <span class="count">How honest the model is</span>
                </div>
                <div class="calib">
                    {#each calibViews as view (view.kind)}
                        <div class="calib-cell">
                            <span
                                class="calib-tone"
                                style="color: var(--{view.kind}-text);"
                            >
                                {view.title}
                            </span>
                            <ReliabilityDiagram
                                points={view.points}
                                brier={view.brier}
                                read={view.read}
                                tone={view.kind}
                                size={200}
                            />
                            <p class="muted small calib-cell-note">{view.caption}</p>
                            {#if view.meta}
                                <p class="muted calib-meta">{view.meta}</p>
                            {/if}
                            {#if view.source}
                                <p class="muted calib-prov" title={view.method}>
                                    {view.source}
                                </p>
                            {/if}
                        </div>
                    {/each}
                </div>
                <p class="muted small calib-note">
                    Calibration compares each model's predicted chance against what
                    actually happened on held-out data. The closer the line sits to the
                    diagonal, the more honest the model.
                </p>
            </div>
        {/if}
    {/if}
</section>

<style lang="scss">
    .progress {
        max-width: 680px;
        margin: 0 auto;
        padding: 48px 24px 64px;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .head {
        margin-bottom: var(--space-1);
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: var(--space-2);

        h1 {
            margin: 0;
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        .sub {
            margin: 6px 0 0;
            color: var(--muted);
            font-size: var(--text-body);
        }
    }

    /* Section switch: a monochrome segmented control (chrome, not score data).
       The three evidence views read as one control; the active facet lifts onto
       a surface pill inside the warm inset track. Host buttons inherit a faint
       rounded box-shadow and radius from Anki's base CSS, so every chrome
       property is reset here explicitly, or the pills render as ghost boxes. */
    .tabs {
        display: inline-flex;
        align-self: flex-start;
        gap: var(--space-0);
        padding: var(--space-0);
        background: var(--elevated);
        border: var(--hairline);
        border-radius: var(--radius-control);
        margin-bottom: var(--space-1);
    }

    .tab {
        appearance: none;
        border: none;
        box-shadow: none;
        background: transparent;
        border-radius: calc(var(--radius-control) - var(--space-0));
        padding: 7px 16px;
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        line-height: 1;
        color: var(--muted);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover:not(.on) {
            color: var(--text);
        }

        &.on {
            color: var(--text);
            background: var(--surface);
            box-shadow: var(--shadow-card);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
        }
    }

    /* Phone: let the control span the column so the three facets stay tappable. */
    @media (max-width: 640px) {
        .tabs {
            align-self: stretch;
        }

        .tab {
            flex: 1 1 0;
            text-align: center;
        }
    }

    /* Loading skeleton, mirroring the coverage panel's shape. */
    .skel-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: var(--space-2);
    }

    .skel-block {
        display: block;
        background: var(--elevated);
        border-radius: 6px;
        animation: pgrep-skel 2.4s ease-in-out infinite;

        &.title {
            width: 120px;
            height: 18px;
        }

        &.count {
            width: 96px;
            height: 12px;
        }

        &.bar {
            width: 100%;
            height: 10px;
            border-radius: 4px;
            margin-bottom: var(--space-3);
        }

        &.row {
            height: 46px;
            border-radius: var(--radius-row);
        }
    }

    .skel-rows {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .skel-note {
        margin: var(--space-2) 0 0;
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
        .skel-block {
            animation: none;
        }
    }

    .panel {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
    }

    .panel-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--space-2);
        margin-bottom: var(--space-2);

        h2 {
            margin: 0;
            font-size: var(--text-emphasis);
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        .count {
            font-size: var(--text-small);
            color: var(--muted);
            font-variant-numeric: tabular-nums;
        }
    }

    /* Coverage hero: the covered fraction reads as the number that matters, set
       beside the segmented bar it summarises. Monochrome throughout, because
       coverage is not one of the three reserved score hues. */
    .cov-hero {
        display: flex;
        align-items: center;
        gap: var(--space-4);
        margin: var(--space-2) 0 var(--space-1);
    }

    .cov-figure {
        flex: 0 0 auto;
    }

    /* inline-flex so the whitespace between the number and the unit is dropped,
       and the small percent sign sits on the number's baseline. */
    .cov-pct {
        display: inline-flex;
        align-items: baseline;
        font-family: var(--font-mono);
        font-size: var(--text-score);
        font-weight: 500;
        line-height: 1;
        letter-spacing: -0.02em;
        font-variant-numeric: tabular-nums;
    }

    .cov-unit {
        margin-left: 2px;
        font-size: 0.5em;
        font-weight: 500;
        color: var(--muted);
    }

    .cov-cap {
        margin-top: var(--space-1);
        font-size: var(--text-small);
        color: var(--muted);
    }

    .cov-track {
        flex: 1 1 auto;
        min-width: 0;
    }

    .cov-gate {
        display: block;
        margin-bottom: 8px;
        text-align: right;
        font-family: var(--font-mono);
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .cov-note {
        margin: 0 0 var(--space-1);
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    /* Phone: stack the number above the bar so neither is squeezed. */
    @media (max-width: 640px) {
        .cov-hero {
            flex-direction: column;
            align-items: stretch;
            gap: var(--space-2);
        }

        .cov-gate {
            text-align: left;
        }
    }

    .topics {
        list-style: none;
        margin: var(--space-2) 0 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .topic {
        padding: 12px 14px;
        border: var(--hairline);
        border-radius: var(--radius-row);

        &.uncovered {
            opacity: 0.68;
        }
    }

    .row {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--space-2);

        .name {
            font-weight: 500;
            font-size: var(--text-body);
        }

        .status {
            font-size: var(--text-small);
            color: var(--muted);

            &.on {
                color: var(--text);
                font-weight: 500;
            }
        }
    }

    .rowsub {
        display: flex;
        gap: var(--space-2);
        flex-wrap: wrap;
        margin-top: 6px;
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;

        .mem {
            color: var(--memory-text);
        }
    }

    .memory-block,
    .performance-block,
    .readiness-block {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .memory-note,
    .performance-note,
    .readiness-note {
        margin: 0;
        line-height: 1.55;
        max-width: 62ch;
    }

    .calib {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: var(--space-3);
        align-items: start;
    }

    .calib-cell {
        display: flex;
        flex-direction: column;
        gap: var(--space-0);
        min-width: 0;
    }

    .calib-tone {
        font-size: var(--text-small);
        font-weight: 600;
        letter-spacing: 0.01em;
    }

    .calib-cell-note {
        margin: var(--space-0) 0 0;
        line-height: 1.5;
    }

    .calib-meta {
        margin: 2px 0 0;
        font-size: var(--text-caption);
        font-variant-numeric: tabular-nums;
    }

    .calib-prov {
        margin: 2px 0 0;
        font-size: var(--text-caption);
        line-height: 1.45;
        cursor: help;
    }

    .calib-note {
        margin: var(--space-2) 0 0;
        line-height: 1.55;
    }

    .actions {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
        margin-top: var(--space-2);
    }

    .seed-hint {
        margin: var(--space-2) 0 0;
    }

    .notice {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--space-1);
    }

    .lead {
        margin: 0;
        font-size: var(--text-emphasis);
        font-weight: 600;
    }

    .muted {
        color: var(--muted);
    }

    .small {
        font-size: var(--text-small);
    }

    .btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 16px;
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        border-radius: var(--radius-control);
        border: var(--hairline);
        background: var(--surface);
        color: var(--text);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            background: var(--hover-wash);
            border-color: var(--muted);
        }

        &:disabled {
            cursor: default;
            opacity: 0.55;
        }
    }
</style>
