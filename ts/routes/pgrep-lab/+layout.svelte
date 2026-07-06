<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep-lab shell. Same fonts and scoped tokens as the pgrep surface. The nav
     and the page container live here (not per page) so the top bar persists across
     lab navigation with no remount flicker and one consistent width. Layout-heavy
     sandboxes opt into a wider container via the wide flag on LAB_PAGES. -->
<script lang="ts">
    import "@fontsource-variable/inter/index.css";
    import "@fontsource-variable/jetbrains-mono/index.css";
    import "../pgrep/pgrep.scss";
    import { page } from "$app/stores";
    import LabNav, { LAB_PAGES } from "./LabNav.svelte";

    function normalize(path: string): string {
        return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
    }

    $: current = normalize($page.url.pathname);
    $: wide = LAB_PAGES.find((p) => p.href === current)?.wide ?? false;
</script>

<div class="pgrep">
    <div class="lab" class:lab--wide={wide}>
        <LabNav />
        <slot />
    </div>
</div>

<style lang="scss">
    :global(body) {
        margin: 0;
    }

    .pgrep {
        min-height: 100vh;
    }

    .lab {
        max-width: 1240px;
        margin: 0 auto;
        padding: var(--space-5) var(--space-3) var(--space-6);
        background: var(--canvas);
        color: var(--text);
        min-height: 100vh;
        font-family: var(--font-ui);
    }

    .lab--wide {
        max-width: 1440px;
    }
</style>
