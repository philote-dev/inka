<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep first-run gate. A two-step first screen a beta tester meets: a warm
    Welcome (brand + Beta tag + sign in or continue offline), then a Sign-in form.
    It hands off from the opening splash (SplashScreen.svelte), which already owns
    the logo moment, so neither step repeats the glyph.

    Offline-first is sacred: study and AI-off scoring never need an account, so
    Continue offline lands straight on Home with the full product. Sign-in is only
    for sync (moving your own progress between your devices), against a pre-created
    account on the beta sync server; there is no self-serve signup here.

    This is the presentational artifact. It owns the steps, fields, states, and
    styling and stays decoupled from the host: the caller passes initialUrl and two
    callbacks (onSignIn, onContinueOffline). The thin /pgrep/login route wires
    those to the real bridge; the office-beta hookup can mount the same component
    (jumping a signed-out returning user to step "signin" via initialStep) and add
    the startup routing plus the gate-dismissed persistence.

    Chrome stays monochrome by the token rule (the amber/blue/lilac hues are a
    reserved data language for the three scores, never decoration), so the Beta
    tag is a filled action-color pill rather than a colored badge.
-->
<script lang="ts">
    export let initialUrl = "http://127.0.0.1:8090/";
    // Resolve ok to let the caller navigate; return ok false with a calm message
    // to surface a failure in place. The caller owns navigation on success.
    export let onSignIn: (creds: {
        url: string;
        username: string;
        password: string;
    }) => Promise<{ ok: boolean; error?: string }> = async () => ({ ok: true });
    export let onContinueOffline: () => void = () => {};

    // "welcome" is the first-run default; the hookup can open straight on "signin"
    // for a returning-but-signed-out user.
    export let initialStep: "welcome" | "signin" = "welcome";

    // State seams so the gallery can render each state without interaction. They
    // seed the initial state once; interaction takes over from there.
    export let busy = false;
    export let error = "";
    export let advancedOpen = false;
    // Demo/gallery seeds so a fixture reads as a real filled form. The app leaves
    // both blank on first run.
    export let initialUsername = "";
    export let initialPassword = "";

    let step: "welcome" | "signin" = initialStep;
    let username = initialUsername;
    let password = initialPassword;
    let url = initialUrl;
    let submitting = busy;
    let errorMsg = error;
    let showAdvanced = advancedOpen;

    function goSignIn(): void {
        errorMsg = "";
        step = "signin";
    }

    function backToWelcome(): void {
        if (submitting) {
            return;
        }
        errorMsg = "";
        step = "welcome";
    }

    async function submit(): Promise<void> {
        if (submitting) {
            return;
        }
        if (!username.trim() || !password) {
            errorMsg = "Enter the username and password we sent you.";
            return;
        }
        submitting = true;
        errorMsg = "";
        try {
            const res = await onSignIn({
                url: url.trim(),
                username: username.trim(),
                password,
            });
            if (!res.ok) {
                errorMsg =
                    res.error || "Could not sign in. Check your details and try again.";
                submitting = false;
            }
            // On success the caller navigates away, unmounting the gate, so the
            // button stays in its signing state until then rather than flashing.
        } catch (e) {
            errorMsg = `Could not reach your account. ${e}`;
            submitting = false;
        }
    }
</script>

<section class="login-gate">
    {#if step === "welcome"}
        <div class="inner welcome" data-step="welcome">
            <h1 class="welcome-title">
                <span class="title-text">
                    Welcome to <span class="word">pgrep</span>
                </span>
                <span class="beta">Beta</span>
            </h1>
            <p class="lede">The honest way to prep for the Physics GRE.</p>

            <div class="actions">
                <button type="button" class="btn primary" on:click={goSignIn}>
                    Sign in
                </button>
                <button type="button" class="btn ghost" on:click={onContinueOffline}>
                    Continue offline
                </button>
                <p class="offline-note">
                    Everything works offline. Sign in to keep devices in sync.
                </p>
            </div>
        </div>
    {:else}
        <div class="inner signin" data-step="signin">
            <div class="signin-header">
                <button
                    type="button"
                    class="back-btn"
                    aria-label="Back to welcome"
                    on:click={backToWelcome}
                >
                    <svg
                        width="18"
                        height="18"
                        viewBox="0 0 20 20"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="1.6"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        aria-hidden="true"
                    >
                        <polyline points="12 4 6 10 12 16" />
                    </svg>
                </button>
                <h1 class="signin-title">Sign in</h1>
            </div>
            <p class="lede signin-lede">Use the username and password we sent you.</p>

            <form class="card" on:submit|preventDefault={submit}>
                <label class="field">
                    <span class="field-label">Username</span>
                    <input
                        type="text"
                        bind:value={username}
                        autocomplete="username"
                        autocapitalize="none"
                        spellcheck="false"
                        disabled={submitting}
                    />
                </label>

                <label class="field">
                    <span class="field-label">Password</span>
                    <input
                        type="password"
                        bind:value={password}
                        autocomplete="current-password"
                        disabled={submitting}
                    />
                </label>

                <button
                    type="button"
                    class="disclosure"
                    aria-expanded={showAdvanced}
                    on:click={() => (showAdvanced = !showAdvanced)}
                >
                    <span class="chev" class:open={showAdvanced} aria-hidden="true">
                        ›
                    </span>
                    Advanced
                </button>

                {#if showAdvanced}
                    <label class="field">
                        <span class="field-label">Account URL</span>
                        <input
                            class="mono"
                            type="text"
                            bind:value={url}
                            autocapitalize="none"
                            autocomplete="off"
                            spellcheck="false"
                            disabled={submitting}
                        />
                    </label>
                {/if}

                {#if errorMsg}
                    <p class="error" role="alert">{errorMsg}</p>
                {/if}

                <button type="submit" class="btn primary" disabled={submitting}>
                    {#if submitting}
                        <span class="spinner" aria-hidden="true"></span>
                    {/if}
                    {submitting ? "Signing in…" : "Sign in"}
                </button>
            </form>
        </div>
    {/if}
</section>

<style lang="scss">
    .login-gate {
        min-height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: var(--space-6) var(--space-3);
        font-family: var(--font-ui);
        color: var(--text);
        background: var(--canvas);
    }

    .inner {
        width: 100%;
        max-width: 400px;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: var(--space-0);
        animation: rise var(--duration-calm) var(--ease-spring) both;
    }

    h1 {
        margin: 0;
        font-size: var(--text-title);
        font-weight: 600;
        letter-spacing: -0.02em;
        line-height: 1.25;
    }

    /* Welcome headline: a centered flex row so the Beta pill sits vertically
       centered against the wordmark rather than floating above the baseline. */
    .welcome-title {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-wrap: wrap;
        gap: 10px;
    }

    .word {
        white-space: nowrap;
    }

    /* Beta tag: a filled pill in the action (opposing) color, high contrast
       against the canvas while staying off the reserved score hues. Sizing
       follows the badge convention (small, uppercase, tracked, full radius),
       centered inline with the text. No hover, so it is never mistaken for a
       button. */
    .beta {
        display: inline-flex;
        align-items: center;
        padding: 3px 8px;
        border-radius: var(--radius-pill);
        background: var(--action-bg);
        color: var(--action-fg);
        font-family: var(--font-mono);
        font-size: var(--text-caption);
        font-weight: 600;
        letter-spacing: 0.06em;
        line-height: 1;
        text-transform: uppercase;
    }

    .lede {
        margin: var(--space-1) 0 0;
        max-width: 34ch;
        font-size: var(--text-body);
        line-height: 1.6;
        color: var(--muted);
    }

    /* Welcome actions */
    .actions {
        margin-top: var(--space-4);
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: stretch;
        gap: var(--space-1);
    }

    .offline-note {
        margin: var(--space-1) 0 0;
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    /* Sign-in step */
    .signin {
        align-items: stretch;
        text-align: left;
    }

    /* Sign-in header: the back control is a quiet icon button to the left of the
       title (the conventional two-step nav pattern), rather than a floating
       "Back" row above the heading. */
    .signin-header {
        display: flex;
        align-items: center;
        gap: var(--space-1);
    }

    .back-btn {
        flex: 0 0 auto;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        margin-left: -6px;
        padding: 0;
        background: none;
        border: none;
        border-radius: var(--radius-pill);
        color: var(--muted);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
        }
    }

    .signin-title {
        text-align: left;
    }

    .signin-lede {
        text-align: left;
        margin-top: var(--space-0);
    }

    .card {
        margin-top: var(--space-3);
        width: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        padding: var(--space-3);
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
    }

    .field {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .field-label {
        font-size: var(--text-small);
        font-weight: 500;
        color: var(--muted);
    }

    input {
        width: 100%;
        box-sizing: border-box;
        padding: 10px 12px;
        color: var(--text);
        background: var(--elevated);
        border: var(--hairline);
        border-radius: var(--radius-control);
        font-family: var(--font-ui);
        font-size: var(--text-body);
        transition: var(--transition-calm);

        &.mono {
            font-family: var(--font-mono);
            font-size: 13px;
        }

        &:hover:not(:disabled) {
            border-color: var(--muted);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 1px;
            border-color: transparent;
        }

        &:disabled {
            opacity: 0.7;
        }
    }

    .disclosure {
        align-self: flex-start;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        margin-top: calc(-1 * var(--space-0));
        padding: 2px 0;
        background: none;
        border: none;
        color: var(--muted);
        font-family: var(--font-mono);
        font-size: var(--text-small);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
            border-radius: var(--radius-control);
        }
    }

    .chev {
        display: inline-block;
        transition: transform var(--duration-calm) var(--ease-spring);

        &.open {
            transform: rotate(90deg);
        }
    }

    .error {
        margin: 0;
        padding: 10px 12px;
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--error);
        background: var(--error-wash);
        border-radius: var(--radius-control);
    }

    .btn {
        width: 100%;
        box-sizing: border-box;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 11px 16px;
        border-radius: var(--radius-control);
        border: var(--hairline);
        background: var(--surface);
        color: var(--text);
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        cursor: pointer;
        transition: var(--transition-calm);

        &:disabled {
            cursor: default;
        }

        &:focus-visible {
            outline: 2px solid var(--focus-ring);
            outline-offset: 2px;
        }
    }

    .btn.primary {
        background: var(--action-bg);
        color: var(--action-fg);
        border-color: transparent;

        &:hover:not(:disabled) {
            background: var(--action-bg-hover);
        }

        &:disabled {
            opacity: 0.8;
        }
    }

    .btn.ghost {
        background: none;
        border-color: var(--border);
        color: var(--muted);

        /* Border and text only on hover (no wash fill), so the secondary reads
           as an outline button rather than a card lighting up. */
        &:hover:not(:disabled) {
            color: var(--text);
            border-color: var(--muted);
        }
    }

    .spinner {
        width: 14px;
        height: 14px;
        border-radius: var(--radius-pill);
        border: 2px solid currentColor;
        border-top-color: transparent;
        animation: spin 0.7s linear infinite;
    }

    @keyframes rise {
        from {
            opacity: 0;
            transform: translateY(6px);
        }
        to {
            opacity: 1;
            transform: none;
        }
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .inner {
            animation: none;
        }

        .spinner {
            animation-duration: 1.6s;
        }

        .chev {
            transition: none;
        }
    }
</style>
