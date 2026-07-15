<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Sidebar motion (the "edge pill" rail). A self-contained playground that puts
     the app's current collapse behavior next to the proposed one from
     design/sidebar-nav-animations-svelte-guide.md, so the difference is visible
     rather than described. No bridge calls; the rails here are fixtures, not the
     real NavRail.

     Two techniques are on show:
       1. Collapse (guide Part 1). Current animates the rail's own width, so its
          contents squish as it closes. Proposed clips a fixed-width inner that
          only fades, so the contents stay rigid while they slide out.
       2. Reopen affordance (guide Part 2). Current leaves a faint edge handle
          plus a top-left button. Proposed grows the handle and reveals a slight
          chevron on hover, and drops the button: the handle is the one way back.

     All numbers are pgrep tokens (--rail-width, --duration-calm, --ease-spring),
     not the guide's verbatim values, so the feel stays on-brand. -->
<script lang="ts">
    const VARIANTS = [
        { id: "proposed", label: "Proposed" },
        { id: "current", label: "Current" },
    ] as const;
    type Variant = (typeof VARIANTS)[number]["id"];

    // Show both side by side by default so the contrast reads at a glance; a
    // single-variant focus is one click away for a closer look.
    let focus: Variant | "both" = "both";

    let collapsed = false;
    let reduced = false;
    let theme: "light" | "dark" = "light";

    $: shown = focus === "both" ? (["proposed", "current"] as Variant[]) : [focus];

    const NOTE: Record<Variant, string> = {
        proposed:
            "Fixed-width inner fades while the outer frame clips it. Contents stay rigid; the handle grows and shows a chevron on hover.",
        current:
            "The rail animates its own width, so its contents squish as it closes. A faint handle and a top-left button bring it back.",
    };
</script>

<div class="head">
    <h1>Sidebar motion</h1>
    <p>
        The collapsing rail and its reopen handle, current beside proposed. Collapse
        the rail and watch the left column: the current rail squishes its contents as
        it closes, the proposed one clips a fixed-width inner so they slide out rigid.
        While collapsed, hover the left edge to compare the reopen handles.
    </p>
</div>

<div class="controls">
    <div class="seg" role="group" aria-label="Which variant to show">
        <button
            type="button"
            class="seg__btn"
            class:is-active={focus === "both"}
            on:click={() => (focus = "both")}>Both</button
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

    <button type="button" class="btn" on:click={() => (collapsed = !collapsed)}>
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

<div class="stages" class:stages--single={focus !== "both"}>
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
                    class:is-collapsed={collapsed}
                    class:is-reduced={reduced}
                >
                    <!-- Outer frame: clips. Its width animates to zero on collapse. -->
                    <div class="railOuter">
                        <!-- Inner: fixed width in the proposed variant (so it only
                             fades), full width in the current one (so it squishes). -->
                        <div class="railInner">
                            <div class="railTop">
                                <span class="brand">
                                    <span class="brand__dot" aria-hidden="true"></span>
                                    pgrep
                                </span>
                                <button
                                    type="button"
                                    class="collapse"
                                    aria-label="Collapse sidebar"
                                    title="Collapse sidebar"
                                    on:click={() => (collapsed = true)}
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

                    <!-- Reopen affordances, only while collapsed. -->
                    {#if collapsed}
                        <button
                            type="button"
                            class="edge"
                            aria-label="Show sidebar"
                            on:click={() => (collapsed = false)}
                        >
                            <span class="handle" aria-hidden="true">
                                <svg
                                    class="chev"
                                    width="12"
                                    height="12"
                                    viewBox="0 0 20 20"
                                    fill="none"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                >
                                    <polyline points="8,5 13,10 8,15" />
                                </svg>
                            </span>
                        </button>

                        {#if variant === "current"}
                            <button
                                type="button"
                                class="burger"
                                aria-label="Show sidebar"
                                on:click={() => (collapsed = false)}
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
            <strong>Rail contents on collapse.</strong> Current squishes the labels as
            the rail narrows. Proposed keeps them rigid (fixed-width inner) and only fades
            them, so the close reads as one clean motion.
        </li>
        <li>
            <strong>The reopen handle.</strong> Hover the left edge while collapsed. Current
            barely thickens. Proposed grows into a small pill and reveals a slight chevron,
            signalling "click to reopen".
        </li>
        <li>
            <strong>The top-left button.</strong> Present in current, gone in proposed: the
            edge handle is the single reopen affordance on desktop.
        </li>
        <li>
            <strong>Reduced motion.</strong> With the toggle on (or the OS setting), every
            transition here is disabled and the rail snaps between states.
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
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
        }

        &.is-active {
            color: var(--action-fg);
            background: var(--action-bg);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
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
        transition: var(--transition-calm);

        &:hover {
            border-color: var(--muted);
            background: var(--hover-wash);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
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
    .is-collapsed .proposed .railInner,
    .proposed.is-collapsed .railInner {
        opacity: 0;
    }

    /* Current: the inner tracks the outer, so the contents squish as it closes
       (the ugliness the two-layer trick removes). No fade to soften the clip. */
    .current .railInner {
        width: 100%;
    }

    .railTop {
        display: flex;
        align-items: center;
        gap: var(--space-1);
        margin-bottom: var(--space-3);
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
        transition: var(--transition-calm);

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

    /* Part 2: the reopen handle. A generous edge zone gives an easy hover target
       even though the visible handle is thin. */
    .edge {
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        z-index: 3;
        width: 18px;
        display: flex;
        align-items: center;
        justify-content: flex-start;
        padding: 0;
        border: 0;
        background: none;
        cursor: pointer;
    }

    .handle {
        display: flex;
        align-items: center;
        justify-content: center;
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

    /* Proposed starts a touch more present and grows into a pill on hover. */
    .proposed .handle {
        width: 6px;
        opacity: 0.6;
    }

    .current .edge:hover .handle,
    .current .edge:focus-visible .handle {
        width: 6px;
        opacity: 1;
        background: var(--muted);
    }

    .proposed .edge:hover .handle,
    .proposed .edge:focus-visible .handle {
        width: 22px;
        opacity: 1;
        background: var(--action-bg);
    }

    .chev {
        color: var(--action-fg);
        opacity: 0;
        transition: opacity 150ms var(--ease-spring);
    }

    .proposed .edge:hover .chev,
    .proposed .edge:focus-visible .chev {
        opacity: 1;
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
        transition: var(--transition-calm);

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
    .stage.is-reduced .handle,
    .stage.is-reduced .chev,
    .stage.is-reduced .burger {
        transition: none;
    }

    @media (prefers-reduced-motion: reduce) {
        .railOuter,
        .railInner,
        .handle,
        .chev,
        .burger {
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
