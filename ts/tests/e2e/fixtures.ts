// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { request, test as base } from "@playwright/test";

export { expect } from "@playwright/test";

// Playwright's webServer probe is a static file (favicon), which mediasrv answers
// as soon as Flask is up -- while Anki is still opening the collection. A page
// loaded in that window gets its i18n bootstrap refused ("collection not open")
// and never finishes rendering, so the first test would fail on a locator that is
// simply not there yet. Wait for a handler that needs the collection instead.
const READY_TIMEOUT_MS = 60_000;
const READY_POLL_MS = 250;

async function waitForCollection(baseURL: string): Promise<void> {
    const api = await request.newContext({ baseURL });
    try {
        const deadline = Date.now() + READY_TIMEOUT_MS;
        let status = 0;
        while (Date.now() < deadline) {
            const res = await api.post("/_anki/pgrepDiagnosticStatus", {
                headers: { "Content-Type": "application/binary" },
                data: "{}",
            });
            if (res.ok()) {
                return;
            }
            status = res.status();
            await new Promise((resolve) => setTimeout(resolve, READY_POLL_MS));
        }
        throw new Error(
            `collection was not open after ${READY_TIMEOUT_MS}ms (last status ${status})`,
        );
    } finally {
        await api.dispose();
    }
}

interface WorkerFixtures {
    collectionReady: void;
}

export const test = base.extend<object, WorkerFixtures>({
    collectionReady: [
        // Playwright reads fixture dependencies off this destructuring pattern, so
        // it has to stay a pattern even though this fixture depends on nothing.
        // eslint-disable-next-line no-empty-pattern
        async ({}, use, workerInfo) => {
            const baseURL = workerInfo.project.use.baseURL;
            if (baseURL) {
                await waitForCollection(baseURL);
            }
            await use();
        },
        { scope: "worker", auto: true },
    ],
});
