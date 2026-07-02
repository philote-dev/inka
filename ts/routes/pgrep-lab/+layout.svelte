<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep-lab shell. Same fonts and scoped tokens as the pgrep surface. -->
<script lang="ts">
    import "@fontsource-variable/inter/index.css";
    import "@fontsource-variable/jetbrains-mono/index.css";
    import "../pgrep/pgrep.scss";
</script>

<div class="pgrep">
    <slot />
</div>

<style>
    :global(body) {
        margin: 0;
    }

    .pgrep {
        min-height: 100vh;
    }
</style>
