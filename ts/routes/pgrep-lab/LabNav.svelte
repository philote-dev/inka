<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Shared pgrep-lab navigation. One canonical list of every lab page, rendered
     on each page so the whole lab is reachable from anywhere (the gallery is the
     Tools-menu entry point, so all six pages must hang off it). The active link
     is derived from the current path, or passed explicitly through the active
     prop. -->
<script lang="ts" context="module">
    export interface LabPage {
        href: string;
        label: string;
        // Layout-heavy sandboxes opt into a wider shell; review pages stay narrow.
        wide?: boolean;
    }

    // Every page in the lab, in nav order.
    export const LAB_PAGES: LabPage[] = [
        { href: "/pgrep-lab", label: "Manifold lab" },
        { href: "/pgrep-lab/gallery", label: "Component gallery" },
        { href: "/pgrep-lab/demo", label: "Demo profile" },
        { href: "/pgrep-lab/home-layouts", label: "Home layouts", wide: true },
        { href: "/pgrep-lab/card-face", label: "Flashcard", wide: true },
        { href: "/pgrep-lab/math", label: "Math", wide: true },
    ];
</script>

<script lang="ts">
    import { page } from "$app/stores";

    // Optional override. When unset, the active page is read from the path so a
    // caller can drop in <LabNav /> with no wiring.
    export let active: string | undefined = undefined;

    function normalize(path: string): string {
        return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
    }

    $: current = normalize(active ?? $page.url.pathname);
</script>

<nav class="lab-nav" aria-label="Lab pages">
    {#each LAB_PAGES as p (p.href)}
        <a
            class="lab-nav__link"
            class:is-active={normalize(p.href) === current}
            href={p.href}
            aria-current={normalize(p.href) === current ? "page" : undefined}
        >
            {p.label}
        </a>
    {/each}
</nav>

<style lang="scss">
    .lab-nav {
        display: inline-flex;
        flex-wrap: wrap;
        gap: 4px;
        padding: 4px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        background: var(--surface);
        margin-bottom: var(--space-3);
    }

    .lab-nav__link {
        padding: 6px 16px;
        border-radius: var(--radius-pill);
        font-size: var(--text-small);
        font-weight: 500;
        color: var(--muted);
        text-decoration: none;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
        }

        &.is-active {
            color: var(--action-fg);
            background: var(--action-bg);
        }
    }
</style>
