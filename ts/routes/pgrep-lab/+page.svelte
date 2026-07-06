<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep dev lab hub. The landing that makes the separation explicit: this lab
     is a dev-only workspace, distinct from the app itself. It holds two things.
     Design decisions are read-only sandboxes that show how the look and behavior
     were chosen (component gallery, home layouts, flashcard face, math, the
     manifold). Demo control drives a live demo: inject a hypothetical account so
     the three scores light up, then sync that account desktop to mobile. The
     actual product features (Study, Home, Progress) live in the app window, not
     here. -->
<script lang="ts">
    import { LAB_PAGES } from "./LabNav.svelte";

    const decisions = LAB_PAGES.filter((p) => p.group === "decisions");
    const demo = LAB_PAGES.filter((p) => p.group === "demo");
</script>

<div class="hub">
    <header class="head">
        <h1>pgrep dev lab</h1>
        <p>
            A dev-only workspace, separate from the app itself. It holds two kinds of
            page. Design decisions are read-only sandboxes that show how the look and
            behavior were chosen. Demo control drives a live demo of the real app: inject
            a hypothetical account so the scores light up, then sync it. The actual
            product features stay in the app window.
        </p>
    </header>

    <section class="group" aria-labelledby="group-decisions">
        <div class="group-head">
            <h2 id="group-decisions">Design decisions</h2>
            <p>
                How the look and behavior were chosen. Read-only, synthetic data, no
                account touched.
            </p>
        </div>
        <div class="cards">
            {#each decisions as p (p.href)}
                <a class="card" href={p.href}>
                    <span class="card-title">{p.label}</span>
                    <span class="card-blurb">{p.blurb}</span>
                    <span class="card-go">Open</span>
                </a>
            {/each}
        </div>
    </section>

    <section class="group group--demo" aria-labelledby="group-demo">
        <div class="group-head">
            <h2 id="group-demo">Demo control</h2>
            <p>
                Drive a live demo of the real app: inject a hypothetical account so the
                scores are earned data, jump straight into the flashcards or the
                wrong-answer ladder, and sync it across devices.
            </p>
        </div>
        <div class="cards">
            {#each demo as p (p.href)}
                <a class="card card--demo" href={p.href}>
                    <span class="card-title">{p.label}</span>
                    <span class="card-blurb">{p.blurb}</span>
                    <span class="card-go">{p.app ? "Open in app \u2197" : "Open"}</span>
                </a>
            {/each}
        </div>
    </section>

    <section class="app-note">
        <span class="dot"></span>
        <p>
            Looking for the working features? The wrong-answer ladder, the flashcards,
            and the three scores live in the app window (Study, Home, Progress), not in
            the lab. Inject a demo account here first and those surfaces light up.
        </p>
    </section>
</div>

<style lang="scss">
    .hub {
        max-width: 960px;
    }

    .head {
        margin-bottom: var(--space-5);

        h1 {
            margin: 0 0 var(--space-1);
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        p {
            margin: 0;
            max-width: 72ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
        }
    }

    .group {
        margin-bottom: var(--space-5);
    }

    .group-head {
        margin-bottom: var(--space-2);

        h2 {
            margin: 0 0 4px;
            font-size: var(--text-emphasis);
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        p {
            margin: 0;
            max-width: 68ch;
            font-size: var(--text-small);
            line-height: 1.5;
            color: var(--muted);
        }
    }

    .cards {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
        gap: var(--space-2);
    }

    .card {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: var(--space-3);
        border: var(--hairline);
        border-radius: var(--radius-card);
        background: var(--surface);
        box-shadow: var(--shadow-card);
        text-decoration: none;
        color: var(--text);
        transition: var(--transition-calm);

        &:hover {
            border-color: var(--muted);
            background: var(--hover-wash);
        }
    }

    .card--demo {
        border-top: 3px solid var(--readiness);
    }

    .card-title {
        font-size: var(--text-body);
        font-weight: 600;
    }

    .card-blurb {
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
        flex: 1;
    }

    .card-go {
        margin-top: 4px;
        font-family: var(--font-mono);
        font-size: var(--text-caption);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--action-bg);
    }

    .app-note {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: var(--space-3);
        border: var(--hairline);
        border-radius: var(--radius-card);
        background: var(--elevated);

        p {
            margin: 0;
            font-size: var(--text-small);
            line-height: 1.55;
            color: var(--muted);
        }
    }

    .dot {
        width: 9px;
        height: 9px;
        margin-top: 5px;
        border-radius: 50%;
        background: var(--readiness);
        flex: 0 0 auto;
    }
</style>
