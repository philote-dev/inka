<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Desktop edge-pill rail toggle. One control hides and shows the nav rail: a
     monochrome slab flush to the rail edge when open, and to the screen edge
     when collapsed. No chevron, no in-rail arrow, no top-left burger.

     Position lives on the wrapper (a div) because base.scss forces every
     <button> to only transition color/box-shadow, so a button can never animate
     left. The visual is a non-interactive span; the full-height hit button
     above it is kept visually invisible on press/focus so it never paints a
     tall outline of the clickable area. -->
<script lang="ts">
    import { railOpen, toggleRail } from "$lib/pgrep/nav";

    // Mouse click focuses the hit button; without a blur the pill stays in its
    // "active" (hover) size until the user clicks elsewhere. Keyboard users keep
    // focus and still get the grown state via :focus-visible.
    function onToggle(event: MouseEvent): void {
        toggleRail();
        (event.currentTarget as HTMLButtonElement).blur();
    }
</script>

<div
    class="slot"
    class:is-collapsed={!$railOpen}
    style="--tab-h:70px;--tab-w-rest:4px;--tab-w-hover:8px;--tab-radius:20px;--tab-op:0.5;"
>
    <button
        class="hit"
        type="button"
        on:click={onToggle}
        aria-label={$railOpen ? "Hide sidebar" : "Show sidebar"}
        aria-expanded={$railOpen}
    ></button>
    <span class="pill" aria-hidden="true"></span>
</div>

<style lang="scss">
    .slot {
        position: fixed;
        top: 0;
        bottom: 0;
        left: var(--rail-width);
        z-index: 30;
        width: calc(var(--tab-w-hover) + 8px);
        transition: left var(--duration-calm) var(--ease-spring);
    }

    .slot.is-collapsed {
        left: 0;
    }

    /* macOS product: clear the floating traffic lights, tracking the real
       safe-area inset pushed by pgrep_titlebar (never hardcode the height). */
    :global(body.pgrep-native-titlebar) .slot {
        top: var(--pgrep-titlebar-inset, 28px);
    }

    /* Very faint full-height edge wash while collapsed and hovered. Hover only —
       focus-within would flash the full hit area on click-hold. */
    .slot.is-collapsed::before {
        content: "";
        position: absolute;
        top: 0;
        bottom: 0;
        left: 0;
        width: 7px;
        background: linear-gradient(
            to right,
            color-mix(in srgb, var(--text) 5%, transparent),
            transparent
        );
        opacity: 0;
        pointer-events: none;
        transition: opacity var(--duration-calm) var(--ease-spring);
    }

    .slot.is-collapsed:hover::before {
        opacity: 1;
    }

    /* Invisible full-height hit target. Parent-scoped !important so app-wide
       button border/hover/focus rules cannot paint a tall outline. */
    .hit {
        position: absolute;
        inset: 0;
        z-index: 1;
        margin: 0;
        padding: 0;
        border: 1px solid transparent !important;
        background: none !important;
        box-shadow: none !important;
        outline: none !important;
        -webkit-tap-highlight-color: transparent;
        cursor: pointer;
    }

    .hit:hover,
    .hit:active,
    .hit:focus,
    .hit:focus-visible {
        border-color: transparent !important;
        background: none !important;
        box-shadow: none !important;
        outline: none !important;
    }

    .pill {
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        width: var(--tab-w-rest);
        height: var(--tab-h);
        border-radius: 0 var(--tab-radius) var(--tab-radius) 0;
        background: var(--muted);
        opacity: var(--tab-op);
        pointer-events: none;
        transition:
            width var(--duration-calm) var(--ease-spring),
            opacity var(--duration-calm) var(--ease-spring);
    }

    /* Hover for pointer; :focus-visible for keyboard. Do not use :focus-within —
       a mouse click would leave the pill stuck grown until something else focuses. */
    .slot:hover .pill,
    .hit:focus-visible ~ .pill {
        width: var(--tab-w-hover);
        opacity: 1;
    }

    @media (prefers-reduced-motion: reduce) {
        .slot,
        .slot.is-collapsed::before,
        .pill {
            transition: none;
        }
    }

    /* Phone keeps the burger; this control is desktop-only. */
    @media (max-width: 640px) {
        .slot {
            display: none;
        }
    }
</style>
