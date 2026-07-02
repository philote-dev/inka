<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep knowledge manifold, the 3D wireframe. Wraps the Three.js renderer in
    ts/lib/pgrep/manifold3d.ts, which consumes the same data-driven `Surface` as
    the Canvas 2D component. Drag to orbit, scroll to zoom. Topic labels ride an
    HTML overlay that tracks the surface as the camera moves. Redraws when the
    night-mode theme toggles and rebuilds when the surface changes.
-->
<script lang="ts">
    import { onDestroy, onMount } from "svelte";

    import { FULL_SURFACE, type Surface } from "$lib/pgrep/manifold";
    import { createManifold3D, type Manifold3DHandle, type ProjectedLabel3D } from "$lib/pgrep/manifold3d";

    export let width = 720;
    export let height = 460;
    export let surface: Surface = FULL_SURFACE;
    export let grid = 64;
    export let heightScale = 1.15;
    export let glow = 0.7;
    export let autoRotate = false;
    export let interactive = true;
    export let showLabels = true;

    let stage: HTMLDivElement | undefined;
    let handle: Manifold3DHandle | undefined;
    let observer: MutationObserver | undefined;
    let labels: ProjectedLabel3D[] = [];

    function currentTheme(): "light" | "dark" {
        const dark = document.documentElement.classList.contains("night-mode")
            || document.body.classList.contains("night-mode");
        return dark ? "dark" : "light";
    }

    onMount(() => {
        if (!stage) {
            return;
        }
        handle = createManifold3D(stage, {
            surface,
            theme: currentTheme(),
            grid,
            heightScale,
            glow,
            autoRotate,
            interactive,
            width,
            height,
            onLabels: (next) => {
                labels = next;
            },
        });
        observer = new MutationObserver(() => handle?.update(surface, currentTheme()));
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    });

    onDestroy(() => {
        observer?.disconnect();
        handle?.dispose();
    });

    export function resetView(): void {
        handle?.resetView();
    }

    // React to prop changes after mount.
    $: if (handle) {
        handle.update(surface, currentTheme());
    }
    $: handle?.setShape({ grid, heightScale, glow });
    $: handle?.setAutoRotate(autoRotate);
    $: handle?.resize(width, height);
</script>

<div class="manifold3d" style="width: {width}px; height: {height}px;">
    <div class="stage" bind:this={stage}></div>
    {#if showLabels}
        <svg {width} {height} class="leaders">
            {#each labels as l (l.name)}
                {#if l.visible}
                    <g>
                        <circle cx={l.ax} cy={l.ay} r="2.5" fill="var(--muted)" />
                        <line x1={l.ax} y1={l.ay} x2={l.lx} y2={l.ly} stroke="var(--muted)" stroke-width="1" opacity="0.7" />
                    </g>
                {/if}
            {/each}
        </svg>
        {#each labels as l (l.name)}
            {#if l.visible}
                <div class="label" style="left: {l.lx}px; top: {l.ly}px; transform: {l.tf}; color: {l.c};">
                    {l.name}
                </div>
            {/if}
        {/each}
    {/if}
</div>

<style lang="scss">
    .manifold3d {
        position: relative;
        touch-action: none;
        font-family: var(--font-ui);
    }

    .stage {
        position: absolute;
        inset: 0;
        cursor: grab;

        &:active {
            cursor: grabbing;
        }
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
