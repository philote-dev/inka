<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep surface shell. Loads the fonts + scoped design tokens, and provides
     the shared sidebar nav so every surface (Home, Study, Progress, Diagnostic)
     is reachable. Rail styling ported from the Claude Design Home export. -->
<script lang="ts">
    import { page } from "$app/state";

    import "@fontsource-variable/inter/index.css";
    import "@fontsource-variable/jetbrains-mono/index.css";
    import "./pgrep.scss";

    const links = [
        { href: "/pgrep", label: "Home" },
        { href: "/pgrep/study", label: "Study" },
        { href: "/pgrep/progress", label: "Progress" },
        { href: "/pgrep/diagnostic", label: "Diagnostic" },
    ];

    $: pathname = page.url.pathname;

    function isActive(href: string, current: string): boolean {
        if (href === "/pgrep") {
            return current === "/pgrep" || current === "/pgrep/";
        }
        return current === href || current.startsWith(`${href}/`);
    }
</script>

<div class="pgrep">
    <div class="shell">
        <nav class="rail">
            <div class="brand">
                <svg width="30" height="30" viewBox="0 0 32 32" fill="none" aria-label="pgrep logo">
                    <path d="M16 3.5 C22 3.5 28.5 7.5 28.5 14 C28.5 19 25 21 24 24.5 C23 27.5 20 29 16 28.5 C10.5 28 6.5 25.5 4.5 21 C2.5 16.5 3.5 10.5 7.5 7 C10 4.8 13 3.5 16 3.5 Z" stroke="currentColor" stroke-width="1.4" />
                    <path d="M16 8 C20 8 24 10.5 24 14.5 C24 17.5 22 19 21.2 21.2 C20.5 23.2 18.5 24.3 16 24 C12.5 23.6 10 22 8.8 19 C7.6 16 8.2 12.5 10.6 10.3 C12.2 8.9 14 8 16 8 Z" stroke="currentColor" stroke-width="1.4" />
                    <path d="M16 12.5 C18.2 12.5 20 13.8 20 15.8 C20 17.3 19 18.1 18.6 19.2 C18.2 20.2 17.2 20.8 16 20.6 C14.2 20.4 13 19.5 12.4 18 C11.8 16.5 12.1 14.8 13.3 13.7 C14.1 13 15 12.5 16 12.5 Z" stroke="currentColor" stroke-width="1.4" />
                </svg>
                <span>pgrep</span>
            </div>

            <div class="nav">
                {#each links as link (link.href)}
                    <a href={link.href} class="item" class:active={isActive(link.href, pathname)}>
                        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                            {#if link.label === "Home"}
                                <path d="M3 9.5 L10 3.5 L17 9.5 V16 a1 1 0 0 1 -1 1 H4 a1 1 0 0 1 -1 -1 Z" />
                            {:else if link.label === "Study"}
                                <path d="M2.5 4.5 C4.5 3.3 7 3.3 9 4.5 V16 C7 14.8 4.5 14.8 2.5 16 Z" />
                                <path d="M17.5 4.5 C15.5 3.3 13 3.3 11 4.5 V16 C13 14.8 15.5 14.8 17.5 16 Z" />
                            {:else if link.label === "Progress"}
                                <polyline points="2.5,14.5 7,10 10,13 17.5,5" />
                                <polyline points="12.5,5 17.5,5 17.5,10" />
                            {:else}
                                <polyline points="2,10 5.5,10 8,4.5 12,15.5 14.5,10 18,10" />
                            {/if}
                        </svg>
                        {link.label}
                    </a>
                {/each}
            </div>
        </nav>

        <main class="page">
            <slot />
        </main>
    </div>
</div>

<style lang="scss">
    :global(body) {
        margin: 0;
    }

    .pgrep {
        min-height: 100vh;
    }

    .shell {
        display: flex;
        min-height: 100vh;
        background: var(--canvas);
        color: var(--text);
    }

    .rail {
        width: 216px;
        flex: 0 0 216px;
        border-right: var(--hairline);
        display: flex;
        flex-direction: column;
        padding: 28px 16px 24px;
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

    .page {
        flex: 1 1 auto;
        min-width: 0;
    }
</style>
