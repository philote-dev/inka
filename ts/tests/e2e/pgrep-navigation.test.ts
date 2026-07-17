// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

function watchDashboardAttachments(): void {
    const state = window as typeof window & {
        __pgrepDashboardAttached?: boolean;
        __pgrepDashboardObserver?: MutationObserver;
    };
    state.__pgrepDashboardObserver?.disconnect();
    state.__pgrepDashboardAttached = document.querySelector(".main") !== null;
    const observer = new MutationObserver(() => {
        if (document.querySelector(".main")) {
            state.__pgrepDashboardAttached = true;
        }
    });
    observer.observe(document, { childList: true, subtree: true });
    state.__pgrepDashboardObserver = observer;
}

function stopDashboardWatch(): boolean {
    const state = window as typeof window & {
        __pgrepDashboardAttached?: boolean;
        __pgrepDashboardObserver?: MutationObserver;
    };
    state.__pgrepDashboardObserver?.disconnect();
    return state.__pgrepDashboardAttached === true;
}

async function mockShell(page: Page): Promise<void> {
    await page.route("**/_anki/pgrepAuthStatus", async (route) => {
        await route.fulfill({ json: { gate_dismissed: true } });
    });
    await page.route("**/_anki/pgrepSettingsGet", async (route) => {
        await route.fulfill({
            json: { sync_url: "http://127.0.0.1:8090/", theme: "Light" },
        });
    });
}

async function mockDiagnosticStatus(page: Page, completed: boolean): Promise<void> {
    await mockShell(page);
    await page.route("**/_anki/pgrepDiagnosticStatus", async (route) => {
        await route.fulfill({ json: { completed } });
    });
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve!: () => void;
    const promise = new Promise<void>((done) => {
        resolve = done;
    });
    return { promise, resolve };
}

async function holdDiagnosticStatus(
    page: Page,
    completed = false,
): Promise<{
    requested: Promise<void>;
    release: () => void;
    finished: Promise<void>;
}> {
    const requested = deferred();
    const release = deferred();
    const finished = deferred();
    await page.route("**/_anki/pgrepDiagnosticStatus", async (route) => {
        requested.resolve();
        await release.promise;
        await route.fulfill({ json: { completed } });
        finished.resolve();
    });
    return {
        requested: requested.promise,
        release: release.resolve,
        finished: finished.promise,
    };
}

test("lab Home closes an open section on the hub", async ({ page }) => {
    await page.goto("/pgrep-lab");

    const design = page.getByRole("button", { name: "Design" });
    await design.click();
    await expect(page.getByRole("link", { name: "Manifold", exact: true })).toBeVisible();

    await page.getByRole("link", { name: "Home", exact: true }).click();

    await expect(design).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByRole("link", { name: "Manifold", exact: true })).toBeHidden();
});

test("lab modified Home click leaves the open section unchanged", async ({ page }) => {
    await page.goto("/pgrep-lab");

    const design = page.getByRole("button", { name: "Design" });
    const home = page.getByRole("link", { name: "Home", exact: true });
    await design.click();

    const modifiedPagePromise = page.context().waitForEvent("page");
    await home.click({ modifiers: ["ControlOrMeta"] });
    const modifiedPage = await modifiedPagePromise;
    await expect(modifiedPage).toHaveURL(/\/pgrep-lab$/);
    await modifiedPage.close();

    const middlePagePromise = page.context().waitForEvent("page");
    await home.click({ button: "middle" });
    const middlePage = await middlePagePromise;
    await expect(middlePage).toHaveURL(/\/pgrep-lab$/);
    await middlePage.close();

    await expect(design).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("link", { name: "Manifold", exact: true })).toBeVisible();
});

test("initial Home hides its dashboard until the diagnostic landing resolves", async ({ page }) => {
    await mockDiagnosticStatus(page, false);
    await page.addInitScript(watchDashboardAttachments);
    await page.goto("/pgrep");

    const splash = page.getByRole("button", { name: "Skip intro" });
    await splash.click();
    await expect(splash).toBeHidden();
    await expect(
        page.getByRole("heading", { name: "Let's place your topics" }),
    ).toBeVisible();

    const dashboardPeeked = await page.evaluate(stopDashboardWatch);
    expect(dashboardPeeked).toBe(false);
});

test("returning Home hides its dashboard until the diagnostic landing resolves", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockShell(page);
    const diagnostic = await holdDiagnosticStatus(page);
    await page.goto("/pgrep/progress");

    const splash = page.getByRole("button", { name: "Skip intro" });
    await splash.click();
    await expect(splash).toBeHidden();
    await expect(page.getByRole("heading", { name: "Progress" })).toBeVisible();

    await page.evaluate(watchDashboardAttachments);

    const homeClick = page.getByRole("link", { name: "Home", exact: true }).click();
    await diagnostic.requested;
    await homeClick;
    diagnostic.release();
    await diagnostic.finished;
    await expect(
        page.getByRole("heading", { name: "Let's place your topics" }),
    ).toBeVisible();

    const dashboardPeeked = await page.evaluate(stopDashboardWatch);
    expect(dashboardPeeked).toBe(false);
});

test("failed Home status falls safely to the diagnostic landing", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockShell(page);
    await page.route("**/_anki/pgrepDiagnosticStatus", async (route) => {
        await route.fulfill({ status: 500, body: "unavailable" });
    });
    await page.addInitScript(watchDashboardAttachments);
    await page.goto("/pgrep");

    const splash = page.getByRole("button", { name: "Skip intro" });
    await splash.click();
    await expect(splash).toBeHidden();
    await expect(
        page.getByRole("heading", { name: "Let's place your topics" }),
    ).toBeVisible();
    expect(await page.evaluate(stopDashboardWatch)).toBe(false);
});

test("hung Home status times out without exposing the dashboard", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockShell(page);
    const requested = deferred();
    const release = deferred();
    const finished = deferred();
    let requestedAt = 0;
    await page.route("**/_anki/pgrepDiagnosticStatus", async (route) => {
        requestedAt = Date.now();
        requested.resolve();
        await release.promise;
        try {
            await route.fulfill({ json: { completed: true } });
        } catch {
            // The request was intentionally aborted by the route-load timeout.
        } finally {
            finished.resolve();
        }
    });
    await page.addInitScript(watchDashboardAttachments);

    await page.goto("/pgrep");
    await requested.promise;
    const splash = page.getByRole("button", { name: "Skip intro" });
    await splash.click();
    const elapsedMs = Date.now() - requestedAt;
    expect(elapsedMs).toBeGreaterThanOrEqual(1_000);
    expect(elapsedMs).toBeLessThan(4_000);
    release.resolve();
    await finished.promise;

    await expect(splash).toBeHidden();
    await expect(
        page.getByRole("heading", { name: "Let's place your topics" }),
    ).toBeVisible();
    expect(await page.evaluate(stopDashboardWatch)).toBe(false);
});

test("completed diagnostic opens the Home dashboard directly", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockShell(page);
    let statusRequests = 0;
    await page.route("**/_anki/pgrepDiagnosticStatus", async (route) => {
        statusRequests += 1;
        await route.fulfill({ json: { completed: true } });
    });
    await page.goto("/pgrep");

    const splash = page.getByRole("button", { name: "Skip intro" });
    await splash.click();
    await expect(splash).toBeHidden();

    await expect(page.getByRole("heading", { name: "Your knowledge map" })).toBeVisible();
    await expect(
        page.getByRole("heading", { name: "Let's place your topics" }),
    ).toHaveCount(0);
    await page.evaluate(
        () =>
            new Promise<void>((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
            }),
    );
    expect(statusRequests).toBe(1);
});

test("Home status is fetched on navigation, not stale hover preload", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockShell(page);
    let completed = false;
    let statusRequests = 0;
    await page.route("**/_anki/pgrepDiagnosticStatus", async (route) => {
        statusRequests += 1;
        await route.fulfill({ json: { completed } });
    });
    await page.goto("/pgrep/progress");

    const splash = page.getByRole("button", { name: "Skip intro" });
    await splash.click();
    await expect(splash).toBeHidden();

    const home = page.getByRole("link", { name: "Home", exact: true });
    await expect(home).toHaveAttribute("data-sveltekit-preload-data", "false");
    await home.hover();
    await page.evaluate(
        () =>
            new Promise<void>((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
            }),
    );
    expect(statusRequests).toBe(0);

    completed = true;
    await home.click();
    await expect(page.getByRole("heading", { name: "Your knowledge map" })).toBeVisible();
    expect(statusRequests).toBeGreaterThan(0);
});

test("Maybe later keeps Home open after leaving and returning", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockDiagnosticStatus(page, false);
    await page.goto("/pgrep");

    const splash = page.getByRole("button", { name: "Skip intro" });
    await splash.click();
    await expect(splash).toBeHidden();
    await page.getByRole("button", { name: "Maybe later" }).click();
    await expect(page.getByRole("heading", { name: "Your knowledge map" })).toBeVisible();

    await page.getByRole("link", { name: "Progress", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Progress" })).toBeVisible();
    await page.getByRole("link", { name: "Home", exact: true }).click();

    await expect(page.getByRole("heading", { name: "Your knowledge map" })).toBeVisible();
    await expect(
        page.getByRole("heading", { name: "Let's place your topics" }),
    ).toHaveCount(0);

    await page.reload();
    const replayedSplash = page.getByRole("button", { name: "Skip intro" });
    await replayedSplash.click();
    await expect(replayedSplash).toBeHidden();

    await expect(page.getByRole("heading", { name: "Your knowledge map" })).toBeVisible();
    await expect(
        page.getByRole("heading", { name: "Let's place your topics" }),
    ).toHaveCount(0);
});

test("an interrupted Home check cannot replace a newer route", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockShell(page);
    const diagnostic = await holdDiagnosticStatus(page);

    await page.goto("/pgrep/progress");
    const splash = page.getByRole("button", { name: "Skip intro" });
    await splash.click();
    await expect(splash).toBeHidden();

    const homeClick = page.getByRole("link", { name: "Home", exact: true }).click();
    await diagnostic.requested;
    await homeClick;
    await page.getByRole("link", { name: "Study", exact: true }).click();
    await expect(page).toHaveURL("/pgrep/study");

    diagnostic.release();
    await diagnostic.finished;
    await page.evaluate(
        () =>
            new Promise<void>((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
            }),
    );

    await expect(page).toHaveURL("/pgrep/study");
    await expect(page.getByRole("heading", { name: "Study" }).first()).toBeVisible();
    await expect(
        page.getByRole("heading", { name: "Let's place your topics" }),
    ).toHaveCount(0);
});
