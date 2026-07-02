// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// pgrep runs as a client-rendered SPA inside an AnkiWebView. The root layout
// already disables SSR/prerender and sets up i18n and night mode; we restate the
// page options here so the pgrep routes are unambiguously client-only.
export const ssr = false;
export const prerender = false;
