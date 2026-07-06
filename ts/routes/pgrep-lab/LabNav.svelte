<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Shared pgrep-lab navigation. One canonical list of every lab page, split into
     two labeled groups so the dev lab reads clearly for a walkthrough: "Design
     decisions" (how the look and behavior were chosen) and "Demo control" (drive
     a live demo of the real app). The lab is separate from the app itself; the
     actual features live in the pgrep window. The active link is derived from the
     current path, or passed explicitly through the active prop. -->
<script lang="ts" context="module">
    export type LabGroup = "home" | "decisions" | "demo";

    export interface LabPage {
        href: string;
        label: string;
        group: LabGroup;
        // A one-line description used by the lab hub cards.
        blurb?: string;
        // Layout-heavy sandboxes opt into a wider shell; review pages stay narrow.
        wide?: boolean;
    }

    // Every page in the lab, in nav order, grouped by purpose.
    export const LAB_PAGES: LabPage[] = [
        { href: "/pgrep-lab", label: "Lab home", group: "home" },
        {
            href: "/pgrep-lab/manifold",
            label: "Manifold",
            group: "decisions",
            blurb: "The data-driven readiness surface, editable live in 3D or its 2D fallback.",
        },
        {
            href: "/pgrep-lab/gallery",
            label: "Component gallery",
            group: "decisions",
            blurb: "Every primitive in its key states, light and dark side by side.",
        },
        {
            href: "/pgrep-lab/home-layouts",
            label: "Home layouts",
            group: "decisions",
            blurb: "Responsive Home card-row options, chosen from real components.",
            wide: true,
        },
        {
            href: "/pgrep-lab/card-face",
            label: "Flashcard",
            group: "decisions",
            blurb: "The Cards-door face and the MathJax renderer, raw versus typeset.",
            wide: true,
        },
        {
            href: "/pgrep-lab/math",
            label: "Math",
            group: "decisions",
            blurb: "Physics notation typeset by the same engine the reviewer uses.",
            wide: true,
        },
        {
            href: "/pgrep-lab/demo",
            label: "Demo control",
            group: "demo",
            blurb: "Inject a hypothetical account so the scores light up, then sync it.",
        },
    ];

    export const GROUP_LABELS: Record<Exclude<LabGroup, "home">, string> = {
        decisions: "Design decisions",
        demo: "Demo control",
    };
</script>

<script lang="ts">
    import { page } from "$app/stores";

    // Optional override. When unset, the active page is read from the path so a
    // caller can drop in <LabNav /> with no wiring.
    export let active: string | undefined = undefined;

    function normalize(path: string): string {
        return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
    }

    const decisions = LAB_PAGES.filter((p) => p.group === "decisions");
    const demo = LAB_PAGES.filter((p) => p.group === "demo");

    $: current = normalize(active ?? $page.url.pathname);
</script>

<nav class="lab-nav" aria-label="Lab pages">
    <a
        class="lab-nav__home"
        class:is-active={current === "/pgrep-lab"}
        href="/pgrep-lab"
        aria-current={current === "/pgrep-lab" ? "page" : undefined}
    >
        Lab home
    </a>

    <div class="lab-nav__group" aria-label={GROUP_LABELS.decisions}>
        <span class="lab-nav__group-label">{GROUP_LABELS.decisions}</span>
        <div class="lab-nav__links">
            {#each decisions as p (p.href)}
                <a
                    class="lab-nav__link"
                    class:is-active={normalize(p.href) === current}
                    href={p.href}
                    aria-current={normalize(p.href) === current ? "page" : undefined}
                >
                    {p.label}
                </a>
            {/each}
        </div>
    </div>

    <div class="lab-nav__group lab-nav__group--demo" aria-label={GROUP_LABELS.demo}>
        <span class="lab-nav__group-label">{GROUP_LABELS.demo}</span>
        <div class="lab-nav__links">
            {#each demo as p (p.href)}
                <a
                    class="lab-nav__link"
                    class:is-active={normalize(p.href) === current}
                    href={p.href}
                    aria-current={normalize(p.href) === current ? "page" : undefined}
                >
                    {p.label}
                </a>
            {/each}
        </div>
    </div>
</nav>

<style lang="scss">
    .lab-nav {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--space-1) var(--space-2);
        margin-bottom: var(--space-3);
    }

    .lab-nav__group {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 4px 4px 4px 12px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        background: var(--surface);
    }

    .lab-nav__group--demo {
        border-color: color-mix(in srgb, var(--readiness) 45%, var(--border));
    }

    .lab-nav__group-label {
        font-size: var(--text-caption);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--muted);
        white-space: nowrap;
    }

    .lab-nav__links {
        display: inline-flex;
        flex-wrap: wrap;
        gap: 4px;
    }

    .lab-nav__home {
        padding: 6px 16px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        background: var(--surface);
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

    .lab-nav__link {
        padding: 6px 14px;
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
