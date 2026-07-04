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
    export let active = "Home";
    export let streak: number | undefined = undefined;

    const items = [
        { name: "Home", href: "/pgrep" },
        { name: "Study", href: "/pgrep/study" },
        { name: "Progress", href: "/pgrep/progress" },
        { name: "Library", href: "/pgrep/library" },
        { name: "Settings", href: "/pgrep/settings" },
    ];
</script>

<nav class="rail">
    <div class="brand">
        <svg
            width="30"
            height="30"
            viewBox="0 0 32 32"
            fill="none"
            aria-label="pgrep logo"
        >
            <path
                d="M16 3.5 C22 3.5 28.5 7.5 28.5 14 C28.5 19 25 21 24 24.5 C23 27.5 20 29 16 28.5 C10.5 28 6.5 25.5 4.5 21 C2.5 16.5 3.5 10.5 7.5 7 C10 4.8 13 3.5 16 3.5 Z"
                stroke="currentColor"
                stroke-width="1.4"
            />
            <path
                d="M16 8 C20 8 24 10.5 24 14.5 C24 17.5 22 19 21.2 21.2 C20.5 23.2 18.5 24.3 16 24 C12.5 23.6 10 22 8.8 19 C7.6 16 8.2 12.5 10.6 10.3 C12.2 8.9 14 8 16 8 Z"
                stroke="currentColor"
                stroke-width="1.4"
            />
            <path
                d="M16 12.5 C18.2 12.5 20 13.8 20 15.8 C20 17.3 19 18.1 18.6 19.2 C18.2 20.2 17.2 20.8 16 20.6 C14.2 20.4 13 19.5 12.4 18 C11.8 16.5 12.1 14.8 13.3 13.7 C14.1 13 15 12.5 16 12.5 Z"
                stroke="currentColor"
                stroke-width="1.4"
            />
        </svg>
        <span>pgrep</span>
    </div>

    <div class="nav">
        {#each items as item (item.name)}
            <a
                href={item.href}
                class="item"
                class:active={item.name === active}
                aria-current={item.name === active ? "page" : undefined}
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
        width: 216px;
        flex: 0 0 216px;
        border-right: var(--hairline);
        display: flex;
        flex-direction: column;
        padding: 28px 16px 24px;
        font-family: var(--font-ui);
    }

    .brand {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 0 12px;
        margin-bottom: 36px;
        color: var(--text);

        span {
            font-size: 15px;
            font-weight: 600;
            letter-spacing: -0.01em;
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
</style>
