<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep dev lab hub. A dev-only workspace, separate from the app. Two zones:
     Design holds read-only sandboxes (how the look and behavior were chosen);
     Demo drives a live demo of the real app (inject an account, then sync). -->
<script lang="ts">
    import { LAB_PAGES } from "./LabNav.svelte";

    const design = LAB_PAGES.filter((p) => p.group === "design");
    const demo = LAB_PAGES.filter((p) => p.group === "demo");
</script>

<div class="hub">
    <section class="group" aria-labelledby="group-design">
        <div class="group-head">
            <h2 id="group-design">Design</h2>
            <p>Read-only sandboxes. Synthetic data, nothing synced.</p>
        </div>
        <div class="cards">
            {#each design as p (p.href)}
                <a class="card card--design" href={p.href}>
                    <span class="card-title">{p.label}</span>
                    <span class="card-blurb">{p.blurb}</span>
                    <span class="card-go">Open</span>
                </a>
            {/each}
        </div>
    </section>

    <section class="group group--demo" aria-labelledby="group-demo">
        <div class="group-head">
            <h2 id="group-demo">Demo</h2>
            <p>Inject an account, jump into the real features, sync across devices.</p>
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
</div>

<style lang="scss">
    .hub {
        max-width: 960px;
    }

    .group {
        margin-bottom: var(--space-5);
    }

    .group-head {
        margin-bottom: var(--space-2);

        h2 {
            margin: 0 0 var(--space-0);
            font-size: var(--text-emphasis);
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        p {
            margin: 0;
            font-size: var(--text-small);
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

    .card--design {
        border-top: 3px solid var(--performance);
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
        margin-top: var(--space-0);
        font-family: var(--font-mono);
        font-size: var(--text-caption);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--action-bg);
    }
</style>
