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

    Fallback. WebGL is not guaranteed (older webviews, disabled GPUs, lost
    contexts). When it is unavailable, or the renderer fails to start, this
    component degrades to the Canvas 2D `Manifold`, which draws the same
    `Surface`. So the manifold always renders and never hard-depends on WebGL.
-->
<script lang="ts">
    import { onDestroy, onMount } from "svelte";

    import Manifold from "$lib/components/Manifold.svelte";
    import { FULL_SURFACE, type Surface } from "$lib/pgrep/manifold";
    import {
        createManifold3D,
        type Manifold3DHandle,
        type ProjectedLabel3D,
        supportsWebGL,
    } from "$lib/pgrep/manifold3d";

    export let width = 720;
    export let height = 460;
    export let surface: Surface = FULL_SURFACE;
    export let grid = 64;
    export let heightScale = 1.15;
    export let glow = 0.7;
    export let autoRotate = false;
    export let interactive = true;
    export let showLabels = true;
    // When set, topic labels and surface taps launch a focus drill scoped to the
    // topic (ux-foundation 5). Threaded to the renderer for raycast taps and to
    // the 2D fallback so both paths reach the same drill.
    export let onTopic: ((slug: string) => void) | undefined = undefined;
    // Projection scale for the 2D fallback. Defaults to a width-proportional
    // value that matches the 3D framing closely enough for the fallback.
    export let fallbackScale: number | undefined = undefined;

    function launch(topic: string | undefined): void {
        if (onTopic && topic) {
            onTopic(topic);
        }
    }

    let stage: HTMLDivElement | undefined;
    let handle: Manifold3DHandle | undefined;
    let observer: MutationObserver | undefined;
    let labels: ProjectedLabel3D[] = [];
    // Start on the 3D path; flip to the 2D fallback if WebGL is missing or fails.
    let use2d = false;

    $: scale2d = fallbackScale ?? Math.round(width * 0.216);

    function currentTheme(): "light" | "dark" {
        const dark =
            document.documentElement.classList.contains("night-mode") ||
            document.body.classList.contains("night-mode");
        return dark ? "dark" : "light";
    }

    onMount(() => {
        if (!stage || !supportsWebGL()) {
            use2d = true;
            return;
        }
        try {
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
                onTopic,
            });
        } catch {
            // A no-WebGL context (or a lost GPU) throws here; degrade to 2D.
            use2d = true;
            return;
        }
        observer = new MutationObserver(() => handle?.update(surface, currentTheme()));
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["class"],
        });
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

{#if use2d}
    <Manifold
        {width}
        {height}
        scale={scale2d}
        {glow}
        {grid}
        {surface}
        {showLabels}
        {onTopic}
    />
{:else}
    <div class="manifold3d" style="width: {width}px; height: {height}px;">
        <div class="stage" bind:this={stage}></div>
        {#if showLabels}
            <svg {width} {height} class="leaders">
                {#each labels as l (l.name)}
                    {#if l.visible}
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
                    {/if}
                {/each}
            </svg>
            {#each labels as l (l.name)}
                {#if l.visible}
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
                {/if}
            {/each}
        {/if}
    </div>
{/if}

<style lang="scss">
    .manifold3d {
        position: relative;
        max-width: 100%;
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
