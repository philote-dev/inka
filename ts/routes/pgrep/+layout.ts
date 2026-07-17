// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import type { LayoutLoad } from "./$types";
import { DIAGNOSTIC_STATUS_DEPENDENCY } from "./lib/bridge";

// pgrep runs as a client-rendered SPA inside an AnkiWebView. The root layout
// already disables SSR/prerender and sets up i18n and night mode; we restate the
// page options here so the pgrep routes are unambiguously client-only.
export const ssr = false;
export const prerender = false;

const HOME_PATH = "/pgrep";
const STATUS_TIMEOUT_MS = 1_500;

// Home's first-run decision is route data, not component side-effect state.
// SvelteKit waits for this load before committing Home and discards a stale
// result if a newer navigation wins, so the dashboard can never render first.
export const load: LayoutLoad = async ({ depends, fetch, url }) => {
    depends(DIAGNOSTIC_STATUS_DEPENDENCY);
    const isHome = url.pathname === HOME_PATH;
    if (!isHome) {
        return { isHome, diagnosticCompleted: null };
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), STATUS_TIMEOUT_MS);
    try {
        const response = await fetch("/_anki/pgrepDiagnosticStatus", {
            method: "POST",
            headers: { "Content-Type": "application/binary" },
            body: "{}",
            signal: controller.signal,
        });
        if (!response.ok) {
            throw new Error(`diagnostic status failed: ${response.status}`);
        }
        const status = (await response.json()) as { completed: boolean };
        return { isHome, diagnosticCompleted: status.completed };
    } catch {
        // Offline-first fallback: an unreadable status is treated as first run,
        // which shows the diagnostic landing instead of leaking the dashboard.
        return { isHome, diagnosticCompleted: false };
    } finally {
        clearTimeout(timeout);
    }
};
