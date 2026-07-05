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
    let readiness: ReadinessData | null = null;
    let loading = true;
    let seeding = false;
    let errored = false;
    // A calibration fetch that FAILS is distinct from a layer that genuinely has
    // no evidence: the former says "unavailable" (honest about the fetch), the
    // latter says "no evidence yet". Tracked so the panel never implies the model
    // is uncalibrated when it simply could not be loaded.
    let calibrationErrored = false;

    async function load(): Promise<void> {
        loading = true;
        errored = false;
        calibrationErrored = false;
        try {
            // Coverage is the primary read; calibration (embedded evidence) and
            // Readiness are secondary, so a hiccup on either abstains its panel
            // rather than failing the whole surface. All three are pure math and
            // return well within the 100ms feel.
            const [coverage, calib, ready] = await Promise.all([
                pgrepCall<CoverageData>("pgrepCoverage", {}),
                pgrepCall<CalibrationData>("pgrepCalibration", {}).catch(() => null),
                pgrepCall<ReadinessData>("pgrepReadinessScore", {}).catch(() => null),
            ]);
            data = coverage;
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

    onMount(load);

    function pct(value: number): number {
        return Math.round(value * 100);
    }

    function round3(value: number): number {
        return Math.round(value * 1000) / 1000;
    }

    function formatN(value: number): string {
        return value.toLocaleString("en-US");
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
                caption: "Calibration could not be loaded right now. Reload to try again.",
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
    $: segments = topics.map((t) => ({ topic: label(t.category), weight: t.blueprint, covered: t.covered ? 1 : 0 }));

    $: calibViews = [
        calibView("memory", "Memory", "Held-out reviews", calibration?.memory, calibrationErrored),
        calibView("performance", "Performance", "Held-out synthetic", calibration?.performance, calibrationErrored),
    ];

    // Coverage-gated Readiness: a scaled point + 80% range when covered, an honest
    // abstain that names the uncovered exam otherwise (the n=1 reality today).
    $: readinessCovered = !!readiness && !readiness.abstain && readiness.scaled != null;
    $: readinessRange =
        readinessCovered && readiness
            ? ([readiness.low, readiness.high] as [number, number])
            : undefined;
    $: readinessHowSure = readinessCovered && readiness ? `${pct(readiness.coverage_pct)} percent covered` : "";
    $: readinessAbstain = readinessAbstainState(readiness);
</script>

<section class="progress">
    <header class="head">
        <div class="head-text">
            <h1>Progress</h1>
            <p class="sub">Coverage gates Readiness. Calibration shows how honest the model is.</p>
        </div>
        <a class="diag-link" href="/pgrep/diagnostic">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="2,10 5.5,10 8,4.5 12,15.5 14.5,10 18,10" />
            </svg>
            Run the diagnostic
        </a>
    </header>

    {#if loading}
        <p class="muted">Loading coverage.</p>
    {:else if errored}
        <div class="panel notice">
            <p class="lead">Could not load coverage.</p>
            <button class="btn" on:click={load}>Try again</button>
        </div>
    {:else if data}
        <div class="panel">
            <div class="panel-head">
                <h2>Coverage</h2>
                <span class="count">{coveredCount} of {topics.length} categories started</span>
            </div>

            <CoverageBar
                {segments}
                coveredPct={pct(data.overall_pct)}
                threshold={pct(data.gate)}
                note="Reviewed coverage. Readiness gates separately on questions attempted, not cards reviewed."
            />

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
                                <span class="mem">Memory {pct(topic.memory_point)} percent</span>
                            {/if}
                        </div>
                    </li>
                {/each}
            </ul>

            {#if !anyCards}
                <p class="muted small seed-hint">Seed sample content to see your coverage.</p>
            {/if}

            <div class="actions">
                <button class="btn" on:click={seed} disabled={seeding}>
                    {seeding ? "Seeding sample content" : "Seed sample content"}
                </button>
                <span class="muted small">A category counts once it has one reviewed card.</span>
            </div>
        </div>

        <div class="readiness-block">
            <ScoreCard
                kind="readiness"
                value={readiness?.scaled ?? undefined}
                range={readinessRange}
                howSure={readinessHowSure}
                updated=""
                abstain={readinessAbstain}
            />
            <p class="muted small readiness-note">
                Readiness leans on Performance under exam conditions, gated on questions attempted (not cards reviewed).
                It abstains until at least {pct(readiness?.coverage_gate ?? 0.7)} percent of the exam has been attempted.
            </p>
        </div>

        <div class="panel">
            <div class="panel-head">
                <h2>Calibration</h2>
                <span class="count">How honest the model is</span>
            </div>
            <div class="calib">
                {#each calibViews as view (view.kind)}
                    <div class="calib-cell">
                        <span class="calib-tone" style="color: var(--{view.kind}-text);">{view.title}</span>
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
                            <p class="muted calib-prov" title={view.method}>{view.source}</p>
                        {/if}
                    </div>
                {/each}
            </div>
            <p class="muted small calib-note">
                Calibration compares each model's predicted chance against what actually happened on held-out data.
                The closer the line sits to the diagonal, the more honest the model.
            </p>
        </div>
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

    /* Diagnostic is a re-runnable flow, not a rail tab. Progress hosts a quiet
       monochrome re-run entry beside the coverage it informs. */
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

    .readiness-block {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

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
