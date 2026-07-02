<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<script lang="ts">
    import { page } from "$app/state";

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
    <nav>
        <span class="brand">pgrep</span>
        <ul>
            {#each links as link}
                <li>
                    <a href={link.href} class:active={isActive(link.href, pathname)}>
                        {link.label}
                    </a>
                </li>
            {/each}
        </ul>
    </nav>

    <main>
        <slot />
    </main>
</div>

<style lang="scss">
    .pgrep {
        min-height: 100vh;
        color: var(--fg);
        background: var(--canvas);
    }

    nav {
        display: flex;
        gap: 1rem;
        align-items: center;
        padding: 0.5rem 1rem;
        border-bottom: 1px solid var(--border);

        ul {
            display: flex;
            gap: 0.25rem;
            margin: 0;
            padding: 0;
            list-style: none;
        }
    }

    .brand {
        font-weight: 600;
    }

    a {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        color: var(--fg);
        text-decoration: none;
        border: 1px solid transparent;
        border-radius: 6px;
        opacity: 0.7;

        &:hover {
            opacity: 1;
        }

        &.active {
            border-color: var(--border);
            opacity: 1;
        }
    }

    main {
        padding: 1rem;
    }
</style>
