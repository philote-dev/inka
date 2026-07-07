<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Shared pgrep-lab navigation. One segmented switcher: Home, Design, Demo.
     Home is a plain link to the hub. Design and Demo are the two content zones;
     selecting one slides the indicator and opens a tray of its links. The tray
     auto-follows the current route, so a sandbox page opens with its siblings
     already shown. The active section is derived from the path. -->
<script lang="ts" context="module">
    export type LabGroup = "home" | "design" | "demo";
    export type LabZone = Exclude<LabGroup, "home">;

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

    // Every entry, in nav order, grouped by zone. The demo zone mixes the lab
    // injector with direct links into the real app features being demoed.
    export const LAB_PAGES: LabPage[] = [
        { href: "/pgrep-lab", label: "Home", group: "home" },
        {
            href: "/pgrep-lab/manifold",
            label: "Manifold",
            group: "design",
            blurb: "The readiness surface end to end: live-editable data, 3D and 2D render, hue schemes across a journey, and the color/label controls.",
            wide: true,
        },
        {
            href: "/pgrep-lab/gallery",
            label: "Gallery",
            group: "design",
            blurb: "Every primitive in its key states, light and dark, including the card face and math typesetting.",
            wide: true,
        },
        {
            href: "/pgrep-lab/card-sets",
            label: "Card sets",
            group: "design",
            blurb: "The Library card-sets wheel as a live playground: tune the geometry and spring, replay the deal, force reduced motion.",
            wide: true,
        },
        {
            href: "/pgrep-lab/calibration",
            label: "Calibration",
            group: "design",
            blurb: "The first-run calibration walkthrough end to end: author one card per subtopic to completion, then the card sets deal in.",
            wide: true,
        },
        {
            href: "/pgrep-lab/demo",
            label: "Profile",
            group: "demo",
            blurb: "Inject a hypothetical account so the scores light up, then sync it.",
        },
        {
            href: "/pgrep-lab/tutor",
            label: "Tutor",
            group: "demo",
            wide: true,
            blurb: "Run the decomposition tutor on any problem, with live AI grading.",
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
            blurb: "The real Problems door: commit, then the gated decomposition tutor on a miss.",
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

    export const ZONE_LABELS: Record<LabZone, string> = {
        design: "Design",
        demo: "Demo",
    };
</script>

<script lang="ts">
    import { onMount } from "svelte";
    import { slide } from "svelte/transition";
    import { page } from "$app/stores";

    // Optional override. When unset, the active section is read from the path so a
    // caller can drop in <LabNav /> with no wiring.
    export let active: string | undefined = undefined;

    const design = LAB_PAGES.filter((p) => p.group === "design");
    const demo = LAB_PAGES.filter((p) => p.group === "demo");

    const SECTIONS: { id: LabGroup; label: string; href?: string }[] = [
        { id: "home", label: "Home", href: "/pgrep-lab" },
        { id: "design", label: ZONE_LABELS.design },
        { id: "demo", label: ZONE_LABELS.demo },
    ];

    function normalize(path: string): string {
        return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
    }

    function sectionOf(path: string): LabGroup {
        if (path === "/pgrep-lab") {
            return "home";
        }
        return LAB_PAGES.find((p) => normalize(p.href) === path)?.group ?? "home";
    }

    // Which tray is open. Follows the route on each navigation, but can be toggled
    // by hand while you stay on a page.
    let openTray: LabZone | null = null;
    let lastPath: string | null = null;

    let reducedMotion = false;
    onMount(() => {
        reducedMotion =
            window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    });

    function toggle(id: LabZone): void {
        openTray = openTray === id ? null : id;
    }

    $: current = normalize(active ?? $page.url.pathname);
    $: routeSection = sectionOf(current);
    // Reset the tray to match the section whenever the route changes.
    $: if (current !== lastPath) {
        lastPath = current;
        openTray = routeSection === "home" ? null : (routeSection as LabZone);
    }
    // The indicator sits on the open tray, falling back to where you actually are.
    $: activeSeg = openTray ?? routeSection;
    $: segIndex = SECTIONS.findIndex((s) => s.id === activeSeg);
    // Only read while a tray is open (guarded in markup), so demo-or-design is enough.
    $: trayPages = openTray === "demo" ? demo : design;
</script>

<nav class="labnav" aria-label="Lab navigation">
    <div class="labnav__bar">
        <span class="labnav__mark">
            pgrep
            <span class="labnav__slash">/</span>
            lab
        </span>

        <div class="switch" style="--seg: {segIndex}">
            <span class="switch__indicator" aria-hidden="true"></span>
            {#each SECTIONS as s (s.id)}
                {#if s.href}
                    <a
                        class="switch__seg"
                        class:is-active={activeSeg === s.id}
                        href={s.href}
                        aria-current={current === s.href ? "page" : undefined}
                    >
                        {s.label}
                    </a>
                {:else}
                    <button
                        type="button"
                        class="switch__seg"
                        class:is-active={activeSeg === s.id}
                        aria-expanded={openTray === s.id}
                        on:click={() => toggle(s.id as LabZone)}
                    >
                        {s.label}
                    </button>
                {/if}
            {/each}
        </div>
    </div>

    {#if openTray}
        <div class="tray" transition:slide={{ duration: reducedMotion ? 0 : 200 }}>
            {#each trayPages as p (p.href)}
                <a
                    class="tray__link"
                    class:is-active={normalize(p.href) === current}
                    class:is-app={p.app}
                    href={p.href}
                    aria-current={normalize(p.href) === current ? "page" : undefined}
                >
                    {p.label}
                    {#if p.app}<span class="tray__ext" aria-hidden="true">↗</span>{/if}
                </a>
            {/each}
        </div>
    {/if}
</nav>

<style lang="scss">
    .labnav {
        margin-bottom: var(--space-3);
    }

    .labnav__bar {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--space-1) var(--space-2);
    }

    .labnav__mark {
        font-family: var(--font-mono);
        font-size: var(--text-small);
        font-weight: 500;
        letter-spacing: 0.02em;
        color: var(--muted);
        white-space: nowrap;
    }

    .labnav__slash {
        opacity: 0.5;
        margin: 0 1px;
    }

    /* Segmented switcher: three equal columns with one sliding indicator. */
    .switch {
        position: relative;
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        padding: 4px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        background: var(--surface);
    }

    .switch__indicator {
        position: absolute;
        top: 4px;
        bottom: 4px;
        left: 4px;
        width: calc((100% - 8px) / 3);
        border-radius: var(--radius-pill);
        background: var(--action-bg);
        transform: translateX(calc(var(--seg, 0) * 100%));
        transition: transform var(--duration-calm) var(--ease-spring);
    }

    .switch__seg {
        position: relative;
        z-index: 1;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        appearance: none;
        border: 0;
        background: transparent;
        min-width: 72px;
        padding: 6px 16px;
        border-radius: var(--radius-pill);
        font: inherit;
        font-size: var(--text-small);
        font-weight: 500;
        color: var(--muted);
        text-decoration: none;
        white-space: nowrap;
        cursor: pointer;
        transition: color var(--duration-calm) var(--ease-spring);

        &:hover {
            color: var(--text);
        }

        &.is-active {
            color: var(--action-fg);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
        }
    }

    .tray {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        margin-top: var(--space-1);
    }

    .tray__link {
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

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
        }
    }

    .tray__ext {
        font-size: 11px;
        opacity: 0.7;
    }

    @media (prefers-reduced-motion: reduce) {
        .switch__indicator {
            transition: none;
        }
    }
</style>
