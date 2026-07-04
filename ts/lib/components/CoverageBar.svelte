<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep coverage bar. One segment per topic, width by blueprint weight, filled
    by how covered that topic is. Coverage gates Readiness, so the note states
    the rule plainly. Monochrome by design: coverage is not one of the three
    reserved score hues. Ported from the Claude Design export
    (design/ux-foundation.md).
-->
<script lang="ts">
    export let segments: Array<{ topic: string; weight: number; covered: number }> = [];
    export let threshold = 70;
    export let coveredPct: number | null = null;
    export let note = "";
    export let showLabels = true;

    $: total = segments.reduce((sum, x) => sum + x.weight, 0) || 1;
    $: computed = Math.round((segments.reduce((sum, x) => sum + x.weight * x.covered, 0) / total) * 100);
    $: covered = coveredPct ?? computed;
</script>

<div class="coverbar">
    <div class="head">
        <span class="pct">{covered} percent of the exam covered</span>
        <span class="gate">Readiness needs {threshold} percent</span>
    </div>
    <div class="bar" role="img" aria-label="{covered} percent of the exam covered">
        {#each segments as s (s.topic)}
            <div class="seg" style="flex: {s.weight};" title={s.topic}>
                <div class="fill" style="width: {Math.round(s.covered * 100)}%;"></div>
            </div>
        {/each}
    </div>
    {#if showLabels}
        <div class="labels" aria-hidden="true">
            {#each segments as s (s.topic)}
                <span class="lab" style="flex: {s.weight};">{s.topic}</span>
            {/each}
        </div>
    {/if}
    {#if note}
        <p class="note">{note}</p>
    {/if}
</div>

<style lang="scss">
    .coverbar {
        font-family: var(--font-ui);
        color: var(--text);
    }

    .head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 10px;

        .pct {
            font-family: var(--font-mono);
            font-size: 13px;
            font-variant-numeric: tabular-nums;
        }

        .gate {
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--muted);
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
    }

    .bar {
        display: flex;
        gap: 3px;
        height: 10px;
    }

    .seg {
        border: var(--hairline);
        border-radius: 3px;
        overflow: hidden;
        display: flex;
        min-width: 0;
    }

    .fill {
        background: var(--text);
        opacity: 0.75;
        border-radius: 2px 0 0 2px;
    }

    .labels {
        display: flex;
        gap: 3px;
        margin-top: 6px;
    }

    .lab {
        min-width: 0;
        font-size: 10px;
        color: var(--muted);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .note {
        margin: 12px 0 0;
        font-size: 12px;
        line-height: 1.5;
        color: var(--muted);
    }
</style>
