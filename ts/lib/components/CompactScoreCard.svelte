<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep CompactScoreCard. A tighter score tile for Home's three-across row: the
    fixed score glyph in its reserved hue, the label, the point number in mono
    tabular figures, and one short secondary line (a likely range, or a short
    reason when the score abstains). It keeps honesty (never a bare number) but
    drops the full missing text and link, which stay on the full ScoreCard used on
    Progress. Mirrors the iOS CompactScoreCard (mobile/ios/PgrepStudy).
-->
<script lang="ts">
    import MemoryGlyph from "./MemoryGlyph.svelte";

    export let kind: "memory" | "performance" | "readiness" = "memory";
    export let label: string | undefined = undefined;
    export let value: number | undefined = undefined;
    export let range: [number, number] | undefined = undefined;
    // A how-sure read used only as the secondary line when a real range is
    // absent, so the number never stands alone.
    export let howSure = "";
    export let abstain = false;
    // A short reason shown under the dash when abstaining (the full "what is
    // missing" text lives on the Progress ScoreCard, not here).
    export let reason = "";

    $: title = label ?? kind.charAt(0).toUpperCase() + kind.slice(1);
    $: accent = `var(--${kind}-text)`;
    $: secondary = range ? `${range[0]} to ${range[1]}` : howSure;
</script>

<section class="compact">
    <div class="head">
        <svg
            class="glyph"
            width="18"
            height="18"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            style="color: {accent}"
        >
            {#if kind === "memory"}
                <MemoryGlyph />
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
        <span class="label">{title}</span>
    </div>

    {#if abstain}
        <div class="value muted">--</div>
        <div class="secondary">{reason || "Not enough yet"}</div>
    {:else}
        <div class="value">{value}</div>
        {#if secondary}
            <div class="secondary">{secondary}</div>
        {/if}
    {/if}
</section>

<style lang="scss">
    .compact {
        display: flex;
        flex-direction: column;
        gap: 6px;
        min-width: 0;
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-row);
        padding: 14px;
        box-shadow: var(--shadow-card);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .head {
        display: flex;
        align-items: center;
        gap: 7px;
        min-width: 0;
    }

    .glyph {
        flex: 0 0 auto;
    }

    .label {
        font-size: var(--text-caption);
        font-weight: 500;
        color: var(--muted);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .value {
        font-family: var(--font-mono);
        font-size: 26px;
        font-weight: 500;
        line-height: 1;
        font-variant-numeric: tabular-nums;

        &.muted {
            color: var(--muted);
        }
    }

    .secondary {
        font-family: var(--font-mono);
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
</style>
