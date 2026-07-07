<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep knowledge manifold, the 2D top-down map. The legible projection of the
    same data-driven `Surface` the 3D wireframe reads: look straight down at your
    knowledge like a topographic sheet. Contours are performance, under-glow is
    memory, dashed rims are knowledge gaps, the outer rim is the exam blueprint.

    Terrain is drawn on the canvas (drawContour in ts/lib/pgrep/manifold.ts); every
    word is real DOM positioned from the anchors the renderer returns, so callouts
    stay crisp, keyboard-focusable, and honest (each summit carries its perf / mem;
    each gap its coverage note). Small-screen default and the fallback wherever the
    3D wireframe cannot run. Redraws when the night-mode theme toggles.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import {
        boundaryR,
        colorAt,
        DEFAULT_SURFACE,
        drawContour,
        inHole,
        type Surface,
    } from "$lib/pgrep/manifold";

    export let width = 420;
    export let height = 420;
    export let surface: Surface = DEFAULT_SURFACE;
    export let glow = 0.85;
    export let grid = 96;
    export let showCallouts = true;
    export let showLegend = true;
    // Drop the honesty readout (a summit's perf / mem, a gap's coverage note) and
    // show plain topic names only. The terrain still tells the coverage story.
    export let showReadouts = true;
    // Force a theme instead of following the document's night-mode class. The lab
    // previews light and dark side by side; undefined = follow the app.
    export let theme: "light" | "dark" | undefined = undefined;
    // When set, a summit/gap callout becomes a focus-drill launcher for its topic.
    export let onTopic: ((slug: string) => void) | undefined = undefined;

    interface Placed {
        name: string;
        kind: "peak" | "gap";
        topic?: string;
        readout: string;
        color: string;
        ax: number;
        ay: number;
        cx: number;
        cy: number;
        w: number;
        h: number;
        lx: number;
        ly: number;
    }

    let canvas: HTMLCanvasElement | undefined;
    let placed: Placed[] = [];

    // Theme-scoped ink for the marks. These are the reserved manifold colors from
    // the design handoff, not general UI tokens, so they are pinned here to keep
    // the map paper-legible in light and quiet in dark.
    interface Ink {
        leader: string;
        datum: string;
        muted: string;
        ink: string;
        inkRGB: number[];
        mix: number;
    }
    const DARK_INK: Ink = {
        leader: "#6E6B64",
        datum: "#A5A199",
        muted: "#A5A199",
        ink: "#ECEAE3",
        inkRGB: [236, 234, 227],
        mix: 0.35,
    };
    const LIGHT_INK: Ink = {
        leader: "#A5A199",
        datum: "#6E6B64",
        muted: "#6E6B64",
        ink: "#262624",
        inkRGB: [38, 38, 36],
        mix: 0.18,
    };

    function currentTheme(): "light" | "dark" {
        if (theme) {
            return theme;
        }
        const dark =
            document.documentElement.classList.contains("night-mode") ||
            document.body.classList.contains("night-mode");
        return dark ? "dark" : "light";
    }

    // Region tint for a callout: the local surface hue softened toward the ink so
    // the name reads while still belonging to its dome.
    function tintAt(x: number, y: number, t: "light" | "dark", theInk: Ink): string {
        const c = colorAt(surface, x, y, t).map((v, i) =>
            Math.round(v + (theInk.inkRGB[i] - v) * theInk.mix),
        );
        return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
    }

    // Auto-placement: push each callout radially outward from the blob center to
    // just past the rim, then relax overlaps in 2D while a weak spring holds each
    // near its region. Static per size/surface/theme, so no per-frame jitter.
    function layout(
        W: number,
        H: number,
        S: number,
        t: "light" | "dark",
        theInk: Ink,
    ): Placed[] {
        if (!canvas) {
            return [];
        }
        const ctx = canvas.getContext("2d");
        if (!ctx) {
            return [];
        }
        const cx0 = W / 2;
        const cy0 = H / 2;
        const clearance = Math.max(16, S * 0.13);

        interface Node {
            item: Placed;
            tx: number;
            ty: number;
        }
        const nodes: Node[] = surface.labels.map((l, i) => {
            const ax = cx0 + l.x * S;
            const ay = cy0 + l.y * S;
            const gap = l.note !== undefined || inHole(surface, l.x, l.y);
            let readout = "";
            if (showReadouts && gap) {
                readout = l.note ?? "gap";
            } else if (showReadouts) {
                const parts: string[] = [];
                if (l.perf !== undefined) {
                    parts.push(`perf ${l.perf}`);
                }
                if (l.mem !== undefined) {
                    parts.push(`mem ${l.mem}`);
                }
                readout = parts.join(" · ");
            }
            ctx.font = "500 13px Inter, sans-serif";
            const nameW = ctx.measureText(l.name).width;
            ctx.font = '10px "JetBrains Mono", monospace';
            const readW = readout ? ctx.measureText(readout).width : 0;
            const w = Math.max(nameW, readW) + 14;
            const h = readout ? 34 : 22;

            let dx = ax - cx0;
            let dy = ay - cy0;
            let r = Math.hypot(dx, dy);
            if (r < 1e-3) {
                // A near-centered feature has no natural direction; fan it out by index.
                const a = (i / Math.max(1, surface.labels.length)) * Math.PI * 2;
                dx = Math.cos(a);
                dy = Math.sin(a);
                r = 1;
            }
            const dirX = dx / r;
            const dirY = dy / r;
            const th = Math.atan2(dy, dx);
            const rim = boundaryR(surface, th) * S;
            const dist = rim + clearance + h / 2;
            const cx = cx0 + dirX * dist;
            const cy = cy0 + dirY * dist;
            const item: Placed = {
                name: l.name,
                kind: gap ? "gap" : "peak",
                topic: l.topic,
                readout,
                color: gap ? theInk.ink : tintAt(l.x, l.y, t, theInk),
                ax,
                ay,
                cx,
                cy,
                w,
                h,
                lx: cx,
                ly: cy,
            };
            return { item, tx: cx, ty: cy };
        });

        const padX = 9;
        const padY = 7;
        for (let iter = 0; iter < 120; iter++) {
            for (let i = 0; i < nodes.length; i++) {
                for (let j = i + 1; j < nodes.length; j++) {
                    const a = nodes[i].item;
                    const b = nodes[j].item;
                    const dx = b.cx - a.cx;
                    const dy = b.cy - a.cy;
                    const ox = (a.w + b.w) / 2 + padX - Math.abs(dx);
                    const oy = (a.h + b.h) / 2 + padY - Math.abs(dy);
                    if (ox > 0 && oy > 0) {
                        // Separate along the axis of least penetration, least motion.
                        if (ox < oy) {
                            const s = (ox / 2) * (dx < 0 ? -1 : 1);
                            a.cx -= s;
                            b.cx += s;
                        } else {
                            const s = (oy / 2) * (dy < 0 ? -1 : 1);
                            a.cy -= s;
                            b.cy += s;
                        }
                    }
                }
            }
            for (const nd of nodes) {
                const it = nd.item;
                it.cx += (nd.tx - it.cx) * 0.03;
                it.cy += (nd.ty - it.cy) * 0.03;
                // Keep the box off the silhouette: never let a label drift over terrain.
                const th = Math.atan2(it.cy - cy0, it.cx - cx0);
                const minR = boundaryR(surface, th) * S + clearance + it.h * 0.35;
                const r = Math.hypot(it.cx - cx0, it.cy - cy0);
                if (r < minR && r > 1e-3) {
                    it.cx = cx0 + ((it.cx - cx0) / r) * minR;
                    it.cy = cy0 + ((it.cy - cy0) / r) * minR;
                }
            }
        }

        // Clamp inside the frame and derive the leader touch-point on each box edge.
        for (const nd of nodes) {
            const it = nd.item;
            it.cx = Math.min(Math.max(it.cx, it.w / 2 + 3), W - it.w / 2 - 3);
            it.cy = Math.min(Math.max(it.cy, it.h / 2 + 3), H - it.h / 2 - 3);
            it.lx = it.cx;
            it.ly = it.cy;
        }
        return nodes.map((n) => n.item);
    }

    // Fit the surface to the frame: shrink the projection so the whole silhouette
    // sits inside, with a gutter left around the rim for the callouts. Works for
    // both the compact embed and the wide nine-unit syllabus.
    function fitScale(W: number, H: number): number {
        let maxX = 1e-3;
        let maxY = 1e-3;
        for (let k = 0; k < 240; k++) {
            const th = (k / 240) * Math.PI * 2;
            const R = boundaryR(surface, th);
            maxX = Math.max(maxX, Math.abs(R * Math.cos(th)));
            maxY = Math.max(maxY, Math.abs(R * Math.sin(th)));
        }
        const gx = W * 0.23;
        const gy = H * 0.18;
        return Math.max(20, Math.min((W / 2 - gx) / maxX, (H / 2 - gy) / maxY));
    }

    // Where the leader meets the label: the box border on the ray to the anchor.
    function leaderEnd(p: Placed): { x: number; y: number } {
        const ex = p.ax - p.cx;
        const ey = p.ay - p.cy;
        if (Math.abs(ex) < 1e-3 && Math.abs(ey) < 1e-3) {
            return { x: p.cx, y: p.cy };
        }
        const tX = ex === 0 ? Infinity : p.w / 2 / Math.abs(ex);
        const tY = ey === 0 ? Infinity : p.h / 2 / Math.abs(ey);
        const t = Math.min(tX, tY);
        return { x: p.cx + ex * t, y: p.cy + ey * t };
    }

    function render(): void {
        if (!canvas) {
            return;
        }
        // Set the backing store here, not via reactive attributes: a reactive
        // width/height binding is re-applied after our redraw in the same Svelte
        // flush, which clears the freshly drawn canvas. Sizing it right before the
        // draw keeps the two in the same synchronous step.
        const bw = Math.round(width * 2);
        const bh = Math.round(height * 2);
        if (canvas.width !== bw) {
            canvas.width = bw;
        }
        if (canvas.height !== bh) {
            canvas.height = bh;
        }
        const t = currentTheme();
        const out = drawContour(canvas, {
            W: width,
            H: height,
            S: fitScale(width, height),
            dpr: 2,
            glow,
            grid,
            indexEvery: 3,
            theme: t,
            surface,
        });
        placed = showCallouts
            ? layout(out.W, out.H, out.S, t, t === "light" ? LIGHT_INK : DARK_INK)
            : [];
    }

    $: ink = (theme ?? "dark") === "light" ? LIGHT_INK : DARK_INK;

    onMount(() => {
        render();
        if (theme) {
            return;
        }
        const observer = new MutationObserver(() => render());
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["class"],
        });
        return () => observer.disconnect();
    });

    // Redraw on any drawing input. Resizing the canvas element clears it, so the
    // terrain and the label solve must both re-run, not just re-read attributes.
    $: redraw(width, height, surface, glow, grid, theme, showCallouts);
    function redraw(..._inputs: unknown[]): void {
        if (canvas) {
            render();
        }
    }

    function launch(topic: string | undefined): void {
        if (onTopic && topic) {
            onTopic(topic);
        }
    }

    // The accessible structure behind the decorative canvas: a plain readout of
    // every topic, its scores, and its coverage state.
    function cell(gap: boolean, v: number | undefined): string {
        if (gap || v === undefined) {
            return "-";
        }
        return String(v);
    }
    $: rows = surface.labels.map((l) => {
        const gap = l.note !== undefined || inHole(surface, l.x, l.y);
        return {
            name: l.name,
            perf: cell(gap, l.perf),
            mem: cell(gap, l.mem),
            coverage: gap ? (l.note ?? "gap") : "covered",
        };
    });
</script>

<div
    class="topview"
    class:is-light={ink === LIGHT_INK}
    style="width: {width}px;"
    style:--leader={ink.leader}
    style:--datum={ink.datum}
    style:--muted={ink.muted}
    style:--ink={ink.ink}
>
    <div class="map" style="width: {width}px; height: {height}px;">
        <canvas
            bind:this={canvas}
            style="width: {width}px; height: {height}px; display: block;"
            aria-hidden="true"
        ></canvas>

        {#if showCallouts}
            <svg {width} {height} class="overlay" aria-hidden="true">
                {#each placed as p (p.name)}
                    {@const end = leaderEnd(p)}
                    {#if p.kind === "peak"}
                        <line
                            x1={p.ax}
                            y1={p.ay}
                            x2={end.x}
                            y2={end.y}
                            stroke="var(--leader)"
                            stroke-width="1"
                        />
                        <circle
                            cx={p.ax}
                            cy={p.ay}
                            r="7"
                            fill="none"
                            stroke={p.color}
                            stroke-width="1"
                            opacity="0.5"
                        />
                        <circle cx={p.ax} cy={p.ay} r="2.5" fill={p.color} />
                    {:else}
                        <line
                            x1={p.ax}
                            y1={p.ay}
                            x2={end.x}
                            y2={end.y}
                            stroke="var(--leader)"
                            stroke-width="1"
                            stroke-dasharray="3 3"
                        />
                        <circle
                            cx={p.ax}
                            cy={p.ay}
                            r="3"
                            fill="none"
                            stroke="var(--datum)"
                            stroke-width="1"
                        />
                    {/if}
                {/each}
            </svg>

            {#each placed as p (p.name)}
                {#if onTopic && p.topic}
                    <button
                        type="button"
                        class="callout is-btn"
                        style="left: {p.lx}px; top: {p.ly}px;"
                        on:click={() => launch(p.topic)}
                    >
                        <span class="callout-name" style="color: {p.color};">
                            {p.name}
                        </span>
                        {#if p.readout}
                            <span class="callout-readout">{p.readout}</span>
                        {/if}
                    </button>
                {:else}
                    <div class="callout" style="left: {p.lx}px; top: {p.ly}px;">
                        <span class="callout-name" style="color: {p.color};">
                            {p.name}
                        </span>
                        {#if p.readout}
                            <span class="callout-readout">{p.readout}</span>
                        {/if}
                    </div>
                {/if}
            {/each}
        {/if}
    </div>

    {#if showLegend}
        <div class="legend">
            <span class="legend-item">
                <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true">
                    <path
                        d="M1 9.5 C6 7.5 16 7.5 21 9.5"
                        fill="none"
                        stroke="var(--muted)"
                        stroke-width="1"
                    />
                    <path
                        d="M1 4.5 C6 2 16 2 21 4.5"
                        fill="none"
                        stroke="var(--muted)"
                        stroke-width="1.6"
                    />
                </svg>
                contour = performance, every 3rd indexed
            </span>
            <span class="legend-item">
                <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true">
                    <ellipse
                        cx="11"
                        cy="6"
                        rx="9"
                        ry="4.5"
                        fill="none"
                        stroke="var(--muted)"
                        stroke-width="1"
                        stroke-dasharray="3 3"
                    />
                </svg>
                dashed rim = knowledge gap
            </span>
            <span class="legend-item">
                <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true">
                    <circle
                        cx="11"
                        cy="6"
                        r="5.5"
                        fill="rgb(235,203,139)"
                        opacity="0.22"
                    />
                    <circle
                        cx="11"
                        cy="6"
                        r="2.5"
                        fill="rgb(235,203,139)"
                        opacity="0.4"
                    />
                </svg>
                under-glow = memory
            </span>
            <span class="legend-item">
                <svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true">
                    <circle
                        cx="11"
                        cy="6"
                        r="5"
                        fill="none"
                        stroke="var(--muted)"
                        stroke-width="1"
                        opacity="0.8"
                    />
                </svg>
                outer rim = blueprint weight
            </span>
        </div>
    {/if}

    <table class="sr-only">
        <caption>
            Knowledge manifold, top-down. Performance, memory and coverage per topic.
        </caption>
        <thead>
            <tr>
                <th>Topic</th>
                <th>Performance</th>
                <th>Memory</th>
                <th>Coverage</th>
            </tr>
        </thead>
        <tbody>
            {#each rows as r (r.name)}
                <tr>
                    <td>{r.name}</td>
                    <td>{r.perf}</td>
                    <td>{r.mem}</td>
                    <td>{r.coverage}</td>
                </tr>
            {/each}
        </tbody>
    </table>
</div>

<style lang="scss">
    .topview {
        font-family: var(--font-ui, "Inter", sans-serif);
    }

    .map {
        position: relative;
        max-width: 100%;
    }

    .overlay {
        position: absolute;
        inset: 0;
        pointer-events: none;
    }

    .callout {
        position: absolute;
        transform: translate(-50%, -50%);
        display: flex;
        flex-direction: column;
        gap: 2px;
        align-items: flex-start;
        white-space: nowrap;
        padding: 1px 5px;
        text-align: left;
    }

    .callout-name {
        font-size: 13px;
        font-weight: 500;
        line-height: 1.15;
    }

    .callout-readout {
        font-family: var(--font-mono, "JetBrains Mono", monospace);
        font-size: 10px;
        line-height: 1.1;
        color: var(--muted);
    }

    .is-btn {
        appearance: none;
        border: 0;
        background: none;
        cursor: pointer;
        pointer-events: auto;
        border-radius: var(--radius-control, 8px);
        transition: var(--transition-calm, all 0.15s ease);

        &:hover .callout-name {
            text-decoration: underline;
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring, #5b8def);
            outline-offset: 2px;
        }
    }

    .legend {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 8px 22px;
        margin-top: 12px;
    }

    .legend-item {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        font-family: var(--font-mono, "JetBrains Mono", monospace);
        font-size: 10px;
        color: var(--muted);
    }

    .sr-only {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
    }
</style>
