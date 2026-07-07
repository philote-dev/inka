<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Shared pgrep-lab navigation. Two zones so the bar reads cleanly on camera:
     "Design decisions" is a collapsible group of read-only sandboxes (how the
     look and behavior were chosen), tucked away by default. "Demo control" is an
     always-visible tab strip named for the actual features you demo: the stats
     injector (a lab page) plus direct jumps into the real app surfaces
     (Flashcards, Practice, Progress, Sync). The open/closed state of the
     decisions group is remembered. The active link is derived from the path. -->
<script lang="ts" context="module">
    export type LabGroup = "home" | "decisions" | "demo";

    export interface LabPage {
        href: string;
        label: string;
        group: LabGroup;
        // A one-line description used by the lab hub cards.
        blurb?: string;
        // True for a real app surface (not a lab page): clicking leaves the lab.
        app?: boolean;
        // Layout-heavy sandboxes opt into a wider shell; review pages stay narrow.
        wide?: boolean;
    }

    // Every entry, in nav order, grouped by purpose. The demo group mixes the
    // lab injector with direct links into the real app features being demoed.
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
            label: "Flashcard face",
            group: "decisions",
            blurb: "The Cards-door face and the MathJax renderer, raw versus typeset.",
            wide: true,
        },
        {
            href: "/pgrep-lab/card-sets",
            label: "Card sets wheel",
            group: "decisions",
            blurb: "The Library card-sets browser: the 3D wheel and the dealt grid, both feels.",
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
            label: "Demo profile",
            group: "demo",
            blurb: "Inject a hypothetical account so the scores light up, then sync it.",
        },
        {
            href: "/pgrep/study?door=cards",
            label: "Flashcards",
            group: "demo",
            app: true,
            blurb: "The real Cards door on the FSRS review loop.",
        },
        {
            href: "/pgrep/study?door=problems",
            label: "Practice",
            group: "demo",
            app: true,
            blurb: "The wrong-answer ladder: commit, then nudge, break down, sibling, reveal.",
        },
        {
            href: "/pgrep/progress",
            label: "Progress",
            group: "demo",
            app: true,
            blurb: "The three scores with ranges, calibration, and coverage.",
        },
        {
            href: "/pgrep/settings",
            label: "Sync",
            group: "demo",
            app: true,
            blurb: "Sign in to the account and sync desktop to mobile.",
        },
    ];

    export const GROUP_LABELS: Record<Exclude<LabGroup, "home">, string> = {
        decisions: "Design decisions",
        demo: "Demo control",
    };
</script>

<script lang="ts">
    import { onMount } from "svelte";
    import { page } from "$app/stores";

    // Optional override. When unset, the active page is read from the path so a
    // caller can drop in <LabNav /> with no wiring.
    export let active: string | undefined = undefined;

    const STORAGE_KEY = "pgrep-lab.decisionsOpen";

    const decisions = LAB_PAGES.filter((p) => p.group === "decisions");
    const demo = LAB_PAGES.filter((p) => p.group === "demo");

    // Collapsed by default; the choice is remembered across visits.
    let decisionsOpen = false;

    onMount(() => {
        try {
            decisionsOpen = localStorage.getItem(STORAGE_KEY) === "1";
        } catch {
            // No storage (or blocked): keep the collapsed default.
        }
    });

    function toggleDecisions(): void {
        decisionsOpen = !decisionsOpen;
        try {
            localStorage.setItem(STORAGE_KEY, decisionsOpen ? "1" : "0");
        } catch {
            // Ignore storage failures; the toggle still works for this session.
        }
    }

    function normalize(path: string): string {
        return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
    }

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

    <div class="lab-nav__group lab-nav__group--collapsible">
        <button
            type="button"
            class="lab-nav__toggle"
            class:is-open={decisionsOpen}
            aria-expanded={decisionsOpen}
            on:click={toggleDecisions}
        >
            <span class="lab-nav__group-label">{GROUP_LABELS.decisions}</span>
            <span class="lab-nav__caret" aria-hidden="true">▾</span>
        </button>
        {#if decisionsOpen}
            <div class="lab-nav__links">
                {#each decisions as p (p.href)}
                    <a
                        class="lab-nav__link"
                        class:is-active={normalize(p.href) === current}
                        href={p.href}
                        aria-current={normalize(p.href) === current
                            ? "page"
                            : undefined}
                    >
                        {p.label}
                    </a>
                {/each}
            </div>
        {/if}
    </div>

    <div class="lab-nav__group lab-nav__group--demo" aria-label={GROUP_LABELS.demo}>
        <span class="lab-nav__group-label">{GROUP_LABELS.demo}</span>
        <div class="lab-nav__links">
            {#each demo as p (p.href)}
                <a
                    class="lab-nav__link"
                    class:is-active={normalize(p.href) === current}
                    class:is-app={p.app}
                    href={p.href}
                    aria-current={normalize(p.href) === current ? "page" : undefined}
                >
                    {p.label}
                    {#if p.app}<span class="lab-nav__ext" aria-hidden="true">
                            ↗
                        </span>{/if}
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

    .lab-nav__group--collapsible {
        padding-left: 4px;
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

    .lab-nav__toggle {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        appearance: none;
        border: 0;
        background: transparent;
        color: var(--muted);
        font: inherit;
        padding: 6px 12px;
        border-radius: var(--radius-pill);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            background: var(--hover-wash);
            color: var(--text);
        }
    }

    .lab-nav__caret {
        font-size: 10px;
        transition: transform 160ms var(--ease-spring, ease);
    }

    .lab-nav__toggle.is-open .lab-nav__caret {
        transform: rotate(180deg);
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
        display: inline-flex;
        align-items: center;
        gap: 4px;
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

    .lab-nav__ext {
        font-size: 11px;
        opacity: 0.7;
    }
</style>
