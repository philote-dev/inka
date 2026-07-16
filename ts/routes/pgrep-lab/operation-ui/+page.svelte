<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Durable review fixtures for pgrep's replacement sync/export chrome. -->
<script lang="ts">
    import OperationCenter from "$lib/components/OperationCenter.svelte";
    import OperationStateMark, {
        type ActivityVariant,
        type MarkPhase,
    } from "$lib/components/OperationStateMark.svelte";
    import type {
        OperationDecision,
        OperationKind,
        OperationPhase,
        OperationSnapshot,
    } from "../../pgrep/lib/operation";

    interface Fixture {
        label: string;
        snapshot: OperationSnapshot;
        tall?: boolean;
    }

    interface VariantCard {
        id: ActivityVariant;
        title: string;
        blurb: string;
    }

    function snapshot(
        operationId: number,
        kind: OperationKind,
        phase: OperationPhase,
        message: string,
        options: Partial<OperationSnapshot> = {},
    ): OperationSnapshot {
        return {
            revision: operationId,
            operation_id: operationId,
            kind,
            phase,
            message,
            detail: null,
            progress: null,
            cancellable: false,
            decision: null,
            dismiss_after_ms: null,
            ...options,
        };
    }

    const mandatoryDownload: OperationDecision = {
        title: "Download your collection?",
        body: "This device has no cards yet.",
        choices: [
            { id: "download", label: "Download", destructive: true },
            { id: "cancel", label: "Cancel", destructive: false },
        ],
    };

    const mandatoryUpload: OperationDecision = {
        title: "Upload this collection?",
        body: "Your account has no cards yet.",
        choices: [
            { id: "upload", label: "Upload", destructive: true },
            { id: "cancel", label: "Cancel", destructive: false },
        ],
    };

    const conflict: OperationDecision = {
        title: "Which copy should we keep?",
        body: "Upload keeps this device. Download keeps your account.",
        choices: [
            { id: "upload", label: "Upload", destructive: true },
            { id: "download", label: "Download", destructive: true },
            { id: "cancel", label: "Cancel", destructive: false },
        ],
    };

    const FIXTURES: Fixture[] = [
        {
            label: "Active, indeterminate",
            snapshot: snapshot(1, "sync", "active", "Checking…", {
                cancellable: true,
            }),
        },
        {
            label: "Full download, 62%",
            snapshot: snapshot(2, "sync", "active", "Downloading…", {
                progress: 0.62,
                cancellable: true,
            }),
        },
        {
            label: "Export complete",
            snapshot: snapshot(3, "export", "success", "Export complete", {
                detail: "Saved to Downloads/pgrep-backup.colpkg",
                progress: 1,
                dismiss_after_ms: null,
            }),
        },
        {
            label: "Up to date",
            snapshot: snapshot(8, "sync", "success", "Up to date", {
                progress: 1,
                dismiss_after_ms: null,
            }),
        },
        {
            label: "Sync error",
            snapshot: snapshot(4, "sync", "error", "Sync failed", {
                detail: "Could not reach your account.",
            }),
        },
        {
            label: "Required download",
            tall: true,
            snapshot: snapshot(5, "sync", "decision", mandatoryDownload.title, {
                decision: mandatoryDownload,
            }),
        },
        {
            label: "Required upload",
            tall: true,
            snapshot: snapshot(6, "sync", "decision", mandatoryUpload.title, {
                decision: mandatoryUpload,
            }),
        },
        {
            label: "Conflict",
            tall: true,
            snapshot: snapshot(7, "sync", "decision", conflict.title, {
                decision: conflict,
            }),
        },
    ];

    const VARIANTS: VariantCard[] = [
        {
            id: "orbit",
            title: "Orbit",
            blurb: "Sized dots on a ring; the whole ring turns. Closest to the reference.",
        },
        {
            id: "cascade",
            title: "Cascade",
            blurb: "Seats stay put; each dot pulses large→small around the circle.",
        },
        {
            id: "soft",
            title: "Soft",
            blurb: "Six dots, slower orbit, gentler falloff — quieter for long waits.",
        },
    ];

    const THEMES = [
        { label: "Light", className: "" },
        { label: "Dark", className: "night-mode" },
    ];

    // One phase per variant for the interactive picker.
    let phases: Record<ActivityVariant, MarkPhase> = {
        orbit: "active",
        cascade: "active",
        soft: "active",
    };

    // Which spinner OperationCenter fixtures use below.
    let fixtureVariant: ActivityVariant = "orbit";

    function setPhase(id: ActivityVariant, phase: MarkPhase): void {
        phases = { ...phases, [id]: phase };
    }

    function play(id: ActivityVariant, phase: MarkPhase): void {
        setPhase(id, "active");
        // Let the dots show briefly so the collapse reads as a transition.
        setTimeout(() => setPhase(id, phase), 700);
    }

    async function noop(): Promise<void> {}
</script>

<header class="head">
    <h1>Operation UI</h1>
    <p>
        Sync and export progress, decisions, and failures — no native dialogs. Pick an
        activity mark below; fixtures under it use the same choice.
    </p>
</header>

<section class="fixture-section">
    <h2>Activity marks</h2>
    <p class="section-lead">
        Working state uses circle dots of different sizes. Success and error collapse the
        ring, then draw a check or X. Product currently defaults to <strong>Orbit</strong>.
    </p>
    <div class="variant-grid">
        {#each VARIANTS as card (card.id)}
            <article class="variant-card" class:selected={fixtureVariant === card.id}>
                <div class="variant-head">
                    <div>
                        <h3>{card.title}</h3>
                        <p>{card.blurb}</p>
                    </div>
                    <button
                        class="use-btn"
                        type="button"
                        class:on={fixtureVariant === card.id}
                        on:click={() => (fixtureVariant = card.id)}
                    >
                        {fixtureVariant === card.id ? "In use" : "Use below"}
                    </button>
                </div>
                <div class="theme-grid compact">
                    {#each THEMES as theme (theme.label)}
                        <div class="pgrep theme-frame mark-frame {theme.className}">
                            <div class="theme-label">{theme.label}</div>
                            <div class="mark-stage">
                                <OperationStateMark
                                    phase={phases[card.id]}
                                    variant={card.id}
                                />
                                <span class="phase-label">{phases[card.id]}</span>
                            </div>
                        </div>
                    {/each}
                </div>
                <div class="play-row">
                    <button type="button" on:click={() => setPhase(card.id, "active")}>
                        Working
                    </button>
                    <button type="button" on:click={() => play(card.id, "success")}>
                        → Check
                    </button>
                    <button type="button" on:click={() => play(card.id, "error")}>
                        → X
                    </button>
                    <button type="button" on:click={() => play(card.id, "cancelled")}>
                        → Cancelled
                    </button>
                </div>
            </article>
        {/each}
    </div>
</section>

{#each FIXTURES as fixture (fixture.label)}
    <section class="fixture-section">
        <h2>{fixture.label}</h2>
        <div class="theme-grid">
            {#each THEMES as theme (theme.label)}
                <div
                    class="pgrep theme-frame {theme.className}"
                    class:tall={fixture.tall}
                >
                    <div class="theme-label">{theme.label}</div>
                    <OperationCenter
                        operation={fixture.snapshot}
                        activityVariant={fixtureVariant}
                        onResolve={noop}
                        onCancel={noop}
                        onDismiss={noop}
                        embedded
                    />
                </div>
            {/each}
        </div>
    </section>
{/each}

<style lang="scss">
    .head {
        margin: var(--space-4) 0;
    }

    .head h1 {
        margin: 0;
        font-size: 32px;
    }

    .head p,
    .section-lead {
        max-width: 760px;
        margin: var(--space-1) 0 0;
        color: var(--muted);
        line-height: 1.6;
    }

    .section-lead {
        margin-bottom: var(--space-2);
    }

    .fixture-section {
        margin-top: var(--space-4);
    }

    .fixture-section h2 {
        margin: 0 0 var(--space-2);
        font-family: var(--font-mono);
        font-size: var(--text-small);
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .variant-grid {
        display: grid;
        gap: var(--space-2);
    }

    .variant-card {
        padding: var(--space-2);
        border: var(--hairline);
        border-radius: var(--radius-frame);
        background: var(--surface);
    }

    .variant-card.selected {
        border-color: var(--text);
    }

    .variant-head {
        display: flex;
        flex-wrap: wrap;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: var(--space-2);
    }

    .variant-head h3 {
        margin: 0;
        font-size: var(--text-body);
        font-weight: 600;
    }

    .variant-head p {
        max-width: 42ch;
        margin: 4px 0 0;
        color: var(--muted);
        font-size: var(--text-small);
        line-height: 1.45;
    }

    .use-btn,
    .play-row button {
        min-height: 32px;
        padding: 0 12px;
        border: var(--hairline);
        border-radius: var(--radius-control);
        background: transparent;
        color: var(--text);
        cursor: pointer;
        font: inherit;
        font-size: var(--text-small);
    }

    .use-btn.on {
        border-color: var(--text);
        font-weight: 600;
    }

    .play-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: var(--space-2);
    }

    .play-row button:hover,
    .use-btn:hover {
        border-color: var(--text);
    }

    .theme-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--space-2);
    }

    .theme-grid.compact {
        gap: 8px;
    }

    .theme-frame {
        position: relative;
        min-height: 150px;
        padding: 52px var(--space-2) var(--space-2);
        overflow: hidden;
        border: var(--hairline);
        border-radius: var(--radius-frame);
        background: var(--canvas);
        color: var(--text);
    }

    .theme-frame.tall {
        min-height: 320px;
    }

    .theme-frame.mark-frame {
        min-height: 112px;
        display: grid;
        place-items: center;
        padding-top: 40px;
    }

    .theme-label {
        position: absolute;
        top: 18px;
        left: 18px;
        color: var(--muted);
        font-family: var(--font-mono);
        font-size: var(--text-caption);
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .mark-stage {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 10px;
    }

    .phase-label {
        color: var(--muted);
        font-family: var(--font-mono);
        font-size: var(--text-caption);
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    @media (max-width: 800px) {
        .theme-grid {
            grid-template-columns: 1fr;
        }
    }
</style>
