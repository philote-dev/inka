<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!--
    pgrep reliability diagram for model calibration. Predicted probability against
    observed accuracy, with the perfect-calibration diagonal and a Brier score.
    With no graded predictions it draws the empty frame and abstains rather than
    inventing a curve. Ported from the Claude Design export
    (design/ux-foundation.md).
-->
<script lang="ts">
    export let points: Array<{ p: number; o: number }> = [];
    export let brier: number | null = null;
    export let read = "";
    export let tone: "memory" | "performance" = "performance";
    export let size = 220;

    const pad = 28;
    $: s = size - pad - 10;
    $: color = tone === "memory" ? "var(--memory)" : "var(--performance)";

    function px(v: number): number {
        return pad + v * s;
    }
    function py(v: number): number {
        return size - pad - v * s;
    }
    $: poly = points.map((p) => `${px(p.p)},${py(p.o)}`).join(" ");
</script>

<div class="reliability">
    <svg width={size} height={size} class="chart">
        <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(0)} stroke="var(--border)" stroke-width="1" />
        <line x1={px(0)} y1={py(0)} x2={px(0)} y2={py(1)} stroke="var(--border)" stroke-width="1" />
        <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(1)} stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 4" opacity="0.6" />
        {#if points.length > 1}
            <polyline points={poly} fill="none" stroke={color} stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        {/if}
        {#each points as p, i (i)}
            <circle cx={px(p.p)} cy={py(p.o)} r="2.5" fill={color} />
        {/each}
        <text x={px(0.5)} y={size - 8} text-anchor="middle" font-size="10" fill="var(--muted)">predicted</text>
        <text x="10" y={py(0.5)} text-anchor="middle" font-size="10" fill="var(--muted)" transform="rotate(-90 10 {py(0.5)})">observed</text>
    </svg>
    <div class="foot" style="padding-left: {pad}px;">
        {#if brier != null}<span class="brier">Brier {brier}</span>{/if}
        {#if read}<span class="read">{read}</span>{/if}
    </div>
</div>

<style lang="scss">
    .reliability {
        display: inline-block;
        font-family: var(--font-ui);
        color: var(--text);
    }

    .chart {
        display: block;
    }

    .foot {
        display: flex;
        align-items: baseline;
        gap: 10px;
        margin-top: 6px;

        .brier {
            font-family: var(--font-mono);
            font-size: 12px;
            font-variant-numeric: tabular-nums;
        }

        .read {
            font-size: 12px;
            color: var(--muted);
        }
    }
</style>
