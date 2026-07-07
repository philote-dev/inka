// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// Client-side pgrep view preferences. These are per-device presentation choices
// (not synced study data), so they live in localStorage rather than the
// collection: a phone can prefer the flat map while the desktop keeps the 3D
// hero. Exposed as Svelte stores so the surface and the Settings control stay in
// step. SSR/prerender safe: localStorage is only touched in the browser.

import { writable } from "svelte/store";

// How to draw the knowledge manifold:
//  - "auto": the 3D wireframe where WebGL is available and motion is allowed,
//    the flat top-down map otherwise (the small-screen / no-WebGL default).
//  - "wire": always the 3D wireframe (it still self-falls-back if WebGL dies).
//  - "map":  always the 2D top-down contour map.
export type ManifoldView = "auto" | "wire" | "map";

const MANIFOLD_VIEW_KEY = "pgrep.manifoldView";

function isManifoldView(v: string | null): v is ManifoldView {
    return v === "auto" || v === "wire" || v === "map";
}

function readManifoldView(): ManifoldView {
    if (typeof localStorage === "undefined") {
        return "auto";
    }
    const stored = localStorage.getItem(MANIFOLD_VIEW_KEY);
    return isManifoldView(stored) ? stored : "auto";
}

export const manifoldView = writable<ManifoldView>(readManifoldView());

manifoldView.subscribe((value) => {
    if (typeof localStorage === "undefined") {
        return;
    }
    try {
        localStorage.setItem(MANIFOLD_VIEW_KEY, value);
    } catch {
        // Storage can be unavailable (private mode, quota); the choice still
        // applies for this session, it just will not persist.
    }
});
