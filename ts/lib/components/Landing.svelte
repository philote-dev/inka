<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep first-run landing. Shown when the diagnostic has not been completed, to
    ask the learner to place their topics. The diagnostic is a one shot, so the
    only later way in is Settings. Design tokens only, both themes.
-->
<script lang="ts">
    import PgrepMark from "$lib/components/PgrepMark.svelte";

    export let onLater: () => void = () => {};
</script>

<section class="landing">
    <span class="mark" aria-hidden="true">
        <PgrepMark size={56} />
    </span>
    <h1>Let's place your topics</h1>
    <p>
        A short diagnostic sets your starting point, so pgrep measures you honestly from
        the first day. It takes a few minutes, and you do it once.
    </p>
    <div class="actions">
        <a class="btn primary" href="/pgrep/diagnostic">Start the diagnostic</a>
        <button class="btn ghost" type="button" on:click={onLater}>Maybe later</button>
    </div>
</section>

<style lang="scss">
    .landing {
        min-height: 100%;
        max-width: 520px;
        margin: 0 auto;
        padding: 96px 24px 64px;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: var(--space-2);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .mark {
        display: block;
        margin-bottom: var(--space-1);
    }

    h1 {
        margin: 0;
        font-size: var(--text-title);
        font-weight: 600;
        letter-spacing: -0.02em;
    }

    p {
        margin: 0;
        max-width: 42ch;
        font-size: var(--text-body);
        line-height: 1.6;
        color: var(--muted);
    }

    .actions {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: var(--space-1);
        margin-top: var(--space-2);
    }

    .btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 11px 20px;
        border-radius: var(--radius-control);
        border: var(--hairline);
        background: var(--surface);
        color: var(--text);
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        text-decoration: none;
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            background: var(--hover-wash);
            border-color: var(--muted);
        }
    }

    .btn.primary {
        background: var(--action-bg);
        color: var(--action-fg);
        border-color: var(--action-bg);

        &:hover {
            background: var(--action-bg-hover);
            border-color: var(--action-bg-hover);
        }
    }

    .btn.ghost {
        background: none;
        border-color: var(--muted);
    }
</style>
