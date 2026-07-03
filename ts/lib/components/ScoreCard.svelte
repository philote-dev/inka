<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep ScoreCard. The honesty anatomy is baked in: number, likely range,
    how sure, and last updated, or an honest abstain state that names what is
    missing. The reserved score hue appears only on the glyph and sparkline.
    Ported from the Claude Design export (design/ux-foundation.md).
-->
<script lang="ts">
    export let kind: "memory" | "performance" | "readiness" = "memory";
    export let label: string | undefined = undefined;
    export let value: number | undefined = undefined;
    export let range: [number, number] | undefined = undefined;
    export let howSure = "";
    export let updated = "Updated 2h ago";
    export let sparkline: number[] | undefined = undefined;
    export let abstain:
        | { message?: string; missing?: string; linkLabel?: string; linkHref?: string }
        | undefined = undefined;

    $: title = label ?? kind.charAt(0).toUpperCase() + kind.slice(1);
    $: accent = `var(--${kind}-text)`;

    function sparkPoints(points: number[]): string {
        return points
            .map((v, i) => `${(i / (points.length - 1)) * 62},${20 - v * 16}`)
            .join(" ");
    }
</script>

<section class="score-card">
    <div class="head">
        <div class="title">
            <svg
                width="20"
                height="20"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
                style="color: {accent}"
            >
                {#if kind === "memory"}
                    <polyline points="3,10 10,6.5 17,10" />
                    <polyline points="3,13.5 10,10 17,13.5" />
                    <polygon points="10,3 14,5.2 10,7.4 6,5.2" />
                {:else if kind === "performance"}
                    <circle cx="10" cy="10" r="7" />
                    <circle cx="10" cy="10" r="3.5" />
                    <circle cx="10" cy="10" r="0.8" fill="currentColor" stroke="none" />
                {:else}
                    <path d="M3.5 13.5 a6.5 6.5 0 0 1 13 0" />
                    <line x1="10" y1="13.5" x2="13.5" y2="8.5" />
                    <circle cx="10" cy="13.5" r="1" fill="currentColor" stroke="none" />
                {/if}
            </svg>
            <span>{title}</span>
        </div>
        {#if !abstain && sparkline && sparkline.length}
            <svg width="62" height="22" viewBox="0 0 62 22" fill="none">
                <polyline
                    points={sparkPoints(sparkline)}
                    stroke={accent}
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    opacity="0.9"
                />
            </svg>
        {/if}
    </div>

    {#if abstain}
        <div class="abstain-msg">{abstain.message ?? "Not enough evidence yet"}</div>
        {#if abstain.missing}
            <p class="abstain-missing">{abstain.missing}</p>
        {/if}
        {#if abstain.linkHref}
            <a class="abstain-link" href={abstain.linkHref}>
                {abstain.linkLabel ?? "See what is missing"}
            </a>
        {:else if abstain.linkLabel}
            <button type="button" class="abstain-link">
                {abstain.linkLabel}
            </button>
        {/if}
    {:else}
        <div class="value">{value}</div>
        {#if range}
            <div class="range">Likely {range[0]} to {range[1]}</div>
        {/if}
        <div class="foot">
            <span class="how-sure">{howSure}</span>
            <span class="updated">{updated}</span>
        </div>
    {/if}
</section>

<style lang="scss">
    .score-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 20px;
        box-shadow: var(--shadow-card);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 14px;
    }

    .title {
        display: flex;
        align-items: center;
        gap: 10px;

        span {
            font-size: 13px;
            font-weight: 500;
            color: var(--muted);
        }
    }

    .value {
        font-family: var(--font-mono);
        font-size: var(--text-score);
        font-weight: 500;
        line-height: 1;
        font-variant-numeric: tabular-nums;
    }

    .range {
        font-family: var(--font-mono);
        font-size: 13px;
        color: var(--muted);
        margin-top: 8px;
        font-variant-numeric: tabular-nums;
    }

    .foot {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: 14px;
        padding-top: 12px;
        border-top: 1px solid var(--border);
    }

    .how-sure {
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .updated {
        font-size: 12px;
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .abstain-msg {
        font-size: 16px;
        font-weight: 600;
    }

    .abstain-missing {
        margin: 8px 0 0;
        font-size: 13px;
        line-height: 1.5;
        color: var(--muted);
    }

    .abstain-link {
        display: inline-block;
        margin-top: 12px;
        padding: 0;
        border: none;
        background: none;
        font: inherit;
        font-size: 13px;
        color: var(--text);
        text-decoration: underline;
        text-underline-offset: 3px;
        cursor: pointer;
    }
</style>
