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

    import PgrepMark from "$lib/components/PgrepMark.svelte";

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
        <PgrepMark size={76} />
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

    @keyframes pgrep-splash-word {
        to {
            opacity: 1;
        }
    }

    /* Reduced motion: no draw or rise, hold the static mark briefly instead. */
    .splash.reduce .mark,
    .splash.reduce .word {
        animation: none;
        opacity: 1;
        transform: none;
    }

    @media (prefers-reduced-motion: reduce) {
        .mark,
        .word {
            animation: none;
            opacity: 1;
            transform: none;
        }

        .splash {
            transition: none;
        }
    }
</style>
