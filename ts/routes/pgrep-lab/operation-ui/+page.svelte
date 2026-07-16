<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Durable review fixtures for pgrep's replacement sync/export chrome. -->
<script lang="ts">
    import OperationCenter from "$lib/components/OperationCenter.svelte";
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

    const THEMES = [
        { label: "Light", className: "" },
        { label: "Dark", className: "night-mode" },
    ];

    async function noop(): Promise<void> {}
</script>

<header class="head">
    <h1>Operation UI</h1>
    <p>Sync and export progress, decisions, and failures — no native dialogs.</p>
</header>

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

    .head p {
        max-width: 760px;
        margin: var(--space-1) 0 0;
        color: var(--muted);
        line-height: 1.6;
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

    .theme-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--space-2);
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

    @media (max-width: 800px) {
        .theme-grid {
            grid-template-columns: 1fr;
        }
    }
</style>
