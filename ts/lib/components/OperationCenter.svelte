<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Shell-level progress, decision, and error UI for pgrep desktop operations. -->
<script lang="ts" context="module">
    let nextOperationCenterId = 0;
</script>

<script lang="ts">
    import { afterUpdate, onDestroy } from "svelte";

    import type {
        OperationChoice,
        OperationSnapshot,
    } from "../../routes/pgrep/lib/operation";

    export let operation: OperationSnapshot;
    export let onResolve: (
        operationId: number,
        choice: string,
    ) => Promise<unknown> = async () => {};
    export let onCancel: (operationId: number) => Promise<unknown> = async () => {};
    export let onDismiss: (operationId: number) => Promise<unknown> = async () => {};
    export let embedded = false;

    let cancelButton: HTMLButtonElement | undefined;
    let decisionCard: HTMLDivElement | undefined;
    const componentId = nextOperationCenterId++;
    let focusedDecisionRevision = -1;
    let scheduledDismissRevision = -1;
    let dismissTimer: ReturnType<typeof setTimeout> | undefined;
    let resolving = false;

    $: visible =
        operation.operation_id !== null &&
        operation.phase !== "idle" &&
        operation.phase !== "decision";
    $: decision = operation.phase === "decision" ? operation.decision : null;
    $: decisionTitleId = `operation-decision-title-${componentId}-${operation.operation_id ?? "none"}`;
    $: decisionBodyId = `operation-decision-body-${componentId}-${operation.operation_id ?? "none"}`;

    function plainBody(body: string): string {
        return body.replaceAll("**", "").replace(/^-\s+/gm, "• ");
    }

    function cancelChoice(): OperationChoice | undefined {
        return decision?.choices.find((choice) => choice.id === "cancel");
    }

    function stateSymbol(): string {
        if (operation.phase === "success") {
            return "✓";
        }
        if (operation.phase === "error") {
            return "!";
        }
        if (operation.phase === "cancelled") {
            return "–";
        }
        return "";
    }

    async function choose(choice: string): Promise<void> {
        if (resolving || operation.operation_id === null) {
            return;
        }
        resolving = true;
        try {
            await onResolve(operation.operation_id, choice);
        } finally {
            resolving = false;
        }
    }

    function handleKeydown(event: KeyboardEvent): void {
        if (!decision) {
            return;
        }
        if (event.key === "Escape") {
            const cancel = cancelChoice();
            if (cancel && !resolving) {
                event.preventDefault();
                void choose(cancel.id);
            }
            return;
        }
        if (event.key === "Tab" && decisionCard) {
            const focusable = Array.from(
                decisionCard.querySelectorAll<HTMLButtonElement>(
                    "button:not([disabled])",
                ),
            );
            if (!focusable.length) {
                event.preventDefault();
                decisionCard.focus();
                return;
            }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }
    }

    afterUpdate(() => {
        if (decision && operation.revision !== focusedDecisionRevision) {
            focusedDecisionRevision = operation.revision;
            queueMicrotask(() => cancelButton?.focus());
        }

        if (
            (operation.phase === "success" || operation.phase === "cancelled") &&
            operation.operation_id !== null &&
            operation.dismiss_after_ms !== null &&
            operation.revision !== scheduledDismissRevision
        ) {
            scheduledDismissRevision = operation.revision;
            clearTimeout(dismissTimer);
            const operationId = operation.operation_id;
            dismissTimer = setTimeout(
                () => void onDismiss(operationId),
                operation.dismiss_after_ms,
            );
        }
    });

    onDestroy(() => clearTimeout(dismissTimer));
</script>

<svelte:window on:keydown={handleKeydown} />

{#if visible}
    <aside
        class="operation-panel"
        class:embedded
        class:error={operation.phase === "error"}
        class:success={operation.phase === "success"}
        class:cancelled={operation.phase === "cancelled"}
        role={operation.phase === "error" ? "alert" : "status"}
        aria-live={operation.phase === "error" ? "assertive" : "polite"}
        aria-atomic="true"
    >
        <div
            class="state-mark"
            class:working={operation.phase === "active"}
            aria-hidden="true"
        >
            {stateSymbol()}
        </div>
        <div class="operation-copy">
            <div class="operation-message">{operation.message}</div>
            {#if operation.detail}
                <div class="operation-detail">{operation.detail}</div>
            {/if}
            {#if operation.phase === "active"}
                <div
                    class="progress-track"
                    class:indeterminate={operation.progress === null}
                    role="progressbar"
                    aria-label={operation.message}
                    aria-valuemin="0"
                    aria-valuemax="100"
                    aria-valuenow={operation.progress === null
                        ? undefined
                        : Math.round(operation.progress * 100)}
                >
                    <span
                        style:width={operation.progress === null
                            ? undefined
                            : `${operation.progress * 100}%`}
                    ></span>
                </div>
            {/if}
        </div>
        {#if operation.phase === "active" && operation.cancellable}
            <button
                class="text-action"
                type="button"
                on:click={() =>
                    operation.operation_id !== null &&
                    void onCancel(operation.operation_id)}
            >
                Cancel
            </button>
        {:else if operation.phase === "error" || operation.phase === "success" || operation.phase === "cancelled"}
            <button
                class="icon-action"
                type="button"
                aria-label="Dismiss"
                on:click={() =>
                    operation.operation_id !== null &&
                    void onDismiss(operation.operation_id)}
            >
                ×
            </button>
        {/if}
    </aside>
{/if}

{#if decision && operation.operation_id !== null}
    <div class="decision-layer" class:embedded>
        <button
            class="decision-backdrop"
            type="button"
            tabindex="-1"
            aria-label="Cancel"
            on:click={() => {
                const cancel = cancelChoice();
                if (cancel) {
                    void choose(cancel.id);
                }
            }}
        ></button>
        <div
            bind:this={decisionCard}
            class="decision-card"
            role="dialog"
            aria-modal="true"
            aria-busy={resolving}
            tabindex="-1"
            aria-labelledby={decisionTitleId}
            aria-describedby={decisionBodyId}
        >
            <h2 id={decisionTitleId}>{decision.title}</h2>
            <p id={decisionBodyId}>{plainBody(decision.body)}</p>
            <div class="decision-actions">
                {#each decision.choices as choice (choice.id)}
                    {#if choice.id === "cancel"}
                        <button
                            bind:this={cancelButton}
                            class="decision-action cancel"
                            type="button"
                            on:click={() => void choose(choice.id)}
                        >
                            {choice.label}
                        </button>
                    {:else}
                        <button
                            class="decision-action"
                            class:destructive={choice.destructive}
                            type="button"
                            on:click={() => void choose(choice.id)}
                        >
                            {choice.label}
                        </button>
                    {/if}
                {/each}
            </div>
        </div>
    </div>
{/if}

<style lang="scss">
    .operation-panel {
        position: fixed;
        right: 24px;
        bottom: 24px;
        z-index: 42;
        display: grid;
        grid-template-columns: 28px minmax(0, 1fr) auto;
        align-items: start;
        gap: 12px;
        width: min(380px, calc(100vw - 48px));
        padding: 14px;
        border: var(--hairline);
        border-radius: var(--radius-row);
        background: var(--surface);
        color: var(--text);
        box-shadow: var(--shadow-card);
    }

    .operation-panel.error {
        border-color: var(--error);
    }

    .operation-panel.cancelled {
        border-color: var(--border);
    }

    .operation-panel.embedded {
        position: relative;
        right: auto;
        bottom: auto;
        width: 100%;
        box-sizing: border-box;
    }

    .state-mark {
        display: grid;
        place-items: center;
        width: 28px;
        height: 28px;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        color: var(--muted);
        font-size: 13px;
        font-weight: 700;
    }

    .state-mark.working::before {
        content: "";
        width: 10px;
        height: 10px;
        border: 1.5px solid var(--border);
        border-top-color: var(--text);
        border-radius: var(--radius-pill);
        animation: operation-spin 800ms linear infinite;
    }

    .error .state-mark {
        border-color: var(--error);
        color: var(--error);
    }

    .success .state-mark {
        border-color: var(--success);
    }

    .operation-copy {
        min-width: 0;
    }

    .operation-message {
        font-size: var(--text-body);
        font-weight: 600;
        line-height: 1.35;
    }

    .operation-detail {
        margin-top: 4px;
        overflow-wrap: anywhere;
        color: var(--muted);
        font-size: var(--text-small);
        line-height: 1.4;
    }

    .progress-track {
        position: relative;
        height: 2px;
        margin-top: 11px;
        overflow: hidden;
        border-radius: var(--radius-pill);
        background: var(--border);
    }

    .progress-track span {
        position: absolute;
        inset: 0 auto 0 0;
        border-radius: inherit;
        background: var(--text);
        transition: width var(--duration-calm) var(--ease-spring);
    }

    .progress-track.indeterminate span {
        width: 38%;
        animation: operation-progress 1.35s var(--ease-spring) infinite;
    }

    .text-action,
    .icon-action,
    .decision-action {
        border: var(--hairline);
        background: transparent;
        color: var(--text);
        cursor: pointer;
        font: inherit;
    }

    .text-action {
        padding: 5px 8px;
        border-radius: var(--radius-control);
        color: var(--muted);
        font-size: var(--text-small);
    }

    .icon-action {
        width: 28px;
        height: 28px;
        border-color: transparent;
        border-radius: var(--radius-pill);
        color: var(--muted);
        font-size: 20px;
        line-height: 1;
    }

    .text-action:hover,
    .icon-action:hover {
        border-color: var(--border);
        color: var(--text);
    }

    .decision-layer {
        position: fixed;
        inset: 0;
        z-index: 55;
        display: grid;
        place-items: center;
        padding: 24px;
    }

    .decision-backdrop {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
        border: 0;
        border-radius: 0;
        background: rgba(38, 38, 36, 0.42);
        box-shadow: none;
        cursor: default;
    }

    .decision-backdrop:hover,
    .decision-backdrop:focus,
    .decision-backdrop:focus-visible,
    .decision-backdrop:active {
        background: rgba(38, 38, 36, 0.42);
        border: 0;
        box-shadow: none;
    }

    .decision-layer.embedded {
        position: absolute;
    }

    .decision-card {
        position: relative;
        width: min(560px, 100%);
        padding: 28px;
        border: var(--hairline);
        border-radius: var(--radius-frame);
        background: var(--surface);
        color: var(--text);
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.28);
    }

    .decision-card h2 {
        margin: 0;
        font-size: var(--text-title);
        line-height: 1.2;
    }

    .decision-card p {
        margin: 12px 0 0;
        white-space: pre-line;
        color: var(--muted);
        font-size: var(--text-body);
        line-height: 1.5;
    }

    .decision-actions {
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 8px;
        margin-top: 24px;
    }

    .decision-action {
        min-height: 40px;
        padding: 0 15px;
        border-radius: var(--radius-control);
        font-size: var(--text-body);
        font-weight: 600;
    }

    .decision-action:hover,
    .decision-action:focus-visible {
        border-color: var(--text);
        outline: none;
    }

    .decision-action.destructive {
        border-color: var(--error);
    }

    .decision-action.cancel {
        order: -1;
        margin-right: auto;
        color: var(--muted);
    }

    button:focus-visible {
        outline: 2px solid var(--focus-ring);
        outline-offset: 2px;
    }

    @keyframes operation-spin {
        to {
            transform: rotate(360deg);
        }
    }

    @keyframes operation-progress {
        from {
            transform: translateX(-110%);
        }
        to {
            transform: translateX(370%);
        }
    }

    @media (max-width: 640px) {
        .operation-panel {
            right: 12px;
            bottom: 12px;
            width: calc(100vw - 24px);
        }

        .decision-layer {
            align-items: end;
            padding: 12px;
        }

        .decision-card {
            padding: 22px;
            border-radius: var(--radius-card);
        }

        .decision-actions {
            flex-direction: column;
        }

        .decision-action,
        .decision-action.cancel {
            order: initial;
            width: 100%;
            margin-right: 0;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .state-mark.working::before,
        .progress-track.indeterminate span {
            animation: none;
        }
    }
</style>
