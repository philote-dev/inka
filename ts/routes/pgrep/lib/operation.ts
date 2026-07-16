// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { get, writable } from "svelte/store";

import { pgrepCall } from "./bridge";

export type OperationKind = "idle" | "sync" | "export" | "message";
export type OperationPhase =
    | "idle"
    | "active"
    | "decision"
    | "success"
    | "error"
    | "cancelled";

export interface OperationChoice {
    id: string;
    label: string;
    destructive: boolean;
}

export interface OperationDecision {
    title: string;
    body: string;
    choices: OperationChoice[];
}

export interface OperationSnapshot {
    revision: number;
    operation_id: number | null;
    kind: OperationKind;
    phase: OperationPhase;
    message: string;
    detail: string | null;
    progress: number | null;
    cancellable: boolean;
    decision: OperationDecision | null;
    dismiss_after_ms: number | null;
}

export const IDLE_OPERATION: OperationSnapshot = {
    revision: 0,
    operation_id: null,
    kind: "idle",
    phase: "idle",
    message: "",
    detail: null,
    progress: null,
    cancellable: false,
    decision: null,
    dismiss_after_ms: null,
};

type PgrepCaller = <T>(fn: string, args?: unknown) => Promise<T>;

export function acceptNewer(
    current: OperationSnapshot,
    incoming: OperationSnapshot,
): OperationSnapshot {
    if (incoming.revision <= current.revision) {
        return current;
    }
    const progress = incoming.progress === null
        ? null
        : Math.min(1, Math.max(0, incoming.progress));
    return { ...incoming, progress };
}

export const operation = writable<OperationSnapshot>(IDLE_OPERATION);

export async function refreshOperation(
    call: PgrepCaller = pgrepCall,
): Promise<OperationSnapshot> {
    try {
        const incoming = await call<OperationSnapshot>("pgrepOperationStatus", {});
        operation.update((current) => acceptNewer(current, incoming));
    } catch {
        // Offline-first: a transient bridge failure does not erase the last
        // operation state or block the rest of the shell.
    }
    return get(operation);
}

export function startOperationMonitor(
    call: PgrepCaller = pgrepCall,
): () => void {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polling = false;

    const poll = async (): Promise<void> => {
        if (stopped || polling) {
            return;
        }
        polling = true;
        const current = await refreshOperation(call);
        polling = false;
        if (stopped) {
            return;
        }
        const busy = current.phase === "active" || current.phase === "decision";
        timer = setTimeout(() => void poll(), busy ? 250 : 1500);
    };

    const onChanged = (): void => {
        clearTimeout(timer);
        void poll();
    };

    window.addEventListener("pgrep-operation-changed", onChanged);
    void poll();
    return () => {
        stopped = true;
        clearTimeout(timer);
        window.removeEventListener("pgrep-operation-changed", onChanged);
    };
}

export async function resolveOperation(
    operationId: number,
    choice: string,
): Promise<boolean> {
    const result = await pgrepCall<{ ok: boolean }>("pgrepOperationResolve", {
        operation_id: operationId,
        choice,
    });
    await refreshOperation();
    return result.ok;
}

export async function cancelOperation(operationId: number): Promise<boolean> {
    const result = await pgrepCall<{ ok: boolean }>("pgrepOperationCancel", {
        operation_id: operationId,
    });
    await refreshOperation();
    return result.ok;
}

export async function dismissOperation(operationId: number): Promise<boolean> {
    const result = await pgrepCall<{ ok: boolean }>("pgrepOperationDismiss", {
        operation_id: operationId,
    });
    await refreshOperation();
    return result.ok;
}
