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
    import { page } from "$app/state";

    import NavRail from "$lib/components/NavRail.svelte";

    import "@fontsource-variable/inter/index.css";
    import "@fontsource-variable/jetbrains-mono/index.css";
    import "./pgrep.scss";

    $: pathname = page.url.pathname;

    // Map the route to a rail destination. Diagnostic is a flow, not a tab, so
    // it leaves no item active (the rail simply has no highlight there).
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

    $: active = activeFor(pathname);
</script>

<div class="pgrep">
    <div class="shell">
        <NavRail {active} />

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

    .page {
        flex: 1 1 auto;
        min-width: 0;
    }
</style>
