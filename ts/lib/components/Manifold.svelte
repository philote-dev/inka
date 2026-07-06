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
    // When set, topic labels become focus-drill launchers (ux-foundation 5).
    export let onTopic: ((slug: string) => void) | undefined = undefined;

    let canvas: HTMLCanvasElement | undefined;
    let labels: ProjectedLabel[] = [];

    function launch(topic: string | undefined): void {
        if (onTopic && topic) {
            onTopic(topic);
        }
    }

    function currentTheme(): "light" | "dark" {
        const dark =
            document.documentElement.classList.contains("night-mode") ||
            document.body.classList.contains("night-mode");
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

    // Redraw when a drawing input changes, so the wireframe stays crisp when its
    // container resizes (the responsive hero) or the surface updates. Resizing the
    // canvas element clears it, so a redraw is required, not just new attributes.
    $: redraw(width, height, scale, glow, grid, lineWidth, surface);

    function redraw(..._inputs: unknown[]): void {
        if (canvas) {
            render();
        }
    }
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
            {#if onTopic && l.topic}
                <button
                    type="button"
                    class="label label-btn"
                    style="left: {l.lx}px; top: {l.ly}px; transform: {l.tf}; color: {l.c};"
                    on:click={() => launch(l.topic)}
                >
                    {l.name}
                </button>
            {:else}
                <div
                    class="label"
                    style="left: {l.lx}px; top: {l.ly}px; transform: {l.tf}; color: {l.c};"
                >
                    {l.name}
                </div>
            {/if}
        {/each}
    {/if}
</div>

<style lang="scss">
    .manifold {
        position: relative;
        max-width: 100%;
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

    /* Topic labels wired to a focus drill become quiet buttons: same look as a
       label, a calm hover underline, and a keyboard focus ring. */
    .label-btn {
        pointer-events: auto;
        border: 0;
        background: none;
        font-family: var(--font-ui);
        cursor: pointer;
        border-radius: var(--radius-control, 8px);
        transition: var(--transition-calm);

        &:hover {
            text-decoration: underline;
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
        }
    }
</style>
