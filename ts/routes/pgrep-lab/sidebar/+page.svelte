<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Sidebar motion (the edge-pill rail). A self-contained playground for the
     collapse behavior from design/sidebar-nav-animations-svelte-guide.md, kept
     on pgrep tokens (--rail-width, --duration-calm, --ease-spring). No bridge
     calls; the rails here are fixtures, not the real NavRail.

     One handle toggles the rail: a small faded pill that hides it (from the rail
     edge) and shows it again (from the screen edge). No in-rail arrow, no
     top-left button, no chevron. Two prototypes for how the pill behaves when
     the rail opens, so we can pick the one that feels right:
       - Travel: the pill slides with the rail edge, staying pinned to it.
       - Fade:   the rail opens first, then the pill fades in at the edge.
     The Current variant is today's app behavior, kept for contrast.

     Implementation note: base.scss forces `transition: color, box-shadow` on
     every <button>, so a button can never animate its own position or opacity.
     The position lives on a wrapper <div> (.toggleSlot) and the fade lives on
     the <span> pill, both of which are free to transition. -->
<script lang="ts">
    import { onDestroy } from "svelte";

    const VARIANTS = [
        { id: "travel", label: "Travel" },
        { id: "fade", label: "Fade" },
        { id: "current", label: "Current" },
    ] as const;
    type Variant = (typeof VARIANTS)[number]["id"];

    // Default to the two prototypes side by side, which is the comparison to make.
    let focus: "compare" | Variant = "compare";

    let collapsed = false;
    let reduced = false;
    let theme: "light" | "dark" = "light";

    // "Settled" is false for one rail-duration after a toggle. The Fade prototype
    // keeps its pill hidden until the rail has settled, then fades it in, so the
    // pill never slides across (no teleport, no travel).
    const DURATION = 240; // ms, matches --duration-calm
    let settled = true;
    let settleTimer: ReturnType<typeof setTimeout> | undefined;

    function setCollapsed(next: boolean): void {
        collapsed = next;
        settled = false;
        clearTimeout(settleTimer);
        settleTimer = setTimeout(() => (settled = true), reduced ? 0 : DURATION);
    }

    onDestroy(() => clearTimeout(settleTimer));

    $: shown = focus === "compare" ? (["travel", "fade"] as Variant[]) : [focus];

    const NOTE: Record<Variant, string> = {
        travel: "The pill stays pinned to the rail edge and slides with it as the rail opens and closes.",
        fade: "The rail opens first; the pill then fades in at the edge once it settles. Nothing slides across.",
        current: "Today's app: an in-rail arrow hides it, a faint handle plus a top-left button show it. Contents squish as the rail narrows.",
    };
</script>

<div class="head">
    <h1>Sidebar motion</h1>
    <p>
        One small pill on the sidebar edge toggles the rail: click to hide, and it
        stays on the screen edge to click again and show. Two prototypes for how the
        pill behaves as the rail opens, Travel and Fade, are shown side by side so we
        can pick the feel. Collapse the rail and watch the left column: the proposed
        rails keep their contents rigid, the current one squishes them.
    </p>
</div>

<div class="controls">
    <div class="seg" role="group" aria-label="Which variant to show">
        <button
            type="button"
            class="seg__btn"
            class:is-active={focus === "compare"}
            on:click={() => (focus = "compare")}>Compare</button
        >
        {#each VARIANTS as v (v.id)}
            <button
                type="button"
                class="seg__btn"
                class:is-active={focus === v.id}
                on:click={() => (focus = v.id)}>{v.label}</button
            >
        {/each}
    </div>

    <button type="button" class="btn" on:click={() => setCollapsed(!collapsed)}>
        {collapsed ? "Expand rail" : "Collapse rail"}
    </button>

    <label class="check">
        <input type="checkbox" bind:checked={reduced} />
        Force reduced motion
    </label>

    <div class="seg" role="group" aria-label="Theme">
        <button
            type="button"
            class="seg__btn"
            class:is-active={theme === "light"}
            on:click={() => (theme = "light")}>Light</button
        >
        <button
            type="button"
            class="seg__btn"
            class:is-active={theme === "dark"}
            on:click={() => (theme = "dark")}>Dark</button
        >
    </div>
</div>

<div class="stages" class:stages--single={focus !== "compare"}>
    {#each shown as variant (variant)}
        <div class="col">
            <div class="col__head">
                <span class="col__title">{VARIANTS.find((v) => v.id === variant)?.label}</span>
                <span class="col__note">{NOTE[variant]}</span>
            </div>

            <!-- Nested .pgrep so dark tokens (keyed off .pgrep.night-mode) apply to
                 the stage subtree, matching the other lab sandboxes. -->
            <div class="pgrep stage-host" class:night-mode={theme === "dark"}>
                <div
                    class="stage {variant}"
                    class:proposed={variant !== "current"}
                    class:is-collapsed={collapsed}
                    class:is-reduced={reduced}
                    class:is-settled={settled}
                >
                    <!-- Outer frame: clips. Its width animates to zero on collapse. -->
                    <div class="railOuter">
                        <!-- Inner: fixed width in the proposed variants (so it only
                             fades), full width in the current one (so it squishes). -->
                        <div class="railInner">
                            <div class="railTop">
                                <span class="brand">
                                    <span class="brand__dot" aria-hidden="true"></span>
                                    pgrep
                                </span>
                                <!-- Current keeps the in-rail hide arrow. Proposed
                                     drops it in favour of the edge pill below. -->
                                {#if variant === "current"}
                                    <button
                                        type="button"
                                        class="collapse"
                                        aria-label="Collapse sidebar"
                                        title="Collapse sidebar"
                                        on:click={() => setCollapsed(true)}
                                    >
                                        <svg
                                            width="16"
                                            height="16"
                                            viewBox="0 0 20 20"
                                            fill="none"
                                            stroke="currentColor"
                                            stroke-width="1.5"
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                        >
                                            <polyline points="12,5 7,10 12,15" />
                                        </svg>
                                    </button>
                                {/if}
                            </div>

                            <div class="items">
                                {#each ["Home", "Study", "Progress", "Library", "Settings"] as item, i (item)}
                                    <span class="item" class:active={i === 1}>
                                        <span class="item__dot" aria-hidden="true"></span>
                                        {item}
                                    </span>
                                {/each}
                            </div>
                        </div>
                    </div>

                    {#if variant === "current"}
                        <!-- Current: reopen affordances, only while collapsed. -->
                        {#if collapsed}
                            <button
                                type="button"
                                class="edge"
                                aria-label="Show sidebar"
                                on:click={() => setCollapsed(false)}
                            >
                                <span class="handle" aria-hidden="true"></span>
                            </button>
                            <button
                                type="button"
                                class="burger"
                                aria-label="Show sidebar"
                                on:click={() => setCollapsed(false)}
                            >
                                <svg
                                    width="16"
                                    height="16"
                                    viewBox="0 0 20 20"
                                    fill="none"
                                    stroke="currentColor"
                                    stroke-width="1.5"
                                    stroke-linecap="round"
                                >
                                    <line x1="3" y1="6" x2="17" y2="6" />
                                    <line x1="3" y1="10" x2="17" y2="10" />
                                    <line x1="3" y1="14" x2="17" y2="14" />
                                </svg>
                            </button>
                        {/if}
                    {:else}
                        <!-- Proposed: one edge pill toggles the rail both ways. The
                             wrapper div owns the position (so it can travel); the
                             pill span owns the fade. A very faint full-height edge
                             wash appears on hover while collapsed. -->
                        <div class="toggleSlot">
                            <button
                                type="button"
                                class="toggle"
                                aria-label={collapsed ? "Show sidebar" : "Hide sidebar"}
                                on:click={() => setCollapsed(!collapsed)}
                            >
                                <span class="pill" aria-hidden="true"></span>
                            </button>
                        </div>
                    {/if}

                    <!-- Placeholder content, so the widening main column and (in the
                         current variant) the squishing rail are both visible. -->
                    <div class="main">
                        <div class="line line--title"></div>
                        <div class="line"></div>
                        <div class="line line--short"></div>
                        <div class="cards">
                            <div class="mini"></div>
                            <div class="mini"></div>
                            <div class="mini"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    {/each}
</div>

<section class="legend">
    <h2>What to look for</h2>
    <ul>
        <li>
            <strong>Travel vs Fade.</strong> Collapse and expand each rail. Travel keeps
            the pill glued to the rail edge the whole way. Fade lets the rail open first,
            then the pill fades in at the edge once it settles.
        </li>
        <li>
            <strong>One handle, both directions.</strong> The same pill hides the rail
            (from its edge) and shows it (from the screen edge). No in-rail arrow, no
            top-left button, no chevron.
        </li>
        <li>
            <strong>Faded edge wash.</strong> While collapsed, hovering the screen edge
            lifts a very faint full-height wash alongside the pill, so the edge is
            discoverable without protruding.
        </li>
        <li>
            <strong>Reduced motion.</strong> With the toggle on (or the OS setting), the
            rail snaps and the pill appears at once, with no travel or fade.
        </li>
    </ul>
    <p class="src">
        Reference: <code>design/sidebar-nav-animations-svelte-guide.md</code> · numbers
        use pgrep tokens (<code>--rail-width</code>, <code>--duration-calm</code>,
        <code>--ease-spring</code>).
    </p>
</section>

<style lang="scss">
    .head {
        margin-bottom: var(--space-3);

        h1 {
            margin: 0 0 var(--space-0);
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        p {
            margin: 0;
            max-width: 68ch;
            font-size: var(--text-body);
            line-height: 1.6;
            color: var(--muted);
        }
    }

    .controls {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--space-1) var(--space-2);
        margin-bottom: var(--space-3);
    }

    .seg {
        display: inline-flex;
        padding: 3px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        background: var(--surface);
    }

    .seg__btn {
        appearance: none;
        border: 0;
        background: transparent;
        padding: 6px 14px;
        border-radius: var(--radius-pill);
        font: inherit;
        font-size: var(--text-small);
        font-weight: 500;
        color: var(--muted);
        cursor: pointer;

        &:hover {
            color: var(--text);
        }

        &.is-active {
            color: var(--action-fg);
            background: var(--action-bg);
        }
    }

    .btn {
        appearance: none;
        padding: 8px 16px;
        border: var(--hairline);
        border-radius: var(--radius-control);
        background: var(--surface);
        font: inherit;
        font-size: var(--text-small);
        font-weight: 500;
        color: var(--text);
        cursor: pointer;

        &:hover {
            border-color: var(--muted);
            background: var(--hover-wash);
        }
    }

    .check {
        display: inline-flex;
        align-items: center;
        gap: var(--space-0);
        font-size: var(--text-small);
        color: var(--muted);
        cursor: pointer;
    }

    .stages {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: var(--space-3);
        align-items: start;

        &--single {
            grid-template-columns: minmax(0, 720px);
        }
    }

    @media (max-width: 900px) {
        .stages {
            grid-template-columns: 1fr;
        }
    }

    .col__head {
        display: flex;
        flex-direction: column;
        gap: 2px;
        margin-bottom: var(--space-1);
    }

    .col__title {
        font-size: var(--text-emphasis);
        font-weight: 600;
    }

    .col__note {
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    .stage-host {
        border-radius: var(--radius-frame);
    }

    /* The mini app shell. Everything below is scoped to the stage so it never
       leaks into the lab chrome. */
    .stage {
        position: relative;
        display: flex;
        height: 340px;
        overflow: hidden;
        border: var(--hairline);
        border-radius: var(--radius-frame);
        background: var(--canvas);
        color: var(--text);
    }

    /* Part 1: the outer frame clips; its width collapses to zero. */
    .railOuter {
        position: relative;
        z-index: 2;
        flex: 0 0 auto;
        width: var(--rail-width);
        overflow: hidden;
        border-right: var(--hairline);
        transition: width var(--duration-calm) var(--ease-spring);
    }

    .is-collapsed .railOuter {
        width: 0;
        border-right-color: transparent;
    }

    .railInner {
        box-sizing: border-box;
        width: var(--rail-width);
        height: 100%;
        padding: var(--space-3) var(--space-2);
        display: flex;
        flex-direction: column;
        transition: opacity var(--duration-calm) var(--ease-spring);
    }

    /* Proposed: the inner is fixed width, so it stays rigid and only fades. */
    .proposed.is-collapsed .railInner {
        opacity: 0;
    }

    /* Current: the inner tracks the outer, so the contents squish as it closes. */
    .current .railInner {
        width: 100%;
    }

    .railTop {
        display: flex;
        align-items: center;
        gap: var(--space-1);
        margin-bottom: var(--space-3);
        min-height: 26px;
    }

    .brand {
        flex: 1 1 auto;
        min-width: 0;
        display: flex;
        align-items: center;
        gap: var(--space-0);
        font-size: var(--text-body);
        font-weight: 600;
        letter-spacing: -0.01em;
        white-space: nowrap;
    }

    .brand__dot {
        flex: 0 0 auto;
        width: 18px;
        height: 18px;
        border-radius: 6px;
        background: var(--readiness);
    }

    .collapse {
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 26px;
        border: 0;
        background: none;
        color: var(--muted);
        border-radius: var(--radius-control);
        cursor: pointer;

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
        }
    }

    .items {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .item {
        display: flex;
        align-items: center;
        gap: var(--space-1);
        padding: 9px 12px;
        border-radius: var(--radius-control);
        color: var(--muted);
        font-size: var(--text-body);
        font-weight: 500;
        white-space: nowrap;
        border: 1px solid transparent;

        &.active {
            color: var(--text);
            background: var(--surface);
            border-color: var(--border);
        }
    }

    .item__dot {
        flex: 0 0 auto;
        width: 14px;
        height: 14px;
        border-radius: 4px;
        border: 1.5px solid currentColor;
        opacity: 0.6;
    }

    /* Proposed: the edge pill. The wrapper owns the position (a div, so it can
       transition, unlike a button); the pill span owns the fade/grow. Parent-
       scoped so the app-wide button border/transition rules cannot override it. */
    .proposed .toggleSlot {
        position: absolute;
        top: 0;
        bottom: 0;
        left: calc(var(--rail-width) - 9px);
        z-index: 5;
        width: 18px;
    }

    .proposed.is-collapsed .toggleSlot {
        left: 0;
    }

    /* Travel: the wrapper slides with the rail edge. */
    .travel .toggleSlot {
        transition: left var(--duration-calm) var(--ease-spring);
    }

    /* Very faint full-height edge wash, only while collapsed and hovered. It sits
       flush to the screen edge and fades out fast, so it hints without protruding. */
    .proposed .toggleSlot::before {
        content: "";
        position: absolute;
        top: 0;
        bottom: 0;
        left: 0;
        width: 12px;
        background: linear-gradient(
            to right,
            color-mix(in srgb, var(--text) 9%, transparent),
            transparent
        );
        opacity: 0;
        pointer-events: none;
        transition: opacity var(--duration-calm) var(--ease-spring);
    }

    .proposed.is-collapsed .toggleSlot:hover::before,
    .proposed.is-collapsed .toggleSlot:focus-within::before {
        opacity: 1;
    }

    .proposed .toggle {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0;
        padding: 0;
        border: 1px solid transparent;
        background: none;
        cursor: pointer;
    }

    .pill {
        width: 4px;
        height: 44px;
        border-radius: var(--radius-pill);
        background: var(--border);
        transition:
            width var(--duration-calm) var(--ease-spring),
            background var(--duration-calm) var(--ease-spring),
            opacity var(--duration-calm) var(--ease-spring);
    }

    /* Travel keeps the pill present; Fade hides it until the rail has settled. */
    .travel .pill {
        opacity: 0.55;
    }

    .fade .pill {
        opacity: 0;
    }

    .fade.is-settled .pill {
        opacity: 0.55;
    }

    .travel .toggle:hover .pill,
    .travel .toggle:focus-visible .pill,
    .fade.is-settled .toggle:hover .pill,
    .fade.is-settled .toggle:focus-visible .pill {
        width: 6px;
        opacity: 1;
        background: var(--muted);
    }

    /* The focus ring rides the small pill, not the full-height hit area. */
    .proposed .toggle:focus-visible .pill {
        box-shadow: 0 0 0 2px var(--canvas), 0 0 0 4px var(--focus-ring);
    }

    /* Current: the faint reopen handle (unchanged from today's app). */
    .stage .edge {
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        z-index: 3;
        width: 16px;
        display: flex;
        align-items: center;
        justify-content: flex-start;
        margin: 0;
        padding: 0;
        border: 1px solid transparent;
        background: none;
        cursor: pointer;
    }

    .handle {
        width: 4px;
        height: 46px;
        border-radius: var(--radius-pill);
        background: var(--border);
        opacity: 0.5;
        transition:
            width var(--duration-calm) var(--ease-spring),
            background var(--duration-calm) var(--ease-spring),
            opacity var(--duration-calm) var(--ease-spring);
    }

    .stage .edge:hover .handle,
    .stage .edge:focus-visible .handle {
        width: 6px;
        opacity: 1;
        background: var(--muted);
    }

    /* Current keeps a top-left button as a second way back. */
    .burger {
        position: absolute;
        top: var(--space-2);
        left: var(--space-2);
        z-index: 4;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 36px;
        height: 36px;
        border: var(--hairline);
        border-radius: var(--radius-control);
        background: var(--surface);
        color: var(--muted);
        cursor: pointer;
        box-shadow: var(--shadow-card);

        &:hover {
            color: var(--text);
            border-color: var(--muted);
        }
    }

    .main {
        flex: 1 1 auto;
        min-width: 0;
        padding: var(--space-3);
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .line {
        height: 12px;
        border-radius: var(--radius-pill);
        background: var(--elevated);
        width: 100%;
    }

    .line--title {
        height: 20px;
        width: 45%;
        margin-bottom: var(--space-1);
        background: var(--border);
    }

    .line--short {
        width: 70%;
    }

    .cards {
        margin-top: var(--space-2);
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: var(--space-1);
    }

    .mini {
        height: 72px;
        border-radius: var(--radius-card);
        border: var(--hairline);
        background: var(--surface);
    }

    /* Preview of the reduced-motion experience, on top of the real media query. */
    .stage.is-reduced .railOuter,
    .stage.is-reduced .railInner,
    .stage.is-reduced .toggleSlot,
    .stage.is-reduced .toggleSlot::before,
    .stage.is-reduced .pill,
    .stage.is-reduced .handle {
        transition: none;
    }

    @media (prefers-reduced-motion: reduce) {
        .railOuter,
        .railInner,
        .toggleSlot,
        .toggleSlot::before,
        .pill,
        .handle {
            transition: none;
        }
    }

    .legend {
        margin-top: var(--space-4);
        max-width: 78ch;

        h2 {
            margin: 0 0 var(--space-1);
            font-size: var(--text-emphasis);
            font-weight: 600;
        }

        ul {
            margin: 0;
            padding-left: 1.2em;
            display: flex;
            flex-direction: column;
            gap: var(--space-1);
        }

        li {
            font-size: var(--text-body);
            line-height: 1.6;
            color: var(--muted);

            strong {
                color: var(--text);
                font-weight: 600;
            }
        }
    }

    .src {
        margin: var(--space-2) 0 0;
        font-size: var(--text-small);
        color: var(--muted);

        code {
            font-family: var(--font-mono);
            font-size: 0.92em;
        }
    }
</style>
