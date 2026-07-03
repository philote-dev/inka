<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep knowledge manifold. A data-driven Canvas 2D wireframe surface with
    topic labels on leader lines. Height is Performance, holes are gaps, glow
    is Memory. Ported from the Claude Design export (design/ux-foundation.md).
    Redraws when the night-mode theme toggles.
-->
<script lang="ts">
    import { onMount } from "svelte";

    import {
        drawManifold,
        FULL_SURFACE,
        type ProjectedLabel,
        type Surface,
    } from "$lib/pgrep/manifold";

    export let width = 828;
    export let height = 540;
    export let scale = 182;
    export let glow = 0.7;
    export let grid = 64;
    export let lineWidth = 0.8;
    export let surface: Surface = FULL_SURFACE;
    export let showLabels = true;

    let canvas: HTMLCanvasElement | undefined;
    let labels: ProjectedLabel[] = [];

    function currentTheme(): "light" | "dark" {
        const dark = document.documentElement.classList.contains("night-mode")
            || document.body.classList.contains("night-mode");
        return dark ? "dark" : "light";
    }

    function render(): void {
        if (!canvas) {
            return;
        }
        labels = drawManifold(canvas, {
            W: width,
            H: height,
            S: scale,
            dpr: 2,
            glow,
            grid,
            lineWidth,
            surface,
            theme: currentTheme(),
        });
    }

    onMount(() => {
        render();
        const observer = new MutationObserver(() => render());
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["class"],
        });
        return () => observer.disconnect();
    });
</script>

<div class="manifold" style="width: {width}px; height: {height}px;">
    <canvas
        bind:this={canvas}
        width={width * 2}
        height={height * 2}
        style="width: {width}px; height: {height}px; display: block;"
    ></canvas>
    {#if showLabels}
        <svg {width} {height} class="leaders">
            {#each labels as l (l.name)}
                <g>
                    <circle cx={l.ax} cy={l.ay} r="2.5" fill="var(--muted)" />
                    <line
                        x1={l.ax}
                        y1={l.ay}
                        x2={l.lx}
                        y2={l.ly}
                        stroke="var(--muted)"
                        stroke-width="1"
                        opacity="0.7"
                    />
                </g>
            {/each}
        </svg>
        {#each labels as l (l.name)}
            <div class="label" style="left: {l.lx}px; top: {l.ly}px; transform: {l.tf}; color: {l.c};">
                {l.name}
            </div>
        {/each}
    {/if}
</div>

<style lang="scss">
    .manifold {
        position: relative;
        font-family: var(--font-ui);
    }

    .leaders {
        position: absolute;
        inset: 0;
        pointer-events: none;
    }

    .label {
        position: absolute;
        font-size: 12px;
        white-space: nowrap;
        padding: 2px 6px;
        pointer-events: none;
    }
</style>
