<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep left navigation rail. Logo, the calm destinations, and an optional
    streak footer. Monochrome; the active item takes a surface chip. Shared
    across the full-bleed pgrep surfaces, so it is the single source of truth
    for the rail (the surface shell renders exactly one of these).

    Destinations follow ux-foundation.md section 4: Home, Study, Progress,
    Library, Settings. Library returns at L4, so it is omitted until its route
    exists rather than linking to a dead page. Diagnostic is a first-run and
    re-runnable flow, not a permanent tab, so it is reached from a surface
    (Home, Progress) rather than the rail.

    The streak is only shown when a real value is passed. We never fabricate a
    streak, so the rail stays honest on every surface.
-->
<script lang="ts">
    import { page } from "$app/state";

    import PgrepMark from "$lib/components/PgrepMark.svelte";
    import { closeRail, narrow, requestReset } from "$lib/pgrep/nav";

    export let active = "Home";
    export let streak: number | undefined = undefined;
    export let collapsed = false;

    const items = [
        { name: "Home", href: "/pgrep" },
        { name: "Study", href: "/pgrep/study" },
        { name: "Progress", href: "/pgrep/progress" },
        { name: "Library", href: "/pgrep/library" },
        { name: "Settings", href: "/pgrep/settings" },
    ];

    // A plain link to the current URL is a no-op, so an in-progress surface never
    // resets. Turn a click on the exact current destination into a reset signal
    // instead. Compare against the real pathname (not just the active section) so
    // a nested route like /pgrep/study/exam still navigates up to Study rather
    // than resetting in place. Modified clicks are left to the browser.
    function onNavClick(event: MouseEvent, href: string): void {
        if (href !== page.url.pathname) {
            return;
        }
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
            return;
        }
        event.preventDefault();
        requestReset();
        if ($narrow) {
            closeRail();
        }
    }
</script>

<nav class="rail" class:collapsed aria-hidden={collapsed}>
    <div class="top">
        <a class="brand" href="/pgrep" aria-label="pgrep home">
            <PgrepMark size={30} />
            <span>pgrep</span>
        </a>
        <button
            class="collapse"
            type="button"
            on:click={closeRail}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
        >
            <svg
                width="18"
                height="18"
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

    <div class="nav">
        {#each items as item (item.name)}
            <a
                href={item.href}
                class="item"
                class:active={item.name === active}
                aria-current={item.name === active ? "page" : undefined}
                on:click={(event) => onNavClick(event, item.href)}
            >
                <svg
                    width="18"
                    height="18"
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                >
                    {#if item.name === "Home"}
                        <path
                            d="M3 9.5 L10 3.5 L17 9.5 V16 a1 1 0 0 1 -1 1 H4 a1 1 0 0 1 -1 -1 Z"
                        />
                    {:else if item.name === "Study"}
                        <path
                            d="M2.5 4.5 C4.5 3.3 7 3.3 9 4.5 V16 C7 14.8 4.5 14.8 2.5 16 Z"
                        />
                        <path
                            d="M17.5 4.5 C15.5 3.3 13 3.3 11 4.5 V16 C13 14.8 15.5 14.8 17.5 16 Z"
                        />
                    {:else if item.name === "Progress"}
                        <polyline points="2.5,14.5 7,10 10,13 17.5,5" />
                        <polyline points="12.5,5 17.5,5 17.5,10" />
                    {:else if item.name === "Library"}
                        <path
                            d="M10 5 C8 3.8 5.5 3.8 3 4.5 V15.5 C5.5 14.8 8 14.8 10 16 C12 14.8 14.5 14.8 17 15.5 V4.5 C14.5 3.8 12 3.8 10 5 Z"
                        />
                        <line x1="10" y1="5" x2="10" y2="16" />
                    {:else}
                        <line x1="3" y1="5.5" x2="17" y2="5.5" />
                        <line x1="3" y1="10" x2="17" y2="10" />
                        <line x1="3" y1="14.5" x2="17" y2="14.5" />
                    {/if}
                </svg>
                {item.name}
            </a>
        {/each}
    </div>

    {#if streak != null}
        <div class="streak">
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
                <path
                    d="M10 2.5 C10 6 6 7 6 11 a4 4 0 0 0 8 0 C14 8.5 11.5 7.5 11.5 5 C11 5.8 10 6.2 10 2.5 Z"
                />
            </svg>
            <span>{streak} day streak</span>
        </div>
    {/if}
</nav>

<style lang="scss">
    .rail {
        flex: 0 0 auto;
        width: var(--rail-width);
        border-right: var(--hairline);
        display: flex;
        flex-direction: column;
        padding: 28px 16px 24px;
        font-family: var(--font-ui);
        overflow: hidden;
        transition:
            width var(--duration-calm) var(--ease-spring),
            padding var(--duration-calm) var(--ease-spring);
    }

    /* Collapsed on entering a learning surface (ts/lib/pgrep/nav.ts). Animate to
       zero width and drop out of the tab order once hidden, so the content takes
       the full width. The top-left button and left-edge handle (in +layout) bring
       it back. */
    .rail.collapsed {
        width: 0;
        padding-left: 0;
        padding-right: 0;
        border-right-color: transparent;
        visibility: hidden;
        transition:
            width var(--duration-calm) var(--ease-spring),
            padding var(--duration-calm) var(--ease-spring),
            visibility 0s linear var(--duration-calm);
    }

    @media (prefers-reduced-motion: reduce) {
        .rail {
            transition: none;
        }
    }

    /* Phone: the rail leaves the flow and becomes an overlay drawer so it never
       squeezes the content. It slides in from the left over the layout's scrim
       and slides out when collapsed, rather than the inline width animation. */
    @media (max-width: 640px) {
        .rail {
            position: fixed;
            top: 0;
            bottom: 0;
            left: 0;
            z-index: 40;
            width: min(82vw, 292px);
            background: var(--canvas);
            box-shadow: var(--shadow-card);
            transform: translateX(0);
            transition: transform var(--duration-calm) var(--ease-spring);
        }

        .rail.collapsed {
            width: min(82vw, 292px);
            padding: 28px 16px 24px;
            border-right-color: var(--border);
            transform: translateX(-100%);
            visibility: hidden;
            transition:
                transform var(--duration-calm) var(--ease-spring),
                visibility 0s linear var(--duration-calm);
        }
    }

    @media (max-width: 640px) and (prefers-reduced-motion: reduce) {
        .rail,
        .rail.collapsed {
            transition: none;
        }
    }

    .top {
        display: flex;
        align-items: center;
        gap: var(--space-1);
        margin-bottom: 36px;
    }

    .brand {
        flex: 1 1 auto;
        min-width: 0;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 0 12px;
        color: var(--text);
        text-decoration: none;
        transition: var(--transition-calm);

        span {
            font-size: 15px;
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        &:hover {
            opacity: 0.7;
        }
    }

    .collapse {
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        border: none;
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

    .nav {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 12px;
        border-radius: var(--radius-control);
        color: var(--muted);
        text-decoration: none;
        font-size: 14px;
        font-weight: 500;
        border: 1px solid transparent;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
        }

        &.active {
            color: var(--text);
            background: var(--surface);
            border-color: var(--border);
        }
    }

    .streak {
        margin-top: auto;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 12px;
        color: var(--muted);
        font-size: 13px;

        span {
            font-variant-numeric: tabular-nums;
        }
    }

    .brand:focus-visible,
    .collapse:focus-visible,
    .item:focus-visible {
        outline: 2px solid var(--focus-ring);
        outline-offset: 2px;
        border-radius: var(--radius-control);
    }
</style>
