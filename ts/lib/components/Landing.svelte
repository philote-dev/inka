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
    export let onLater: () => void = () => {};
</script>

<section class="landing">
    <span class="mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" fill="none">
            <path
                d="M16 3.5 C22 3.5 28.5 7.5 28.5 14 C28.5 19 25 21 24 24.5 C23 27.5 20 29 16 28.5 C10.5 28 6.5 25.5 4.5 21 C2.5 16.5 3.5 10.5 7.5 7 C10 4.8 13 3.5 16 3.5 Z"
                stroke="currentColor"
                stroke-width="1.4"
            />
            <path
                d="M16 8 C20 8 24 10.5 24 14.5 C24 17.5 22 19 21.2 21.2 C20.5 23.2 18.5 24.3 16 24 C12.5 23.6 10 22 8.8 19 C7.6 16 8.2 12.5 10.6 10.3 C12.2 8.9 14 8 16 8 Z"
                stroke="currentColor"
                stroke-width="1.4"
            />
            <path
                d="M16 12.5 C18.2 12.5 20 13.8 20 15.8 C20 17.3 19 18.1 18.6 19.2 C18.2 20.2 17.2 20.8 16 20.6 C14.2 20.4 13 19.5 12.4 18 C11.8 16.5 12.1 14.8 13.3 13.7 C14.1 13 15 12.5 16 12.5 Z"
                stroke="currentColor"
                stroke-width="1.4"
            />
        </svg>
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

    svg {
        width: 56px;
        height: 56px;
        display: block;
        margin-bottom: var(--space-1);
        color: var(--text);
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
