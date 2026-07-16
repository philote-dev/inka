// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { expect, test } from "vitest";

import { acceptNewer, IDLE_OPERATION, type OperationSnapshot } from "./operation";

function snapshot(
    revision: number,
    phase: OperationSnapshot["phase"],
    progress: number | null = null,
): OperationSnapshot {
    return {
        ...IDLE_OPERATION,
        revision,
        operation_id: 7,
        kind: "sync",
        phase,
        message: phase,
        progress,
    };
}

test("accepts only a newer operation revision", () => {
    const current = snapshot(4, "active");

    expect(acceptNewer(current, snapshot(3, "error"))).toBe(current);
    expect(acceptNewer(current, snapshot(4, "error"))).toBe(current);
    expect(acceptNewer(current, snapshot(5, "success")).phase).toBe("success");
});

test("clamps progress from the bridge", () => {
    expect(acceptNewer(IDLE_OPERATION, snapshot(1, "active", 1.4)).progress).toBe(1);
    expect(acceptNewer(IDLE_OPERATION, snapshot(1, "active", -0.2)).progress).toBe(0);
});

test("an equal revision cannot replace a terminal state", () => {
    const complete = snapshot(9, "success", 1);
    const lateProgress = snapshot(9, "active", 0.8);

    expect(acceptNewer(complete, lateProgress)).toBe(complete);
});

test("accepts the cancelled terminal phase", () => {
    const cancelled = snapshot(10, "cancelled");

    expect(acceptNewer(IDLE_OPERATION, cancelled).phase).toBe("cancelled");
});
