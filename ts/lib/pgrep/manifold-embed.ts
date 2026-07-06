// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// Standalone entry that hosts the pgrep 3D knowledge manifold inside a WKWebView
// on the native iOS Home. It reuses the exact Three.js renderer the desktop web
// Home uses (createManifold3D in manifold3d.ts) over the same data-driven
// Surface model, so the phone shows the real WebGL manifold rather than a 2D
// fallback. The native side builds the Surface from the synced scores and calls
// window.pgrepManifold.render({...}). esbuild bundles this together with Three.js
// into a single classic script (no ES-module imports, so file:// loading in
// WKWebView never trips CORS); see tools/build-manifold-webview.sh.

import { createManifold3D, type Manifold3DHandle } from "./manifold3d";
import { FULL_SURFACE, type Surface } from "./manifold";

type Theme = "light" | "dark";

interface RenderPayload {
    surface?: Surface;
    theme?: Theme;
    grid?: number;
    heightScale?: number;
    autoRotate?: boolean;
    interactive?: boolean;
}

interface ManifoldApi {
    render(payload: RenderPayload): void;
}

interface HostWindow {
    webkit?: {
        messageHandlers?: Record<string, { postMessage(message: unknown): void }>;
    };
    pgrepManifold?: ManifoldApi;
}

function host(): HostWindow {
    return window as unknown as HostWindow;
}

// Report lifecycle to the native coordinator (a no-op in a plain browser).
function notify(message: unknown): void {
    try {
        host().webkit?.messageHandlers?.manifold?.postMessage(message);
    } catch {
        // Not running inside a WKWebView; nothing to notify.
    }
}

let handle: Manifold3DHandle | undefined;
let interactive = true;

function stageEl(): HTMLElement {
    let stage = document.getElementById("stage");
    if (!stage) {
        stage = document.createElement("div");
        stage.id = "stage";
        document.body.appendChild(stage);
    }
    return stage;
}

function viewport(): { width: number; height: number } {
    return {
        width: Math.max(1, window.innerWidth || document.documentElement.clientWidth),
        height: Math.max(1, window.innerHeight || document.documentElement.clientHeight),
    };
}

function render(payload: RenderPayload): void {
    const surface: Surface = payload.surface ?? FULL_SURFACE;
    const theme: Theme = payload.theme ?? "dark";
    const { width, height } = viewport();
    interactive = payload.interactive ?? interactive;

    if (!handle) {
        handle = createManifold3D(stageEl(), {
            surface,
            theme,
            grid: payload.grid ?? 72,
            heightScale: payload.heightScale ?? 1.2,
            autoRotate: payload.autoRotate ?? false,
            interactive,
            width,
            height,
        });
    } else {
        handle.resize(width, height);
        handle.update(surface, theme);
    }
    notify({ type: "rendered" });
}

window.addEventListener("resize", () => {
    if (handle) {
        const { width, height } = viewport();
        handle.resize(width, height);
    }
});

host().pgrepManifold = { render };

// Tell the native coordinator we are ready to receive a surface. It replies by
// calling window.pgrepManifold.render(...) with the live surface and theme.
notify({ type: "ready" });
