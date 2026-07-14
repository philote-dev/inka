<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep first-run sign-in route. A thin wiring layer over LoginGate: it reads
     the saved sync URL, persists it, and kicks the existing sync bridge, then
     lands on Home. Rendered as a full-screen overlay so a standalone preview at
     /pgrep/login covers the shell rail, which is also how the office-beta hookup
     can mount the gate (that hookup owns startup routing and the gate-dismissed
     flag; see docs_pgrep/plan/login-gate-beta-handoff.md).

     Success detection is optimistic for now: pgrepSync is fire-and-forget today
     (it returns "started" and Anki's own progress/error dialog handles the rest),
     so a clean kickoff is treated as success. The hookup replaces this with a
     login call that reports the real result. Offline-first is untouched:
     Continue offline never calls sync. -->
<script lang="ts">
    import { goto } from "$app/navigation";
    import { onMount } from "svelte";

    import LoginGate from "$lib/components/LoginGate.svelte";

    import { pgrepCall } from "../lib/bridge";

    let initialUrl = "http://127.0.0.1:8090/";
    // Hold the gate until the saved URL loads, so its field seeds with the real
    // value instead of flashing the default.
    let ready = false;

    onMount(async () => {
        try {
            const s = await pgrepCall<{ sync_url?: string }>("pgrepSettingsGet", {});
            if (s?.sync_url) {
                initialUrl = s.sync_url;
            }
        } catch {
            // Fall back to the default URL if settings cannot be read.
        } finally {
            ready = true;
        }
    });

    async function handleSignIn(creds: {
        url: string;
        username: string;
        password: string;
    }): Promise<{ ok: boolean; error?: string }> {
        try {
            await pgrepCall("pgrepSettingsSet", { sync_url: creds.url });
        } catch {
            // Persisting the URL is best effort; still attempt the sign-in.
        }
        try {
            await pgrepCall("pgrepSync", {
                url: creds.url,
                username: creds.username,
                password: creds.password,
            });
        } catch (e) {
            return { ok: false, error: `Could not reach the server. ${String(e)}` };
        }
        await goto("/pgrep");
        return { ok: true };
    }

    function continueOffline(): void {
        void goto("/pgrep");
    }
</script>

<div class="login-route">
    {#if ready}
        <LoginGate
            {initialUrl}
            onSignIn={handleSignIn}
            onContinueOffline={continueOffline}
        />
    {/if}
</div>

<style lang="scss">
    /* Cover the shell (rail included) so the gate reads as a first screen. Fixed
       to the viewport; tokens still resolve from the .pgrep ancestor. */
    .login-route {
        position: fixed;
        inset: 0;
        z-index: 60;
        overflow: auto;
        background: var(--canvas);
    }
</style>
