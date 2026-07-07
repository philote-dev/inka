<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Manifold lab. The single home for the readiness surface. Three parts: the
     production 3D renderer shown across a learner's journey with the live color and
     label controls; the data-to-shape playground (./Playground.svelte) where editing
     the units reshapes the surface; and the hue-scheme comparison. Terrain is held
     identical across schemes so only the color variable differs. Synthetic data, a
     design surface, not a product screen. -->
<script lang="ts">
    import { onMount } from "svelte";

    import Manifold3D from "$lib/components/Manifold3D.svelte";
    import ManifoldTopView from "$lib/components/ManifoldTopView.svelte";
    import Playground from "./Playground.svelte";
    import {
        type Bump,
        FULL_SURFACE,
        type Glow,
        type Hole,
        type ManifoldLabel,
        type Surface,
    } from "$lib/pgrep/manifold";

    // Reserved score hues (match SCORE_COLORS in manifold.ts) plus an unlit neutral.
    const AMBER = [235, 203, 139];
    const BLUE = [129, 161, 193];
    const LILAC = [196, 167, 214];
    const NEUTRAL = [150, 150, 150];

    const COVERAGE_GATE = 0.4;
    const READY_PERF = 0.7;
    const WEAK_MEMORY = 0.45;

    type Diag = "strong" | "rusty";

    interface Area {
        slug: string;
        name: string;
        x: number;
        y: number;
        weight: number;
        dx: number;
        dy: number;
        tf: string;
    }

    // The nine exam areas: fixed map position, blueprint weight (footprint), and
    // label offsets, mirroring ts/lib/pgrep/manifold.ts and pylib/anki/pgrep/manifold.py.
    // prettier-ignore
    const AREAS: Area[] = [
        { slug: "mechanics", name: "Classical Mechanics", x: -0.6, y: -0.5, weight: 0.2, dx: -60, dy: -44, tf: "translate(-100%, -100%)" },
        { slug: "electromagnetism", name: "Electromagnetism", x: 0.56, y: -0.48, weight: 0.18, dx: 30, dy: -60, tf: "translate(0, -100%)" },
        { slug: "optics_waves", name: "Optics & Waves", x: 1.0, y: -0.14, weight: 0.08, dx: 54, dy: -22, tf: "translate(0, -100%)" },
        { slug: "thermodynamics", name: "Thermo & Stat Mech", x: -1.05, y: 0.14, weight: 0.1, dx: -54, dy: 26, tf: "translate(-100%, 0)" },
        { slug: "quantum", name: "Quantum Mechanics", x: 0.16, y: 0.6, weight: 0.13, dx: -60, dy: 40, tf: "translate(-100%, 0)" },
        { slug: "atomic", name: "Atomic Physics", x: 0.72, y: 0.4, weight: 0.1, dx: 64, dy: 46, tf: "translate(0, 0)" },
        { slug: "special_relativity", name: "Special Relativity", x: -0.56, y: 0.62, weight: 0.06, dx: -50, dy: 62, tf: "translate(-100%, 0)" },
        { slug: "lab", name: "Laboratory Methods", x: -0.05, y: -0.62, weight: 0.06, dx: 10, dy: -60, tf: "translate(-50%, -100%)" },
        { slug: "specialized", name: "Specialized Topics", x: 0.16, y: 0.04, weight: 0.09, dx: 30, dy: 60, tf: "translate(0, 0)" },
    ];

    // A per-area learner state at one moment: the diagnostic placement plus the
    // three raw signals (null where that score has not earned a value yet).
    interface State {
        diag: Diag;
        mem: number | null; // Memory point (FSRS retrievability)
        cov: number; // Coverage 0..1 (attempt count over the gate)
        perf: number | null; // Performance point P(correct)
    }

    // One learner's journey. Four moments, told honestly: placement, then
    // memorizing, then problem work (with real gaps), then exam approach. Each
    // area carries its four states in order.
    // prettier-ignore
    const JOURNEY: Record<string, State[]> = {
        mechanics: [
            { diag: "strong", mem: null, cov: 0, perf: null },
            { diag: "strong", mem: 0.82, cov: 0, perf: null },
            { diag: "strong", mem: 0.84, cov: 0.7, perf: 0.82 },
            { diag: "strong", mem: 0.85, cov: 1, perf: 0.86 },
        ],
        electromagnetism: [
            { diag: "strong", mem: null, cov: 0, perf: null },
            { diag: "strong", mem: 0.7, cov: 0, perf: null },
            { diag: "strong", mem: 0.72, cov: 0.6, perf: 0.68 },
            { diag: "strong", mem: 0.75, cov: 1, perf: 0.74 },
        ],
        optics_waves: [
            { diag: "rusty", mem: null, cov: 0, perf: null },
            { diag: "rusty", mem: 0.5, cov: 0, perf: null },
            { diag: "rusty", mem: 0.55, cov: 0.5, perf: 0.55 },
            { diag: "rusty", mem: 0.6, cov: 0.8, perf: 0.62 },
        ],
        thermodynamics: [
            { diag: "rusty", mem: null, cov: 0, perf: null },
            { diag: "rusty", mem: 0.55, cov: 0, perf: null },
            { diag: "rusty", mem: 0.6, cov: 0.6, perf: 0.6 },
            { diag: "rusty", mem: 0.62, cov: 0.9, perf: 0.66 },
        ],
        quantum: [
            { diag: "rusty", mem: null, cov: 0, perf: null },
            { diag: "rusty", mem: null, cov: 0, perf: null },
            { diag: "rusty", mem: 0.3, cov: 0.2, perf: 0.35 },
            { diag: "rusty", mem: 0.35, cov: 0.25, perf: 0.4 },
        ],
        atomic: [
            { diag: "rusty", mem: null, cov: 0, perf: null },
            { diag: "rusty", mem: 0.5, cov: 0, perf: null },
            { diag: "rusty", mem: 0.5, cov: 0.5, perf: 0.5 },
            { diag: "rusty", mem: 0.55, cov: 0.8, perf: 0.6 },
        ],
        special_relativity: [
            { diag: "strong", mem: null, cov: 0, perf: null },
            { diag: "strong", mem: 0.72, cov: 0, perf: null },
            { diag: "strong", mem: 0.74, cov: 0.6, perf: 0.72 },
            { diag: "strong", mem: 0.78, cov: 1, perf: 0.8 },
        ],
        lab: [
            { diag: "rusty", mem: null, cov: 0, perf: null },
            { diag: "rusty", mem: null, cov: 0, perf: null },
            { diag: "rusty", mem: 0.3, cov: 0.25, perf: 0.3 },
            { diag: "rusty", mem: 0.4, cov: 0.4, perf: 0.45 },
        ],
        specialized: [
            { diag: "rusty", mem: null, cov: 0, perf: null },
            { diag: "rusty", mem: 0.45, cov: 0, perf: null },
            { diag: "rusty", mem: 0.45, cov: 0.5, perf: 0.45 },
            { diag: "rusty", mem: 0.5, cov: 0.7, perf: 0.55 },
        ],
    };

    const STAGES = [
        {
            title: "After the diagnostic",
            caption: "Placement only. No reviews or problems yet.",
        },
        {
            title: "Two weeks of cards",
            caption: "Memory rises where they have reviewed.",
        },
        {
            title: "Grinding problems",
            caption: "Attempts arrive; thin coverage opens real gaps.",
        },
        {
            title: "Exam approaching",
            caption: "Well-practiced areas reach readiness; gaps remain.",
        },
    ];

    // Derived flags shared by every scheme.
    function covered(s: State): boolean {
        return s.cov >= COVERAGE_GATE && s.perf !== null;
    }
    function ready(s: State): boolean {
        return covered(s) && (s.perf as number) >= READY_PERF;
    }

    function rgb(c: number[]): string {
        return `${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])}`;
    }
    function lerp(a: number[], b: number[], t: number): number[] {
        return a.map((v, i) => v + (b[i] - v) * Math.max(0, Math.min(1, t)));
    }

    // Region hue: the furthest pipeline stage the area has reached, its saturation
    // growing with how much we have measured, so the color climbs every session,
    // muted, then amber (memorized), then blue (practiced), then lilac (ready).
    function arcColor(s: State): string {
        if (ready(s)) {
            return rgb(lerp(NEUTRAL, LILAC, Math.min(1, s.cov)));
        }
        if (covered(s)) {
            return rgb(lerp(NEUTRAL, BLUE, Math.min(1, s.cov)));
        }
        if (s.mem !== null) {
            return rgb(lerp(NEUTRAL, AMBER, Math.min(1, s.mem)));
        }
        if (s.diag === "strong") {
            return rgb(lerp(NEUTRAL, AMBER, 0.4)); // early lean from the diagnostic
        }
        return rgb(lerp(NEUTRAL, NEUTRAL, 0.2));
    }

    type Colorer = (s: State) => string;

    // Terrain: height from the leading signal, holes for real gaps, region glow
    // from the hue mapping above.
    function buildSurface(
        stageIdx: number,
        color: Colorer,
        withLabels = false,
    ): Surface {
        const bumps: Bump[] = [];
        const dips: Bump[] = [];
        const holes: Hole[] = [];
        const glows: Glow[] = [];
        const labels: ManifoldLabel[] = [];
        for (const area of AREAS) {
            const s = JOURNEY[area.slug][stageIdx];
            const strength = s.perf ?? s.mem ?? (s.diag === "strong" ? 0.5 : 0);
            const h = 0.16 + 0.5 * strength;
            const spread = 0.22 + area.weight * 0.9;
            bumps.push({ x: area.x, y: area.y, h, s: spread });
            glows.push({ x: area.x, y: area.y, c: color(s) });

            const weakHole =
                (s.mem !== null && s.mem < WEAK_MEMORY) ||
                (s.cov > 0 && s.cov < COVERAGE_GATE);
            if (weakHole) {
                holes.push({
                    x: area.x,
                    y: area.y,
                    rx: 0.12 + area.weight * 0.4,
                    ry: 0.08 + area.weight * 0.25,
                    rot: 0,
                });
                dips.push({ x: area.x, y: area.y, h: 0.12, s: 0.26 });
            }

            if (withLabels) {
                labels.push({
                    name: area.name,
                    x: area.x,
                    y: area.y,
                    dx: area.dx,
                    dy: area.dy,
                    tf: area.tf,
                    topic: area.slug,
                });
            }
        }
        return {
            boundary: FULL_SURFACE.boundary,
            spread: FULL_SURFACE.spread,
            bumps,
            dips,
            holes,
            glows,
            labels,
        };
    }

    // The manifold rendered in the production 3D renderer, one surface per journey
    // stage, with labels so the color reads in context.
    const arcStages = STAGES.map((_, i) => buildSurface(i, arcColor, true));
    let stageIdx = STAGES.length - 1;
    let vibrance = 0.7;
    let labelLayout: "offset" | "radial" = "radial";
    let chipStrength = 0.6;
    $: arcSurface = arcStages[stageIdx];

    // The two heroes fill the row and resize with the page. A ResizeObserver keeps
    // their pixel size in step with their column so the 3D projection and its labels
    // stay correct at any width.
    let heroesEl: HTMLDivElement | undefined;
    let heroW = 470;
    let heroH = 320;
    function measureHeroes(): void {
        if (!heroesEl) {
            return;
        }
        const cs = getComputedStyle(heroesEl);
        const cols = cs.gridTemplateColumns.split(" ").filter(Boolean).length || 1;
        const gap = parseFloat(cs.columnGap || cs.gap || "0") || 0;
        const w = Math.max(
            240,
            Math.floor((heroesEl.clientWidth - gap * (cols - 1)) / cols),
        );
        heroW = w;
        heroH = Math.round(w * 0.68);
    }

    // Dev hook: drive both heroes to a set azimuth (degrees) so screenshots can
    // review the labels at fixed angles. Removed for production; lab-only aid.
    let lightHero: Manifold3D | undefined;
    let darkHero: Manifold3D | undefined;
    const HERO_DISTANCE = 4.4; // pulled back from the default so labels get a gutter
    onMount(() => {
        // Track the row width so the heroes and maps fill the page side by side.
        measureHeroes();
        const ro = new ResizeObserver(measureHeroes);
        if (heroesEl) {
            ro.observe(heroesEl);
        }
        // Pull both heroes back a touch so the ring of labels clears the figure.
        lightHero?.setDistance(HERO_DISTANCE);
        darkHero?.setDistance(HERO_DISTANCE);
        (
            window as unknown as {
                __manifoldOrbit?: (deg: number, polarDeg?: number) => void;
            }
        ).__manifoldOrbit = (deg: number, polarDeg?: number) => {
            const az = (deg * Math.PI) / 180;
            const pol = polarDeg === undefined ? undefined : (polarDeg * Math.PI) / 180;
            lightHero?.orbitTo(az, pol);
            darkHero?.orbitTo(az, pol);
            lightHero?.setDistance(HERO_DISTANCE);
            darkHero?.setDistance(HERO_DISTANCE);
        };
        (window as unknown as { __manifoldDist?: (d: number) => void }).__manifoldDist =
            (d: number) => {
                lightHero?.setDistance(d);
                darkHero?.setDistance(d);
            };
        return () => ro.disconnect();
    });
</script>

<div>
    <header class="head">
        <h1>Manifold lab</h1>
        <p>
            The readiness surface, end to end. Step the production 3D renderer through a
            learner's journey with the color and label controls, then edit the data in
            the playground below and watch the shape respond. Height and holes are
            data-driven; the region hue tracks how far each area has come. Synthetic
            data, for design.
        </p>
        <div class="legend" aria-label="Hue legend">
            <span class="key">
                <span class="sw" style="background: rgb({rgb(AMBER)})"></span>
                Memory
            </span>
            <span class="key">
                <span class="sw" style="background: rgb({rgb(BLUE)})"></span>
                Performance
            </span>
            <span class="key">
                <span class="sw" style="background: rgb({rgb(LILAC)})"></span>
                Readiness
            </span>
            <span class="key">
                <span class="sw" style="background: rgb({rgb(NEUTRAL)})"></span>
                Unlit
            </span>
            <span class="key note">
                Holes are real gaps (thin coverage or weak memory).
            </span>
        </div>
    </header>

    <section class="pick">
        <div class="pick-head">
            <h2>The manifold</h2>
            <p>
                The production Three.js renderer, light and dark side by side. Step
                through a learner's journey to watch the terrain rise and the hue travel
                from muted, through amber (memorized), to blue (practiced), to lilac
                (ready). Drag either to orbit; scroll to zoom.
            </p>
        </div>

        <div class="pick-controls">
            <div class="stage-picker" role="group" aria-label="Journey stage">
                {#each STAGES as stage, i (stage.title)}
                    <button class:on={stageIdx === i} on:click={() => (stageIdx = i)}>
                        <span class="pick-idx">{i + 1}</span>
                        {stage.title}
                    </button>
                {/each}
            </div>
            <label class="vibrance">
                <span>Vibrance</span>
                <input type="range" min="0" max="1" step="0.05" bind:value={vibrance} />
                <span class="val">{vibrance.toFixed(2)}</span>
            </label>
            <label class="vibrance">
                <span>Pill</span>
                <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    bind:value={chipStrength}
                />
                <span class="val">{chipStrength.toFixed(2)}</span>
            </label>
            <div class="seg" role="group" aria-label="Label layout">
                <button
                    class:on={labelLayout === "radial"}
                    on:click={() => (labelLayout = "radial")}
                >
                    Labels: outside
                </button>
                <button
                    class:on={labelLayout === "offset"}
                    on:click={() => (labelLayout = "offset")}
                >
                    Original
                </button>
            </div>
        </div>

        <div class="heroes" bind:this={heroesEl}>
            <div class="hero hero--light">
                <span class="hero-tag">Light</span>
                <Manifold3D
                    bind:this={lightHero}
                    width={heroW}
                    height={heroH}
                    grid={90}
                    heightScale={1.25}
                    theme="light"
                    {vibrance}
                    {labelLayout}
                    {chipStrength}
                    surface={arcSurface}
                    interactive={true}
                    showLabels={true}
                />
            </div>
            <div class="hero hero--dark">
                <span class="hero-tag">Dark</span>
                <Manifold3D
                    bind:this={darkHero}
                    width={heroW}
                    height={heroH}
                    grid={90}
                    heightScale={1.25}
                    theme="dark"
                    {vibrance}
                    {labelLayout}
                    {chipStrength}
                    surface={arcSurface}
                    interactive={true}
                    showLabels={true}
                />
            </div>
        </div>
        <p class="hero-caption">
            <span class="pick-idx">{stageIdx + 1}</span>
            {STAGES[stageIdx].title}. {STAGES[stageIdx].caption}
        </p>
    </section>

    <section class="topdown">
        <div class="pick-head">
            <h2>Top-down map</h2>
            <p>
                The exact same surface as the wireframe above, seen from straight above
                like a topographic sheet. Step the journey and both projections move
                together: contours are performance, under-glow is memory, dashed rims
                are the knowledge gaps, the outer rim is the exam blueprint. Canvas
                draws terrain only; the topic labels are real DOM, auto-placed outside
                the rim.
            </p>
        </div>

        <div class="maps">
            <div class="map-card map-card--light">
                <span class="hero-tag">Light</span>
                <ManifoldTopView
                    width={heroW}
                    height={heroH}
                    theme="light"
                    surface={arcSurface}
                    showReadouts={false}
                />
            </div>
            <div class="map-card map-card--dark">
                <span class="hero-tag">Dark</span>
                <ManifoldTopView
                    width={heroW}
                    height={heroH}
                    theme="dark"
                    surface={arcSurface}
                    showReadouts={false}
                />
            </div>
        </div>
        <p class="hero-caption">
            <span class="pick-idx">{stageIdx + 1}</span>
            {STAGES[stageIdx].title}. {STAGES[stageIdx].caption}
        </p>
    </section>

    <Playground />
</div>

<style lang="scss">
    .head {
        margin-bottom: var(--space-4);

        h1 {
            margin: 0 0 var(--space-1);
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        p {
            margin: 0 0 var(--space-2);
            max-width: 78ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
        }
    }

    .legend {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--space-1) var(--space-3);
        font-size: var(--text-small);
        color: var(--muted);
    }

    .key {
        display: inline-flex;
        align-items: center;
        gap: 6px;

        &.note {
            font-style: italic;
        }
    }

    .sw {
        width: 12px;
        height: 12px;
        border-radius: 3px;
        display: inline-block;
    }

    .pick {
        margin-bottom: var(--space-6);
    }

    .pick-head {
        margin-bottom: var(--space-2);

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
            line-height: 1.55;
            color: var(--muted);
        }
    }

    .pick-controls {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--space-2) var(--space-3);
        margin-bottom: var(--space-2);
    }

    .vibrance {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: var(--text-small);
        color: var(--muted);

        input[type="range"] {
            accent-color: var(--action-bg);
            width: 130px;
            cursor: pointer;
        }

        .val {
            font-family: var(--font-mono);
            color: var(--text);
            min-width: 34px;
            text-align: right;
        }
    }

    .seg {
        display: inline-flex;
        border: var(--hairline);
        border-radius: var(--radius-control);
        overflow: hidden;

        button {
            appearance: none;
            border: 0;
            background: var(--surface);
            color: var(--muted);
            font: inherit;
            font-size: var(--text-small);
            font-weight: 500;
            padding: 6px 12px;
            cursor: pointer;
            transition: var(--transition-calm);

            &.on {
                background: var(--action-bg);
                color: var(--action-fg);
            }

            &:not(.on):hover {
                background: var(--hover-wash);
                color: var(--text);
            }
        }
    }

    .stage-picker {
        display: inline-flex;
        flex-wrap: wrap;
        gap: 6px;

        button {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            appearance: none;
            border: var(--hairline);
            background: var(--surface);
            color: var(--muted);
            font: inherit;
            font-size: var(--text-small);
            font-weight: 500;
            padding: 6px 14px;
            border-radius: var(--radius-pill);
            cursor: pointer;
            transition: var(--transition-calm);

            &:hover {
                background: var(--hover-wash);
                color: var(--text);
            }

            &.on {
                background: var(--action-bg);
                color: var(--action-fg);
                border-color: transparent;
            }
        }
    }

    .pick-idx {
        font-family: var(--font-mono);
        font-size: var(--text-caption);
        opacity: 0.7;
    }

    .heroes {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--space-2);
    }

    @media (max-width: 620px) {
        .heroes {
            grid-template-columns: 1fr;
        }
    }

    .hero {
        position: relative;
        min-width: 0;
        border-radius: var(--radius-frame);
        box-shadow: var(--shadow-card);
        overflow: hidden;

        :global(.manifold3d) {
            overflow: hidden;
            max-width: 100%;
        }
    }

    .hero--light {
        background: #f7f6f2;
        border: var(--hairline);
    }

    .hero--dark {
        background: #14161a;
        border: 1px solid #2a2e35;
    }

    .hero-tag {
        position: absolute;
        top: 8px;
        left: 10px;
        z-index: 2;
        font-family: var(--font-mono);
        font-size: var(--text-caption);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 2px 8px;
        border-radius: var(--radius-pill);
    }

    .hero--light .hero-tag {
        background: rgba(0, 0, 0, 0.06);
        color: #4a4a46;
    }

    .hero--dark .hero-tag {
        background: rgba(255, 255, 255, 0.1);
        color: #d8d6cf;
    }

    .hero-caption {
        margin: var(--space-1) 0 0;
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: var(--text-small);
        color: var(--muted);
    }

    .topdown {
        margin-bottom: var(--space-6);
    }

    .maps {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--space-2);
        align-items: start;
    }

    @media (max-width: 620px) {
        .maps {
            grid-template-columns: 1fr;
        }
    }

    .map-card {
        position: relative;
        min-width: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 16px;
        border-radius: var(--radius-frame);
        box-shadow: var(--shadow-card);
    }

    .map-card--light {
        background: #f5f2ec;
        border: var(--hairline);
        border-color: #e8e4da;
    }

    .map-card--dark {
        background: #1b1a19;
        border: 1px solid #45433e;
    }

    .map-card--light .hero-tag {
        background: rgba(0, 0, 0, 0.06);
        color: #4a4a46;
    }

    .map-card--dark .hero-tag {
        background: rgba(255, 255, 255, 0.1);
        color: #d8d6cf;
    }
</style>
