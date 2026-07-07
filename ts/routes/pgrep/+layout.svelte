<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep surface shell. Loads the fonts + scoped design tokens, and renders the
     shared NavRail so every surface uses one rail (no per-page duplicate). The
     rail follows ux-foundation.md section 4: Home, Study, Progress, Settings
     (Library returns at L4). Diagnostic is a first-run and re-runnable flow, so
     it is reached from Home and Progress rather than a permanent tab. -->
<script lang="ts">
    import { afterNavigate } from "$app/navigation";
    import { page } from "$app/state";
    import { onMount } from "svelte";

    import Landing from "$lib/components/Landing.svelte";
    import NavRail from "$lib/components/NavRail.svelte";
    import SplashScreen from "$lib/components/SplashScreen.svelte";
    import {
        closeRail,
        narrow,
        openRail,
        railOpen,
        resetSignal,
        setNarrow,
    } from "$lib/pgrep/nav";

    import { pgrepCall } from "./lib/bridge";

    import "@fontsource-variable/inter/index.css";
    import "@fontsource-variable/jetbrains-mono/index.css";
    import "./pgrep.scss";

    // Map the route to a rail destination. Diagnostic is a flow, not a tab, so
    // it leaves no item active (the rail simply has no highlight there). Nested
    // routes highlight their parent (for example /pgrep/study/exam -> Study).
    function activeFor(current: string): string {
        if (current.startsWith("/pgrep/study")) {
            return "Study";
        }
        if (current.startsWith("/pgrep/progress")) {
            return "Progress";
        }
        if (current.startsWith("/pgrep/library")) {
            return "Library";
        }
        if (current.startsWith("/pgrep/settings")) {
            return "Settings";
        }
        if (current.startsWith("/pgrep/diagnostic")) {
            return "";
        }
        return "Home";
    }

    let active = activeFor(page.url.pathname);
    let isHome = page.url.pathname === "/pgrep";

    // The opening splash plays once per app load. This layout mounts once per
    // webview load, not on client navigation, so it does not replay as the
    // learner moves between surfaces. It is skippable inside the component.
    let showSplash = true;

    // First-run onboarding. Until the diagnostic has been completed, Home shows a
    // landing that asks for it. null while unknown so a completed learner never
    // sees a flash, and a failed read falls open to showing it. "Maybe later"
    // hides it for the session; after that the only way in is Settings.
    let diagnosticDone: boolean | null = null;
    let landingDismissed = false;
    $: showLanding =
        !showSplash && isHome && diagnosticDone === false && !landingDismissed;

    async function loadDiagnosticStatus(): Promise<void> {
        try {
            const status = await pgrepCall<{ completed: boolean }>(
                "pgrepDiagnosticStatus",
                {},
            );
            diagnosticDone = status.completed;
        } catch {
            diagnosticDone = false;
        }
    }

    // Recompute the active rail item on every route change. afterNavigate also
    // fires on first mount, so the initial value and later client navigations
    // both track the real pathname. Entering Home re-checks the diagnostic, so
    // completing it and returning reflects at once. null while the check runs
    // keeps the landing from flashing over the real Home.
    afterNavigate(() => {
        active = activeFor(page.url.pathname);
        isHome = page.url.pathname === "/pgrep";
        // On phone the rail is an overlay drawer, so a tap on a destination should
        // dismiss it as the new surface loads, the way a mobile drawer expects.
        if ($narrow) {
            closeRail();
        }
        if (isHome) {
            diagnosticDone = null;
            void loadDiagnosticStatus();
        }
    });

    // Track phone width so the rail auto-collapses (and returns as a drawer) below
    // the 640px breakpoint, matching the responsive step-downs in _pgrep.scss.
    onMount(() => {
        const mq = window.matchMedia("(max-width: 640px)");
        const apply = (): void => setNarrow(mq.matches);
        apply();
        mq.addEventListener("change", apply);
        return () => mq.removeEventListener("change", apply);
    });

    // A generic reset for the re-clicked active tab. Stateless surfaces have no
    // in-progress state to tear down, so returning them to the top is the honest
    // default; stateful surfaces (Study) react to resetSignal themselves. Skip the
    // value seen at mount so a first paint does not scroll.
    onMount(() => {
        let first = true;
        return resetSignal.subscribe(() => {
            if (first) {
                first = false;
                return;
            }
            window.scrollTo({ top: 0 });
        });
    });

    // Apply the saved theme on every surface, not just Settings. Without this a
    // stored Dark preference reverts to Light on a fresh webview load of Home,
    // Study, Progress, or Library (only the document persists across client nav).
    onMount(async () => {
        try {
            const s = await pgrepCall<{ theme: string | null }>("pgrepSettingsGet", {});
            if (s.theme) {
                const el = document.documentElement;
                if (s.theme === "Light") {
                    el.classList.remove("night-mode");
                } else if (s.theme === "Dark") {
                    el.classList.add("night-mode");
                } else {
                    const prefersDark =
                        window.matchMedia?.("(prefers-color-scheme: dark)").matches ??
                        false;
                    el.classList.toggle("night-mode", prefersDark);
                }
            }
        } catch {
            // Leave whatever the app already shows if the read fails.
        }
    });
</script>

<div class="pgrep">
    {#if showSplash}
        <SplashScreen onDone={() => (showSplash = false)} />
    {/if}
    <div class="shell" class:rail-collapsed={!$railOpen}>
        <NavRail {active} collapsed={!$railOpen} />

        {#if $narrow && $railOpen}
            <!-- Phone-only scrim behind the drawer. A tap on the dimmed content
                 closes the rail, the standard way out of a mobile drawer. -->
            <button
                class="rail-scrim"
                type="button"
                on:click={closeRail}
                aria-label="Close sidebar"
            ></button>
        {/if}

        {#if !$railOpen}
            <!-- Restore affordances, shown only while the rail is collapsed. The
                 left-edge handle appears on hover; the top-left button is always
                 there. Both bring the rail back. -->
            <button
                class="rail-edge"
                type="button"
                on:click={openRail}
                aria-label="Show sidebar"
            >
                <span class="handle" aria-hidden="true"></span>
            </button>
            <button
                class="rail-burger"
                type="button"
                on:click={openRail}
                aria-label="Show sidebar"
            >
                <svg
                    width="18"
                    height="18"
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

        <main class="page">
            {#if showLanding}
                <Landing onLater={() => (landingDismissed = true)} />
            {:else}
                <slot />
            {/if}
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

    /* macOS product: the window uses an expanded client area under a transparent
       title bar (pgrep_host.apply_native_titlebar), so the surface fills to the
       very top. Inset it by the title-bar height so the rail and its collapsed
       controls clear the floating traffic lights. */
    :global(body.pgrep-native-titlebar) .shell {
        padding-top: 28px;
    }

    :global(body.pgrep-native-titlebar) .rail-burger {
        top: 42px;
    }

    :global(body.pgrep-native-titlebar) .rail-edge {
        top: 28px;
    }

    .page {
        flex: 1 1 auto;
        min-width: 0;
    }

    /* Restore affordances, shown only while the rail is collapsed. */
    .rail-burger {
        position: fixed;
        top: 14px;
        left: 14px;
        z-index: 30;
        width: 40px;
        height: 40px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: var(--hairline);
        border-radius: var(--radius-control);
        background: var(--surface);
        color: var(--muted);
        cursor: pointer;
        box-shadow: var(--shadow-card);
        transition: var(--transition-calm);
    }

    .rail-burger:hover {
        color: var(--text);
        border-color: var(--muted);
    }

    /* A thin left-edge zone that reveals a small centred handle on hover. */
    .rail-edge {
        position: fixed;
        left: 0;
        top: 0;
        bottom: 0;
        z-index: 25;
        width: 14px;
        display: flex;
        align-items: center;
        justify-content: flex-start;
        padding: 0;
        border: none;
        background: none;
        cursor: pointer;
    }

    /* Always faintly visible so the collapsed rail is discoverable, growing more
       prominent on hover or keyboard focus. */
    .rail-edge .handle {
        width: 4px;
        height: 48px;
        border-radius: var(--radius-pill);
        background: var(--border);
        opacity: 0.5;
        transition:
            opacity var(--duration-calm) var(--ease-spring),
            width var(--duration-calm) var(--ease-spring),
            background var(--duration-calm) var(--ease-spring);
    }

    .rail-edge:hover .handle,
    .rail-edge:focus-visible .handle {
        opacity: 1;
        width: 6px;
        background: var(--muted);
    }

    /* Phone drawer scrim: dims the content while the rail overlays it, and is
       itself the tap target that closes the drawer. */
    .rail-scrim {
        position: fixed;
        inset: 0;
        z-index: 35;
        padding: 0;
        border: none;
        background: rgba(0, 0, 0, 0.36);
        cursor: pointer;
        animation: rail-scrim-in var(--duration-calm) var(--ease-spring);
    }

    @keyframes rail-scrim-in {
        from {
            opacity: 0;
        }
        to {
            opacity: 1;
        }
    }

    /* Phone: the edge-hover handle has no meaning on touch, so the burger is the
       single, obvious way back to the rail. */
    @media (max-width: 640px) {
        .rail-edge {
            display: none;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .rail-edge .handle {
            transition: opacity 0s;
        }

        .rail-scrim {
            animation: none;
        }
    }
</style>
