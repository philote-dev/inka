// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { afterEach, expect, test, vi } from "vitest";

import { pgrepCall } from "./bridge";

afterEach(() => {
    vi.unstubAllGlobals();
});

function stubFetch(impl: (url: string, init: RequestInit) => unknown) {
    const spy = vi.fn(impl);
    vi.stubGlobal("fetch", spy);
    return spy;
}

test("posts to the mediasrv handler with the content type it requires", async () => {
    const fetchSpy = stubFetch(() => ({
        ok: true,
        json: async () => ({ score: 720 }),
    }));

    const out = await pgrepCall("pgrepReadinessScore", { deck: 1 });

    expect(out).toEqual({ score: 720 });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("/_anki/pgrepReadinessScore");
    expect(init.method).toBe("POST");
    // mediasrv's permission check rejects anything else.
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
        "application/binary",
    );
    expect(init.body).toBe(JSON.stringify({ deck: 1 }));
});

test("an omitted argument sends an empty object, not undefined", async () => {
    const fetchSpy = stubFetch(() => ({ ok: true, json: async () => ({}) }));

    await pgrepCall("pgrepStatus");

    expect(fetchSpy.mock.calls[0][1].body).toBe("{}");
});

test("a failure carries the status and the body text", async () => {
    stubFetch(() => ({
        ok: false,
        status: 500,
        text: async () => "collection is closed",
    }));

    await expect(pgrepCall("pgrepStatus")).rejects.toThrow(
        "500: collection is closed",
    );
});

test("an unreadable error body falls back to naming the handler", async () => {
    stubFetch(() => ({
        ok: false,
        status: 403,
        text: async () => {
            throw new Error("stream already consumed");
        },
    }));

    await expect(pgrepCall("pgrepStatus")).rejects.toThrow(
        "403: pgrep pgrepStatus failed",
    );
});
