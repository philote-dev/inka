// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { get } from "svelte/store";
import { afterEach, expect, test, vi } from "vitest";

const KEY = "pgrep.manifoldView";

/** A minimal localStorage stand-in; `failWrites` models private mode / quota. */
function fakeStorage(seed: Record<string, string> = {}, failWrites = false) {
    const data = new Map(Object.entries(seed));
    return {
        getItem: (k: string) => data.get(k) ?? null,
        setItem: (k: string, v: string) => {
            if (failWrites) {
                throw new Error("storage unavailable");
            }
            data.set(k, v);
        },
        removeItem: (k: string) => void data.delete(k),
        read: (k: string) => data.get(k) ?? null,
    };
}

async function loadPrefs(storage: unknown) {
    vi.resetModules();
    vi.stubGlobal("localStorage", storage);
    return await import("./prefs");
}

afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
});

test("a stored view is restored", async () => {
    const { manifoldView } = await loadPrefs(fakeStorage({ [KEY]: "wire" }));
    expect(get(manifoldView)).toBe("wire");
});

test("an unrecognised stored value falls back to auto", async () => {
    const { manifoldView } = await loadPrefs(fakeStorage({ [KEY]: "hologram" }));
    expect(get(manifoldView)).toBe("auto");
});

test("no stored value means auto", async () => {
    const { manifoldView } = await loadPrefs(fakeStorage());
    expect(get(manifoldView)).toBe("auto");
});

test("a change is written back to storage", async () => {
    const storage = fakeStorage();
    const { manifoldView } = await loadPrefs(storage);

    manifoldView.set("map");

    expect(storage.read(KEY)).toBe("map");
});

test("the choice still applies for the session when storage refuses writes", async () => {
    const { manifoldView } = await loadPrefs(fakeStorage({}, true));

    manifoldView.set("wire");

    expect(get(manifoldView)).toBe("wire");
});

test("without localStorage at all the store still works", async () => {
    vi.resetModules();
    vi.stubGlobal("localStorage", undefined);
    const { manifoldView } = await import("./prefs");

    expect(get(manifoldView)).toBe("auto");
    manifoldView.set("map");
    expect(get(manifoldView)).toBe("map");
});
