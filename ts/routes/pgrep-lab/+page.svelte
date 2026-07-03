<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep manifold lab. A durable dev surface that proves the manifold is data
     driven and lets us refine the look. The playground edits the nine PGRE
     units live and reshapes one surface in either the 3D wireframe or the 2D
     contour fallback. The tiles below isolate one input each. -->
<script lang="ts">
    import Manifold from "$lib/components/Manifold.svelte";
    import Manifold3D from "$lib/components/Manifold3D.svelte";
    import { buildSurface, type TopicStat } from "$lib/pgrep/manifold";

    type Lead = "memory" | "performance" | "readiness";

    const LEADS: { id: Lead; short: string; label: string }[] = [
        { id: "memory", short: "M", label: "Memory" },
        { id: "performance", short: "P", label: "Performance" },
        { id: "readiness", short: "R", label: "Readiness" },
    ];

    // Fixed layout of the nine units: screen position, blueprint weight, and the
    // label offset the renderer uses for leader lines.
    const LAYOUT = [
        { name: "Classical Mechanics", x: -0.6, y: -0.5, weight: 0.2, dx: -60, dy: -44, tf: "translate(-100%, -100%)" },
        { name: "Electromagnetism", x: 0.56, y: -0.48, weight: 0.18, dx: 30, dy: -60, tf: "translate(0, -100%)" },
        { name: "Optics & Waves", x: 1.0, y: -0.14, weight: 0.08, dx: 54, dy: -22, tf: "translate(0, -100%)" },
        { name: "Thermo & Stat Mech", x: -1.05, y: 0.14, weight: 0.1, dx: -54, dy: 26, tf: "translate(-100%, 0)" },
        { name: "Quantum Mechanics", x: 0.16, y: 0.6, weight: 0.13, dx: -60, dy: 40, tf: "translate(-100%, 0)" },
        { name: "Atomic Physics", x: 0.72, y: 0.4, weight: 0.1, dx: 64, dy: 46, tf: "translate(0, 0)" },
        { name: "Special Relativity", x: -0.56, y: 0.62, weight: 0.06, dx: -50, dy: 62, tf: "translate(-100%, 0)" },
        { name: "Laboratory Methods", x: -0.05, y: -0.62, weight: 0.06, dx: 10, dy: -60, tf: "translate(-50%, -100%)" },
        { name: "Specialized Topics", x: 0.16, y: 0.04, weight: 0.09, dx: 30, dy: 60, tf: "translate(0, 0)" },
    ];

    // Seeded so the default view already tells the data story: varied peaks, two
    // real gaps (Quantum, Lab), a mix of leading scores.
    const DEFAULTS: Record<string, { performance: number; coverage: number; lead: Lead }> = {
        "Classical Mechanics": { performance: 0.82, coverage: 1, lead: "performance" },
        "Electromagnetism": { performance: 0.68, coverage: 1, lead: "performance" },
        "Optics & Waves": { performance: 0.55, coverage: 1, lead: "memory" },
        "Thermo & Stat Mech": { performance: 0.6, coverage: 1, lead: "readiness" },
        "Quantum Mechanics": { performance: 0.35, coverage: 0.2, lead: "memory" },
        "Atomic Physics": { performance: 0.5, coverage: 1, lead: "memory" },
        "Special Relativity": { performance: 0.72, coverage: 1, lead: "readiness" },
        "Laboratory Methods": { performance: 0.3, coverage: 0.25, lead: "performance" },
        "Specialized Topics": { performance: 0.45, coverage: 1, lead: "readiness" },
    };

    function seededUnits(): TopicStat[] {
        return LAYOUT.map((u) => ({ ...u, ...DEFAULTS[u.name] }));
    }

    let units: TopicStat[] = seededUnits();

    let view: "3d" | "2d" = "3d";
    let autoRotate = false;
    let grid = 60;
    let heightScale = 1.2;
    let manifold3d: Manifold3D | undefined;

    const VIEW_W = 720;
    const VIEW_H = 460;

    $: surface = buildSurface(units);
    $: gapCount = units.filter((u) => u.coverage < 0.4).length;

    function bump(): void {
        units = units;
    }

    function setLead(i: number, lead: Lead): void {
        units[i].lead = lead;
        bump();
    }

    function resetUnits(): void {
        units = seededUnits();
    }

    // The four isolation tiles, each changing exactly one input from a flat base.
    function stat(fn: (name: string) => { performance: number; coverage: number; lead: Lead }): TopicStat[] {
        return LAYOUT.map((u) => ({ ...u, ...fn(u.name) }));
    }
    const tiles = [
        {
            title: "Baseline",
            surface: buildSurface(stat(() => ({ performance: 0.5, coverage: 1, lead: "performance" }))),
            caption: "Moderate performance everywhere, full coverage, performance led. The reference for the three below.",
        },
        {
            title: "Performance drives height",
            surface: buildSurface(stat((n) => ({ performance: n === "Quantum Mechanics" ? 0.96 : 0.5, coverage: 1, lead: "performance" }))),
            caption: "Only Quantum's performance rose to 0.96. Its peak grows. Nothing else changed.",
        },
        {
            title: "Coverage drives gaps",
            surface: buildSurface(stat((n) => ({ performance: 0.5, coverage: n === "Quantum Mechanics" ? 0.1 : 1, lead: "performance" }))),
            caption: "Only Quantum's coverage fell below the line. A hole opens exactly there. A gap is real, not decorative.",
        },
        {
            title: "Leading score drives hue",
            surface: buildSurface(stat(() => ({ performance: 0.5, coverage: 1, lead: "memory" }))),
            caption: "Same shape, every unit now led by Memory. The surface warms to amber. Color is the reserved score language.",
        },
    ];
</script>

<div class="lab">
    <nav class="lab-nav">
        <a class="lab-nav__link is-active" href="/pgrep-lab" aria-current="page">Manifold lab</a>
        <a class="lab-nav__link" href="/pgrep-lab/gallery">Component gallery</a>
    </nav>

    <header class="head">
        <h1>Manifold lab</h1>
        <p>
            One surface object drives everything. Height is Performance, hue is the leading score, holes are
            coverage gaps, footprint is blueprint weight. Edit the units and watch the same instrument reshape
            in 3D or its 2D fallback.
        </p>
    </header>

    <section class="playground">
        <div class="stage">
            <div class="toolbar">
                <div class="seg" role="group" aria-label="View mode">
                    <button class:on={view === "3d"} on:click={() => (view = "3d")}>3D</button>
                    <button class:on={view === "2d"} on:click={() => (view = "2d")}>2D</button>
                </div>
                {#if view === "3d"}
                    <label class="check">
                        <input type="checkbox" bind:checked={autoRotate} />
                        Auto-rotate
                    </label>
                    <button class="ghost" on:click={() => manifold3d?.resetView()}>Reset view</button>
                {/if}
                <span class="spacer"></span>
                <span class="meta">{gapCount} {gapCount === 1 ? "gap" : "gaps"}</span>
            </div>

            <div class="viewport" style="width: {VIEW_W}px; height: {VIEW_H}px;">
                {#if view === "3d"}
                    <Manifold3D
                        bind:this={manifold3d}
                        width={VIEW_W}
                        height={VIEW_H}
                        {surface}
                        {grid}
                        {heightScale}
                        {autoRotate}
                    />
                {:else}
                    <Manifold width={VIEW_W} height={VIEW_H} scale={150} grid={64} {surface} showLabels />
                {/if}
            </div>

            {#if view === "3d"}
                <div class="stage-controls">
                    <label class="slider">
                        <span>Grid</span>
                        <input type="range" min="24" max="96" step="4" bind:value={grid} />
                        <span class="val">{grid}</span>
                    </label>
                    <label class="slider">
                        <span>Height</span>
                        <input type="range" min="0.6" max="2" step="0.05" bind:value={heightScale} />
                        <span class="val">{heightScale.toFixed(2)}</span>
                    </label>
                    <span class="hint">Drag to orbit. Scroll to zoom.</span>
                </div>
            {:else}
                <div class="stage-controls">
                    <span class="hint">Canvas 2D wireframe. The same surface, no WebGL.</span>
                </div>
            {/if}
        </div>

        <aside class="panel">
            <div class="panel-head">
                <span>Units</span>
                <button class="ghost" on:click={resetUnits}>Reset</button>
            </div>
            <div class="units">
                {#each units as u, i (u.name)}
                    <div class="unit">
                        <div class="unit-name">{u.name}</div>
                        <div class="unit-ctrls">
                            <label class="slider small">
                                <span>Perf</span>
                                <input type="range" min="0" max="1" step="0.01" bind:value={u.performance} on:input={bump} />
                                <span class="val">{u.performance.toFixed(2)}</span>
                            </label>
                            <label class="slider small">
                                <span>Cov</span>
                                <input type="range" min="0" max="1" step="0.01" bind:value={u.coverage} on:input={bump} />
                                <span class="val" class:below={u.coverage < 0.4}>{u.coverage.toFixed(2)}</span>
                            </label>
                            <div class="leads" role="group" aria-label="Leading score">
                                {#each LEADS as l (l.id)}
                                    <button
                                        class:active={u.lead === l.id}
                                        title={l.label}
                                        on:click={() => setLead(i, l.id)}
                                    >
                                        <span class="dot" style="background: var(--{l.id});"></span>{l.short}
                                    </button>
                                {/each}
                            </div>
                        </div>
                    </div>
                {/each}
            </div>
        </aside>
    </section>

    <section class="proof">
        <h2>What each input does</h2>
        <div class="grid">
            {#each tiles as tile (tile.title)}
                <section class="tile">
                    <div class="tile-head">{tile.title}</div>
                    <div class="viz">
                        <Manifold width={440} height={230} scale={96} grid={70} surface={tile.surface} showLabels={false} />
                    </div>
                    <p class="caption">{tile.caption}</p>
                </section>
            {/each}
        </div>
    </section>
</div>

<style lang="scss">
    .lab {
        max-width: 1180px;
        margin: 0 auto;
        padding: var(--space-5) var(--space-3) var(--space-6);
        background: var(--canvas);
        color: var(--text);
        min-height: 100vh;
    }

    .lab-nav {
        display: inline-flex;
        gap: 4px;
        padding: 4px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        background: var(--surface);
        margin-bottom: var(--space-3);
    }

    .lab-nav__link {
        padding: 6px 16px;
        border-radius: var(--radius-pill);
        font-size: var(--text-small);
        font-weight: 500;
        color: var(--muted);
        text-decoration: none;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
        }

        &.is-active {
            color: var(--action-fg);
            background: var(--action-bg);
        }
    }

    .head {
        margin-bottom: var(--space-4);

        h1 {
            margin: 0 0 var(--space-1);
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

    .playground {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 340px;
        gap: var(--space-2);
        align-items: start;
        margin-bottom: var(--space-5);
    }

    .stage {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        min-width: 0;
    }

    .toolbar {
        display: flex;
        align-items: center;
        gap: var(--space-1);
    }

    .spacer {
        flex: 1;
    }

    .meta {
        font-family: var(--font-mono);
        font-size: var(--text-small);
        color: var(--muted);
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
            padding: 6px 14px;
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

    .check {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: var(--text-small);
        color: var(--muted);
        cursor: pointer;
        user-select: none;
    }

    .ghost {
        appearance: none;
        border: var(--hairline);
        background: var(--surface);
        color: var(--text);
        font: inherit;
        font-size: var(--text-small);
        padding: 6px 12px;
        border-radius: var(--radius-control);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            background: var(--hover-wash);
            border-color: var(--muted);
        }
    }

    .viewport {
        border: var(--hairline);
        border-radius: var(--radius-frame);
        background: var(--surface);
        box-shadow: var(--shadow-card);
        overflow: hidden;
        max-width: 100%;
    }

    .stage-controls {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
        padding: 2px var(--space-0);
    }

    .hint {
        font-size: var(--text-small);
        color: var(--muted);
    }

    .slider {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: var(--text-small);
        color: var(--muted);

        span:first-child {
            min-width: 44px;
        }

        input[type="range"] {
            accent-color: var(--action-bg);
            width: 128px;
            cursor: pointer;
        }

        .val {
            font-family: var(--font-mono);
            color: var(--text);
            min-width: 34px;
            text-align: right;

            &.below {
                color: var(--caution);
            }
        }

        &.small {
            span:first-child {
                min-width: 30px;
            }

            input[type="range"] {
                width: 92px;
            }

            .val {
                min-width: 30px;
            }
        }
    }

    .panel {
        border: var(--hairline);
        border-radius: var(--radius-card);
        background: var(--surface);
        box-shadow: var(--shadow-card);
        overflow: hidden;
    }

    .panel-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--space-1) var(--space-2);
        border-bottom: var(--hairline);
        font-size: var(--text-small);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--muted);
    }

    .units {
        max-height: 520px;
        overflow-y: auto;
    }

    .unit {
        padding: var(--space-1) var(--space-2);
        border-bottom: var(--hairline);

        &:last-child {
            border-bottom: 0;
        }
    }

    .unit-name {
        font-size: var(--text-small);
        font-weight: 500;
        margin-bottom: 4px;
    }

    .unit-ctrls {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .leads {
        display: inline-flex;
        gap: 6px;
        margin-top: 2px;

        button {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            appearance: none;
            border: var(--hairline);
            background: var(--surface);
            color: var(--muted);
            font: inherit;
            font-size: var(--text-caption);
            font-weight: 500;
            padding: 3px 8px;
            border-radius: var(--radius-pill);
            cursor: pointer;
            transition: var(--transition-calm);

            &:hover {
                background: var(--hover-wash);
            }

            &.active {
                border-color: var(--muted);
                color: var(--text);
                background: var(--hover-wash);
            }
        }

        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }
    }

    .proof {
        h2 {
            margin: 0 0 var(--space-2);
            font-size: var(--text-emphasis);
            font-weight: 600;
        }
    }

    .grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: var(--space-2);
    }

    .tile {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        padding: var(--space-2);
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .tile-head {
        font-size: var(--text-emphasis);
        font-weight: 600;
        letter-spacing: -0.01em;
    }

    .viz {
        display: flex;
        justify-content: center;
        overflow: hidden;
    }

    .caption {
        margin: 0;
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    @media (max-width: 900px) {
        .playground {
            grid-template-columns: minmax(0, 1fr);
        }

        .grid {
            grid-template-columns: 1fr;
        }
    }
</style>
