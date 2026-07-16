<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Status glyph for shell operations: orbital dots while working, then a
     drawn check / X. Variants live in /pgrep-lab/operation-ui for picking. -->
<script lang="ts" context="module">
    export type ActivityVariant = "orbit" | "cascade" | "soft";
    export type MarkPhase = "active" | "success" | "error" | "cancelled";
</script>

<script lang="ts">
    export let phase: MarkPhase = "active";
    export let variant: ActivityVariant = "orbit";

    const ORBIT_DOTS = 8;
    const CASCADE_DOTS = 8;
    const SOFT_DOTS = 6;

    $: working = phase === "active";
    $: dotCount =
        variant === "soft" ? SOFT_DOTS : variant === "cascade" ? CASCADE_DOTS : ORBIT_DOTS;
    $: stepDeg = 360 / dotCount;

    // Fixed size falloff around the ring (largest at index 0). Orbit rotates the
    // whole ring so the bright head chases; cascade/soft pulse each seat instead.
    function dotScale(index: number, count: number): number {
        const t = index / count;
        if (variant === "soft") {
            return 0.28 + 0.72 * Math.pow(1 - t, 1.35);
        }
        return 0.22 + 0.78 * Math.pow(1 - t, 1.15);
    }
</script>

<div
    class="mark"
    class:working
    class:success={phase === "success"}
    class:error={phase === "error"}
    class:cancelled={phase === "cancelled"}
    class:orbit={variant === "orbit"}
    class:cascade={variant === "cascade"}
    class:soft={variant === "soft"}
    aria-hidden="true"
>
    <div class="dots" class:show={working}>
        <div class="dots-spin">
            {#each Array(dotCount) as _, i (i)}
                <span
                    class="dot"
                    style="--i: {i}; --step: {stepDeg}deg; --scale: {dotScale(i, dotCount)}; --delay: {i}"
                ></span>
            {/each}
        </div>
    </div>

    <svg
        class="symbol check"
        class:show={phase === "success"}
        viewBox="0 0 24 24"
        fill="none"
    >
        <path
            class="stroke"
            d="M5.5 12.5 10 17l8.5-10"
            stroke="currentColor"
            stroke-width="2.25"
            stroke-linecap="round"
            stroke-linejoin="round"
        />
    </svg>

    <svg
        class="symbol cross"
        class:show={phase === "error"}
        viewBox="0 0 24 24"
        fill="none"
    >
        <path
            class="stroke"
            d="M7 7l10 10M17 7 7 17"
            stroke="currentColor"
            stroke-width="2.25"
            stroke-linecap="round"
        />
    </svg>

    <svg
        class="symbol dash"
        class:show={phase === "cancelled"}
        viewBox="0 0 24 24"
        fill="none"
    >
        <path
            class="stroke"
            d="M7 12h10"
            stroke="currentColor"
            stroke-width="2.25"
            stroke-linecap="round"
        />
    </svg>
</div>

<style lang="scss">
    .mark {
        position: relative;
        display: grid;
        place-items: center;
        width: 28px;
        height: 28px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        color: var(--muted);
    }

    .mark.success {
        border-color: var(--success);
        color: var(--success);
    }

    .mark.error {
        border-color: var(--error);
        color: var(--error);
    }

    .mark.working {
        color: var(--text);
    }

    .dots,
    .symbol {
        grid-area: 1 / 1;
    }

    .dots {
        position: relative;
        width: 18px;
        height: 18px;
        opacity: 0;
        transform: scale(0.72);
        pointer-events: none;
        transition:
            opacity 140ms var(--ease-spring),
            transform 160ms var(--ease-spring);
    }

    .dots.show {
        opacity: 1;
        transform: scale(1);
    }

    .dots-spin {
        position: absolute;
        inset: 0;
    }

    .mark.orbit .dots.show .dots-spin {
        animation: mark-orbit 880ms linear infinite;
    }

    .mark.soft .dots {
        width: 16px;
        height: 16px;
    }

    .mark.soft .dots.show .dots-spin {
        animation: mark-orbit 1200ms linear infinite;
    }

    .dot {
        position: absolute;
        top: 50%;
        left: 50%;
        width: 5px;
        height: 5px;
        border-radius: var(--radius-pill);
        background: currentColor;
        transform: rotate(calc(var(--i) * var(--step))) translateY(-7px)
            scale(var(--scale));
        transform-origin: center;
    }

    .mark.soft .dot {
        width: 4.5px;
        height: 4.5px;
        transform: rotate(calc(var(--i) * var(--step))) translateY(-6px)
            scale(var(--scale));
    }

    .mark.cascade .dot {
        /* Equal seats; the pulse carries the motion. */
        transform: rotate(calc(var(--i) * var(--step))) translateY(-7px) scale(0.55);
        opacity: 0.28;
        animation: mark-cascade 960ms var(--ease-spring) infinite;
        animation-delay: calc(var(--delay) * -120ms);
    }

    .symbol {
        width: 16px;
        height: 16px;
        opacity: 0;
        transform: scale(0.78);
        pointer-events: none;
        transition:
            opacity 160ms var(--ease-spring),
            transform 200ms var(--ease-spring);
    }

    .symbol.show {
        opacity: 1;
        transform: scale(1);
    }

    .stroke {
        stroke-dasharray: 32;
        stroke-dashoffset: 32;
    }

    .symbol.show .stroke {
        animation: mark-draw 280ms var(--ease-spring) forwards;
    }

    .cross .stroke {
        stroke-dasharray: 18;
        stroke-dashoffset: 18;
    }

    .dash .stroke {
        stroke-dasharray: 12;
        stroke-dashoffset: 12;
    }

    @keyframes mark-orbit {
        to {
            transform: rotate(360deg);
        }
    }

    @keyframes mark-cascade {
        0%,
        100% {
            opacity: 0.22;
            transform: rotate(calc(var(--i) * var(--step))) translateY(-7px) scale(0.45);
        }
        35% {
            opacity: 1;
            transform: rotate(calc(var(--i) * var(--step))) translateY(-7px) scale(1);
        }
    }

    @keyframes mark-draw {
        to {
            stroke-dashoffset: 0;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .mark.orbit .dots.show .dots-spin,
        .mark.soft .dots.show .dots-spin,
        .mark.cascade .dot,
        .symbol.show .stroke {
            animation: none;
        }

        .mark.cascade .dot {
            opacity: 0.55;
            transform: rotate(calc(var(--i) * var(--step))) translateY(-7px) scale(0.7);
        }

        .stroke {
            stroke-dashoffset: 0;
        }

        .dots,
        .symbol {
            transition: none;
        }
    }
</style>
