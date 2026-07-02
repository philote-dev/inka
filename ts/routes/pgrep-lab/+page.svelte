<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep manifold lab. A durable dev surface that proves the manifold is
     data driven. Each tile starts from the same baseline and changes exactly
     one input, so you can see height follow performance, hue follow the
     leading score, and holes follow coverage. -->
<script lang="ts">
    import Manifold from "$lib/components/Manifold.svelte";
    import { buildSurface, type TopicStat } from "$lib/pgrep/manifold";

    type Lead = "memory" | "performance" | "readiness";

    // The nine PGRE units, fixed layout positions and blueprint weights.
    const layout = [
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

    function stats(fn: (name: string) => { performance: number; coverage: number; lead: Lead }): TopicStat[] {
        return layout.map((u) => ({ ...u, ...fn(u.name) }));
    }

    const baseline = stats(() => ({ performance: 0.5, coverage: 1, lead: "performance" }));
    const taller = stats((n) => ({ performance: n === "Quantum Mechanics" ? 0.96 : 0.5, coverage: 1, lead: "performance" }));
    const gap = stats((n) => ({ performance: 0.5, coverage: n === "Quantum Mechanics" ? 0.1 : 1, lead: "performance" }));
    const memoryLed = stats(() => ({ performance: 0.5, coverage: 1, lead: "memory" }));

    const tiles = [
        {
            title: "Baseline",
            surface: buildSurface(baseline),
            caption: "Moderate performance everywhere, full coverage, performance led. The reference for the three below.",
        },
        {
            title: "Performance drives height",
            surface: buildSurface(taller),
            caption: "Only Quantum's performance rose to 0.96. Its peak (lower center) grows. Nothing else changed.",
        },
        {
            title: "Coverage drives gaps",
            surface: buildSurface(gap),
            caption: "Only Quantum's coverage fell below the line. A hole opens exactly there. A gap is real, not decorative.",
        },
        {
            title: "Leading score drives hue",
            surface: buildSurface(memoryLed),
            caption: "Same shape, every unit now led by Memory. The surface warms to amber. Color is the reserved score language.",
        },
    ];
</script>

<div class="lab">
    <header class="head">
        <h1>Manifold lab</h1>
        <p>
            One surface object drives everything. Height is Performance, hue is the leading score,
            holes are coverage gaps, footprint is blueprint weight. Each tile changes one input.
        </p>
    </header>

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
</div>

<style lang="scss">
    .lab {
        max-width: 1000px;
        margin: 0 auto;
        padding: var(--space-5) var(--space-3) var(--space-6);
        background: var(--canvas);
        color: var(--text);
        min-height: 100vh;
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
            max-width: 68ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
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
</style>
