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
    import LoginGate from "$lib/components/LoginGate.svelte";
    import NavRail from "$lib/components/NavRail.svelte";
    import OperationCenter from "$lib/components/OperationCenter.svelte";
    import RailEdgePill from "$lib/components/RailEdgePill.svelte";
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
    import {
        cancelOperation,
        dismissOperation,
        operation,
        resolveOperation,
        startOperationMonitor,
    } from "./lib/operation";

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

    // The content panel is the one scroll container (the shell is a fixed frame),
    // so reset-to-top and any future scroll control target this element, not the
    // window.
    let pageEl: HTMLElement | undefined;

    // A scroll-edge shadow under the transparent title bar fades in only once the
    // content panel has scrolled, matching native titlebarSeparatorStyle instead
    // of a permanent line.
    let scrolled = false;
    function onPageScroll(): void {
        scrolled = (pageEl?.scrollTop ?? 0) > 2;
    }

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

    // First-run login gate (beta). Shown before the app when the user is neither
    // signed in nor has chosen to continue offline. "unknown" until the check
    // resolves, so the app is never rendered (and never flashes) behind the splash
    // until we know; a failed read falls open to the app, since offline-first must
    // never depend on the gate. See docs_pgrep/plan/login-gate-beta-handoff.md.
    type GateState = "unknown" | "show" | "hide";
    let gateState: GateState = "unknown";
    let gateUrl = "http://127.0.0.1:8090/";

    async function loadAuthStatus(): Promise<void> {
        try {
            const [status, settings] = await Promise.all([
                pgrepCall<{ gate_dismissed: boolean }>("pgrepAuthStatus", {}),
                pgrepCall<{ sync_url?: string }>("pgrepSettingsGet", {}),
            ]);
            if (settings?.sync_url) {
                gateUrl = settings.sync_url;
            }
            gateState = status.gate_dismissed ? "hide" : "show";
        } catch {
            gateState = "hide";
        }
    }

    async function gateSignIn(creds: {
        url: string;
        username: string;
        password: string;
    }): Promise<{ ok: boolean; error?: string }> {
        try {
            const res = await pgrepCall<{ ok: boolean; error?: string }>(
                "pgrepSignIn",
                creds,
            );
            if (res.ok) {
                gateState = "hide";
            }
            return res;
        } catch (e) {
            return { ok: false, error: `Could not reach your account. ${e}` };
        }
    }

    function gateContinueOffline(): void {
        void pgrepCall("pgrepGateSkip", {});
        gateState = "hide";
    }

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

    // Resolve the login gate before showing the app, so a first-run or signed-out
    // user meets the gate rather than Home.
    onMount(() => {
        void loadAuthStatus();
    });

    // One operation monitor owns sync/export state for every route. It polls the
    // bridge so browser-first development and the embedded webview behave the
    // same; the host event only wakes it sooner inside Qt.
    onMount(() => startOperationMonitor());

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
            pageEl?.scrollTo({ top: 0 });
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

    // Short in-app status line for legacy transient actions such as undo. Sync
    // and export use the structured OperationCenter above; host Qt redirects
    // any remaining yellow ToolTip panel through pgrep-status.
    let statusMsg = "";
    let statusTimer: ReturnType<typeof setTimeout> | undefined;

    onMount(() => {
        const onStatus = (ev: Event): void => {
            const detail = (ev as CustomEvent<{ message?: string; periodMs?: number }>)
                .detail;
            const message = detail?.message?.trim();
            if (!message) {
                return;
            }
            statusMsg = message;
            clearTimeout(statusTimer);
            statusTimer = setTimeout(() => {
                statusMsg = "";
            }, detail?.periodMs ?? 3000);
        };
        window.addEventListener("pgrep-status", onStatus);
        return () => {
            window.removeEventListener("pgrep-status", onStatus);
            clearTimeout(statusTimer);
        };
    });
</script>

<div class="pgrep">
    {#if showSplash}
        <SplashScreen onDone={() => (showSplash = false)} />
    {/if}

    {#if gateState === "show"}
        <!-- First-run gate covers the shell (rail included) until the user signs
             in or continues offline. The splash (z-index above) still plays over
             it on load. -->
        <div class="login-overlay">
            <LoginGate
                initialUrl={gateUrl}
                onSignIn={gateSignIn}
                onContinueOffline={gateContinueOffline}
            />
        </div>
    {:else if gateState === "hide"}
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

            <!-- Desktop: one edge pill travels with the rail edge and toggles
                 hide/show. Phone: a top-left burger reopens the drawer while
                 collapsed (the edge pill is desktop-only). -->
            <RailEdgePill />
            {#if !$railOpen && $narrow}
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

            <main class="page" bind:this={pageEl} on:scroll={onPageScroll}>
                <div class="scroll-edge" class:scrolled aria-hidden="true"></div>
                {#if showLanding}
                    <Landing onLater={() => (landingDismissed = true)} />
                {:else}
                    <slot />
                {/if}
            </main>

            <OperationCenter
                operation={$operation}
                onResolve={resolveOperation}
                onCancel={cancelOperation}
                onDismiss={dismissOperation}
            />

            {#if statusMsg}
                <div class="shell-status" role="status" aria-live="polite">
                    {statusMsg}
                </div>
            {/if}
        </div>
    {/if}
</div>

<style lang="scss">
    :global(body) {
        margin: 0;
    }

    .pgrep {
        height: 100dvh;
        overflow: hidden;
    }

    /* First-run gate overlay: covers the shell and rail. Below the splash
       (z-index 60) so the intro still plays over it, above everything else. */
    .login-overlay {
        position: fixed;
        inset: 0;
        z-index: 50;
        overflow: auto;
        background: var(--canvas);
    }

    .shell {
        display: flex;
        position: relative;
        height: 100%;
        min-height: 100vh;
        box-sizing: border-box;
        overflow: hidden;
        background: var(--canvas);
        color: var(--text);
    }

    /* Replaces Anki's floating yellow tooltip panel for product-path success
       messages (sync complete, export, undo). Calm, in-flow chrome. */
    .shell-status {
        position: fixed;
        left: 50%;
        bottom: 24px;
        z-index: 40;
        transform: translateX(-50%);
        max-width: min(420px, calc(100vw - 48px));
        padding: 10px 16px;
        border: var(--hairline);
        border-radius: var(--radius-control);
        background: var(--surface);
        color: var(--text);
        font-family: var(--font-ui);
        font-size: var(--text-body);
        line-height: 1.4;
        box-shadow: var(--shadow-card);
        pointer-events: none;
    }

    /* macOS product: the window uses an expanded client area under a transparent
       title bar (pgrep_host.apply_native_titlebar), so the surface fills to the
       very top. Structure (the shell and the rail divider) runs full height to
       the top edge; only the content columns are inset by the title-bar safe
       area, so the divider reaches the top and nothing collides with the
       floating traffic lights. */
    :global(body.pgrep-native-titlebar) .page {
        padding-top: var(--pgrep-titlebar-inset, 28px);
    }

    .page {
        flex: 1 1 auto;
        min-width: 0;
        overflow-y: auto;
        overscroll-behavior: contain;
    }

    /* Scroll-edge shadow: a hairline under the title-bar band that fades in only
       once the content panel has scrolled, so the top does not need a permanent
       divider. Scoped to the native title bar; the browser dev surface is
       unchanged. Pinned to the band bottom via the safe-area inset. */
    .scroll-edge {
        position: sticky;
        top: 0;
        height: 0;
        z-index: 5;
        pointer-events: none;
    }

    .scroll-edge::after {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 1px;
        background: var(--border);
        box-shadow: 0 6px 12px -6px rgba(0, 0, 0, 0.25);
        opacity: 0;
        transition: opacity var(--duration-calm) var(--ease-spring);
    }

    :global(body.pgrep-native-titlebar) .scroll-edge {
        top: var(--pgrep-titlebar-inset, 28px);
    }

    :global(body.pgrep-native-titlebar) .scroll-edge.scrolled::after {
        opacity: 1;
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

    @media (prefers-reduced-motion: reduce) {
        .rail-scrim {
            animation: none;
        }

        .scroll-edge::after {
            transition: none;
        }
    }
</style>
