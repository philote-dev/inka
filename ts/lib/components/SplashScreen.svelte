<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep opening animation. A brief branded splash on app open: the nested
    contour mark draws in, the wordmark fades up, then the whole thing fades out
    to reveal the app. Skippable with a click or a key, and near-instant under
    prefers-reduced-motion. Design tokens only, both themes.
-->
<script lang="ts">
    import { onMount } from "svelte";

    export let onDone: () => void = () => {};

    let leaving = false;
    const reduce =
        typeof window !== "undefined" &&
        (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);

    let holdTimer: ReturnType<typeof setTimeout>;
    let doneTimer: ReturnType<typeof setTimeout>;

    function finish(): void {
        if (leaving) {
            return;
        }
        leaving = true;
        clearTimeout(holdTimer);
        doneTimer = setTimeout(onDone, reduce ? 0 : 320);
    }

    function onKey(event: KeyboardEvent): void {
        if (event.key === "Escape" || event.key === "Enter" || event.key === " ") {
            finish();
        }
    }

    onMount(() => {
        holdTimer = setTimeout(finish, reduce ? 450 : 1500);
        return () => {
            clearTimeout(holdTimer);
            clearTimeout(doneTimer);
        };
    });
</script>

<svelte:window on:keydown={onKey} />

<button
    class="splash"
    class:leaving
    class:reduce
    type="button"
    aria-label="Skip intro"
    on:click={finish}
>
    <span class="mark">
        <svg
            viewBox="0 0 32 32"
            fill="none"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
        >
            <path
                pathLength="1"
                d="M16 3.5 C22 3.5 28.5 7.5 28.5 14 C28.5 19 25 21 24 24.5 C23 27.5 20 29 16 28.5 C10.5 28 6.5 25.5 4.5 21 C2.5 16.5 3.5 10.5 7.5 7 C10 4.8 13 3.5 16 3.5 Z"
                stroke="currentColor"
                stroke-width="1.4"
            />
            <path
                pathLength="1"
                d="M16 8 C20 8 24 10.5 24 14.5 C24 17.5 22 19 21.2 21.2 C20.5 23.2 18.5 24.3 16 24 C12.5 23.6 10 22 8.8 19 C7.6 16 8.2 12.5 10.6 10.3 C12.2 8.9 14 8 16 8 Z"
                stroke="currentColor"
                stroke-width="1.4"
            />
            <path
                pathLength="1"
                d="M16 12.5 C18.2 12.5 20 13.8 20 15.8 C20 17.3 19 18.1 18.6 19.2 C18.2 20.2 17.2 20.8 16 20.6 C14.2 20.4 13 19.5 12.4 18 C11.8 16.5 12.1 14.8 13.3 13.7 C14.1 13 15 12.5 16 12.5 Z"
                stroke="currentColor"
                stroke-width="1.4"
            />
        </svg>
        <span class="word">pgrep</span>
    </span>
</button>

<style lang="scss">
    .splash {
        position: fixed;
        inset: 0;
        z-index: 60;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0;
        padding: 0;
        border: none;
        background: var(--canvas);
        color: var(--text);
        cursor: pointer;
        opacity: 1;
        transition: opacity 300ms var(--ease-spring);
    }

    .splash.leaving {
        opacity: 0;
        pointer-events: none;
    }

    .mark {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        animation: pgrep-splash-rise 620ms var(--ease-spring) both;
    }

    svg {
        width: 76px;
        height: 76px;
        display: block;
    }

    svg path {
        stroke-dasharray: 1;
        stroke-dashoffset: 1;
        animation: pgrep-splash-draw 820ms var(--ease-spring) forwards;
    }

    svg path:nth-child(2) {
        animation-delay: 120ms;
    }

    svg path:nth-child(3) {
        animation-delay: 240ms;
    }

    .word {
        font-family: var(--font-ui);
        font-size: var(--text-emphasis);
        font-weight: 600;
        letter-spacing: 0.02em;
        opacity: 0;
        animation: pgrep-splash-word 460ms var(--ease-spring) 460ms forwards;
    }

    @keyframes pgrep-splash-rise {
        from {
            opacity: 0;
            transform: scale(0.92);
        }
        to {
            opacity: 1;
            transform: none;
        }
    }

    @keyframes pgrep-splash-draw {
        to {
            stroke-dashoffset: 0;
        }
    }

    @keyframes pgrep-splash-word {
        to {
            opacity: 1;
        }
    }

    /* Reduced motion: no draw or rise, hold the static mark briefly instead. */
    .splash.reduce .mark,
    .splash.reduce .word,
    .splash.reduce svg path {
        animation: none;
        opacity: 1;
        stroke-dashoffset: 0;
        transform: none;
    }

    @media (prefers-reduced-motion: reduce) {
        .mark,
        .word,
        svg path {
            animation: none;
            opacity: 1;
            stroke-dashoffset: 0;
            transform: none;
        }

        .splash {
            transition: none;
        }
    }
</style>
