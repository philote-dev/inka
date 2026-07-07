// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// pgrep knowledge-manifold, the production 3D renderer. It consumes the exact
// same `Surface` structure as the Canvas 2D fallback (ts/lib/pgrep/manifold.ts)
// and reuses its math verbatim: `height` -> vertex displacement (up axis),
// `boundaryR` + `inHole` -> which grid cells exist (a gap is a real hole in the
// mesh, never faked), `colorAt` -> the reserved amber/lilac/blue score hue per
// region, `glows` -> the soft under-light on the floor. Three.js draws it as a
// translucent color shell under a clean wireframe. Nothing photoreal, an
// instrument readout with depth you can orbit.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { boundaryR, colorAt, FULL_SURFACE, height, type Hole, type ManifoldLabel, type Surface } from "./manifold";

// Whether to prefer the 3D hero. False on machines without WebGL so callers can
// fall back to the Canvas 2D `Manifold`. Callers should also honor
// prefers-reduced-motion themselves.
export function supportsWebGL(): boolean {
    try {
        const canvas = document.createElement("canvas");
        return !!(window.WebGLRenderingContext
            && (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")));
    } catch {
        return false;
    }
}

export interface Manifold3DOpts {
    theme?: "light" | "dark";
    surface?: Surface;
    /** Grid resolution per axis. 64 reads clean, drop to ~40 for thumbnails. */
    grid?: number;
    /** Vertical exaggeration of the height field. */
    heightScale?: number;
    /** Slow calm turntable, off by default (calm over flashy). */
    autoRotate?: boolean;
    /** Allow drag-to-orbit and scroll-to-zoom. */
    interactive?: boolean;
    /** Line + fill brightness 0..1, mirrors the 2D `glow`. */
    glow?: number;
    /** Color vibrance 0..1. 0 keeps the calm default; higher pushes saturation,
     *  keeps the wireframe lines colored instead of near-black, and fills the
     *  cells with more visible hue. */
    vibrance?: number;
    width?: number;
    height?: number;
    /** Called each frame the camera or surface moves, with topic label anchors
     *  projected to pixel space so an HTML overlay can track them. */
    onLabels?: (labels: ProjectedLabel3D[]) => void;
    /** Called with a blueprint category slug when the learner taps a topic
     *  region on the surface (ux-foundation 5, the focus-drill entry). A drag to
     *  orbit never fires this; only a genuine tap does. */
    onTopic?: (slug: string) => void;
    /** How topic labels are placed. "offset" uses the fixed per-label design
     *  offset (the original). "radial" ignores the offsets and pushes every label
     *  into the left/right gutter just outside the projected silhouette, stacked
     *  per side so labels never overlap each other or land on the surface,
     *  re-solved each frame so it follows the viewing angle. */
    labelLayout?: "offset" | "radial";
}

export interface ManifoldShapeOpts {
    grid?: number;
    heightScale?: number;
    glow?: number;
    vibrance?: number;
}

export interface ProjectedLabel3D {
    name: string;
    /** Anchor (the surface point) in pixel space. */
    ax: number;
    ay: number;
    /** Label box position in pixel space. */
    lx: number;
    ly: number;
    /** CSS transform that seats the label box relative to its point. */
    tf: string;
    /** Elbow leader polyline from the surface anchor to the label edge: a
     *  diagonal run to a knee, then a short leg into the middle of the label. */
    lead?: { x: number; y: number }[];
    /** 0..1 how much the label sits over the mesh/lines (0 fully outside the
     *  outline). Drives a subtle backing pill so an over-surface label stays
     *  readable. */
    chip?: number;
    /** Label ink, a readable tint of the region hue. */
    c: string;
    /** False when the anchor is behind the camera or off screen. */
    visible: boolean;
    /** 0..1 target opacity. The overlay eases toward it with a CSS transition so
     *  labels fade in and out (backface + zoom hide) instead of popping. Undefined
     *  means fully shown. */
    opacity?: number;
    /** Blueprint category slug, so a clicked label can launch its focus drill. */
    topic?: string;
}

export interface Manifold3DHandle {
    /** Reshape to a new surface and/or theme. Rebuilds the wireframe. */
    update(surface: Surface, theme: "light" | "dark"): void;
    /** Adjust structural look (density, exaggeration, brightness) live. */
    setShape(opts: ManifoldShapeOpts): void;
    setAutoRotate(on: boolean): void;
    setLabelLayout(mode: "offset" | "radial"): void;
    /** Orbit the camera to an absolute azimuth (and optional polar) in radians,
     *  keeping the current distance. Dev aid for reviewing labels at set angles. */
    orbitTo(azimuth: number, polar?: number): void;
    /** Set the camera distance from the target (clamped to min/max), keeping the
     *  current direction. Pull back to leave a gutter around the figure. */
    setDistance(distance: number): void;
    resize(width: number, height: number): void;
    resetView(): void;
    dispose(): void;
}

// Domain half-extent, matches the 2D renderer's rim search plus a small margin.
function domainLimit(surface: Surface): number {
    let lim = 0;
    for (let k = 0; k < 72; k++) {
        lim = Math.max(lim, boundaryR(surface, (k / 72) * Math.PI * 2));
    }
    return lim + 0.06;
}

// Inside the blob outline only (holes NOT excluded). The 3D renderer meshes the
// hole interior too, so a well is a continuous closed depression that ties into an
// oval base, rather than an open cutout that leaves the funnel walls dangling.
function insideBoundary(surface: Surface, x: number, y: number): boolean {
    return Math.hypot(x, y) <= boundaryR(surface, Math.atan2(y, x));
}

function rimFade(surface: Surface, x: number, y: number): number {
    const R = boundaryR(surface, Math.atan2(y, x));
    return Math.max(0, Math.min(1, (R - Math.hypot(x, y)) / 0.5));
}

// Line brightness: peaks read vivid, valleys quiet down, everything fades into
// the rim. Baked into the vertex color so a single 1px line material stays crisp.
function lineBrightness(surface: Surface, x: number, y: number, z: number, theme: "light" | "dark"): number {
    const zc = Math.max(0, z);
    const base = theme === "dark" ? 0.42 : 0.5;
    const lift = Math.max(0, Math.min(1, base + 1.35 * zc));
    return lift * (0.5 + 0.5 * rimFade(surface, x, y));
}

// A soft radial-gradient texture for the floor under-glow.
function glowTexture(rgb: string): THREE.CanvasTexture {
    const size = 128;
    const cv = document.createElement("canvas");
    cv.width = cv.height = size;
    const c = cv.getContext("2d")!;
    const grad = c.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    grad.addColorStop(0, `rgba(${rgb},1)`);
    grad.addColorStop(1, `rgba(${rgb},0)`);
    c.fillStyle = grad;
    c.fillRect(0, 0, size, size);
    const tex = new THREE.CanvasTexture(cv);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
}

export function createManifold3D(container: HTMLElement, opts: Manifold3DOpts = {}): Manifold3DHandle {
    let surface = opts.surface ?? FULL_SURFACE;
    let theme: "light" | "dark" = opts.theme ?? "dark";
    let grid = opts.grid ?? 64;
    let heightScale = opts.heightScale ?? 1.15;
    let glow = opts.glow ?? 0.7;
    let vibrance = opts.vibrance ?? 0;
    let labelLayout: "offset" | "radial" = opts.labelLayout ?? "offset";
    const interactive = opts.interactive ?? true;
    const onLabels = opts.onLabels;
    const onTopic = opts.onTopic;
    let width = opts.width ?? container.clientWidth ?? 640;
    let height0 = opts.height ?? container.clientHeight ?? 420;

    const scratch = new THREE.Color();
    const projV = new THREE.Vector3();
    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(34, width / height0, 0.1, 100);
    const initialCam = new THREE.Vector3(0.55, 1.75, 2.75);
    const initialTarget = new THREE.Vector3(0, 0.12, 0);
    camera.position.copy(initialCam);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height0);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.rotateSpeed = 0.8;
    controls.minDistance = 1.6;
    controls.maxDistance = 6.5;
    controls.minPolarAngle = 0.12;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.autoRotate = opts.autoRotate ?? false;
    controls.autoRotateSpeed = 0.55;
    controls.enableRotate = interactive;
    controls.enableZoom = interactive;
    controls.target.copy(initialTarget);

    // Shared materials. All draw without writing depth so the surface reads as a
    // translucent shell (front and back both show, painter-ordered by renderOrder,
    // exactly like the 2D canvas). Glow planes get their own throwaway materials.
    const fillMat = new THREE.MeshBasicMaterial({
        vertexColors: true,
        transparent: true,
        side: THREE.DoubleSide,
        depthWrite: false,
    });
    const gridMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false });
    const rimMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false });

    // Everything data-driven lives in one group we swap out on rebuild.
    let group = new THREE.Group();
    let version = 0;
    // The translucent shell mesh, kept so a tap can raycast the surface body.
    let pickMesh: THREE.Mesh | undefined;
    // Persistent perimeter angle per topic label, so the radial layout seeds each
    // frame's relaxation from the last solve instead of re-deriving from scratch.
    const ringAngles = new Map<string, number>();
    // Persistent SCREEN position per label. The visible seat is low-passed toward
    // its freshly solved target here, which absorbs jitter from both the angle
    // solve and the wobbling silhouette radius, so motion reads fluid.
    const ringPos = new Map<string, { x: number; y: number }>();
    // Largest per-frame pixel move from the last radial solve; when it drops below
    // a small epsilon the layout has settled and can stop recomputing.
    let ringSettleDelta = 0;

    // Vibrance-driven color controls, tuned per theme. All reduce to the calm
    // defaults at vibrance 0, so the shipped Home hero is unchanged unless a
    // caller opts in. Dark mode already reads vividly, and brightening it blows
    // the hues toward white, so vibrance acts mostly on light mode (where the
    // 0.55 theme darkening otherwise greys everything out) and only gently on
    // dark: a touch more saturation, and never a lightness boost.
    function darkVibrance(): number {
        return vibrance * 0.25;
    }

    // `saturation` pushes hues further from grey; `lightness` counteracts the
    // light-theme darkening (light only, never dark).
    function vividAt(x: number, y: number): number[] {
        if (theme === "light") {
            return colorAt(surface, x, y, theme, 1.6 + vibrance * 1.8, 1 + vibrance * 1.0);
        }
        return colorAt(surface, x, y, theme, 1.6 + darkVibrance() * 1.2, 1);
    }

    // rgb (sRGB 0..255) -> linear, scaled by brightness, appended to `out`. A
    // color floor keeps wireframe lines colored instead of collapsing to near
    // black in the valleys; the floor is strong in light, gentle in dark.
    function pushRGB(out: number[], x: number, y: number, z: number, boost: number): void {
        const [r, g, b] = vividAt(x, y);
        const lit = lineBrightness(surface, x, y, z, theme) * boost;
        const v = theme === "light" ? vibrance : darkVibrance();
        const floor = (theme === "light" ? 0.5 : 0.2) * v;
        const bri = Math.min(1 + (theme === "light" ? 0.2 : 0) * v, floor + (1 - floor) * lit);
        scratch.setRGB((r / 255) * bri, (g / 255) * bri, (b / 255) * bri, THREE.SRGBColorSpace);
        out.push(scratch.r, scratch.g, scratch.b);
    }

    // The translucent fill: full-hue rgb with a per-vertex alpha that fades to
    // nothing in the valleys and at the rim, the "loose color fitting" from 2D.
    // Vibrance lifts the base, gain, and cap so the cells carry visible color,
    // strongly in light, gently in dark so it never washes to white.
    function pushFill(pos: number[], col: number[], x: number, y: number, z: number): void {
        pos.push(x, z * heightScale, y);
        const [r, g, b] = vividAt(x, y);
        scratch.setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace);
        const zc = Math.max(0, z);
        const v = theme === "light" ? vibrance : darkVibrance();
        const base = (theme === "dark" ? 0.05 : 0.07) + v * 0.13;
        const gain = (theme === "dark" ? 0.9 : 0.75) + v * 0.6;
        const cap = 0.55 + v * 0.3;
        const a = Math.max(
            0,
            Math.min(cap, glow * (0.4 + 0.6 * rimFade(surface, x, y)) * (base + gain * Math.pow(zc, 1.3))),
        );
        col.push(scratch.r, scratch.g, scratch.b, a);
    }

    function disposeGroup(): void {
        group.traverse((obj) => {
            const node = obj as { geometry?: THREE.BufferGeometry; material?: THREE.Material | THREE.Material[] };
            node.geometry?.dispose();
            const mat = node.material;
            if (mat && mat !== gridMat && mat !== rimMat && mat !== fillMat) {
                for (const m of Array.isArray(mat) ? mat : [mat]) {
                    (m as THREE.MeshBasicMaterial).map?.dispose();
                    m.dispose();
                }
            }
        });
        scene.remove(group);
    }

    function build(): void {
        group = new THREE.Group();
        pickMesh = undefined;
        const lim = domainLimit(surface);
        const n = grid;

        // Adaptive grid (ported from the 2D renderer): concentrate the fixed n
        // samples where the surface changes fastest, i.e. pack them across the
        // steep crater walls near each hole, so a well is resolved smoothly instead
        // of as a few big spiky facets. Bumps are only gently de-emphasised so the
        // rest of the manifold keeps the density it has now. Returns n+1 ticks.
        const axisTicks = (cGet: (o: { x: number; y: number }) => number, rGet: (o: Hole) => number): number[] => {
            const M = 400;
            const wArr: number[] = [];
            for (let k = 0; k <= M; k++) {
                const v = -lim + (2 * lim * k) / M;
                let d = 1 + 0.7 * Math.pow(Math.abs(v) / lim, 6);
                for (const h of surface.holes) {
                    const s = Math.max(0.1, rGet(h) * 1.15);
                    d += 1.5 * Math.exp(-Math.pow(v - cGet(h), 2) / (2 * s * s));
                }
                for (const b of surface.bumps) {
                    d -= 0.12 * (b.h / 0.5) * Math.exp(-Math.pow(v - cGet(b), 2) / (2 * b.s * b.s));
                }
                // A high floor keeps the smooth regions well sampled, so grid curves
                // stay visible everywhere, not just packed at the craters.
                wArr.push(Math.max(0.62, d));
            }
            const cum = [0];
            for (let k = 1; k <= M; k++) {
                cum.push(cum[k - 1] + (wArr[k - 1] + wArr[k]) / 2);
            }
            const ticks: number[] = [];
            let k = 0;
            for (let i = 0; i <= n; i++) {
                const target = (cum[M] * i) / n;
                while (k < M - 1 && cum[k + 1] < target) {
                    k++;
                }
                const f = Math.min(1, Math.max(0, (target - cum[k]) / ((cum[k + 1] - cum[k]) || 1)));
                ticks.push(-lim + (2 * lim * (k + f)) / M);
            }
            return ticks;
        };
        const xs = axisTicks((o) => o.x, (o) => o.rx);
        const ys = axisTicks((o) => o.y, (o) => o.ry);

        const z: number[][] = [];
        const vis: boolean[][] = [];
        for (let i = 0; i <= n; i++) {
            z.push([]);
            vis.push([]);
            for (let j = 0; j <= n; j++) {
                z[i].push(height(surface, xs[i], ys[j]));
                vis[i].push(insideBoundary(surface, xs[i], ys[j]));
            }
        }

        // Translucent color shell: two triangles per cell whose four corners are
        // all on the surface, so holes stay open. Painter-ordered under the lines.
        const fpos: number[] = [];
        const fcol: number[] = [];
        for (let i = 0; i < n; i++) {
            for (let j = 0; j < n; j++) {
                if (!vis[i][j] || !vis[i + 1][j] || !vis[i + 1][j + 1] || !vis[i][j + 1]) {
                    continue;
                }
                const corners: Array<[number, number]> = [[i, j], [i + 1, j], [i + 1, j + 1], [i, j + 1]];
                for (const t of [[0, 1, 2], [0, 2, 3]]) {
                    for (const ci of t) {
                        const [ii, jj] = corners[ci];
                        pushFill(fpos, fcol, xs[ii], ys[jj], z[ii][jj]);
                    }
                }
            }
        }
        if (fpos.length) {
            const fg = new THREE.BufferGeometry();
            fg.setAttribute("position", new THREE.Float32BufferAttribute(fpos, 3));
            fg.setAttribute("color", new THREE.Float32BufferAttribute(fcol, 4));
            const fillMesh = new THREE.Mesh(fg, fillMat);
            fillMesh.renderOrder = 0;
            group.add(fillMesh);
            pickMesh = fillMesh;
        }

        // Clip a grid point that is outside the outline back to the exact boundary
        // along the edge toward an inside point (binary search), so the mesh meets
        // the smooth outline instead of ending on a coarse grid staircase.
        const clipToBoundary = (
            xin: number,
            yin: number,
            xout: number,
            yout: number,
        ): { x: number; y: number } => {
            let lo = 0;
            let hi = 1;
            for (let k = 0; k < 14; k++) {
                const mid = (lo + hi) / 2;
                const x = xin + (xout - xin) * mid;
                const y = yin + (yout - yin) * mid;
                if (insideBoundary(surface, x, y)) {
                    lo = mid;
                } else {
                    hi = mid;
                }
            }
            return { x: xin + (xout - xin) * lo, y: yin + (yout - yin) * lo };
        };

        // Wireframe. An edge with both ends inside draws straight; an edge that
        // crosses the outline is clipped to it (like the 2D renderer's `seg`), so
        // the boundary reads as the smooth outline, not a spiky grid staircase.
        const positions: number[] = [];
        const colors: number[] = [];
        const pushVert = (x: number, y: number, zz: number): void => {
            positions.push(x, zz * heightScale, y);
            pushRGB(colors, x, y, zz, glow);
        };
        const edge = (i0: number, j0: number, i1: number, j1: number): void => {
            const v0 = vis[i0][j0];
            const v1 = vis[i1][j1];
            if (!v0 && !v1) {
                return;
            }
            const x0 = xs[i0];
            const y0 = ys[j0];
            const x1 = xs[i1];
            const y1 = ys[j1];
            if (v0 && v1) {
                pushVert(x0, y0, z[i0][j0]);
                pushVert(x1, y1, z[i1][j1]);
            } else if (v0) {
                const c = clipToBoundary(x0, y0, x1, y1);
                pushVert(x0, y0, z[i0][j0]);
                pushVert(c.x, c.y, height(surface, c.x, c.y));
            } else {
                const c = clipToBoundary(x1, y1, x0, y0);
                pushVert(c.x, c.y, height(surface, c.x, c.y));
                pushVert(x1, y1, z[i1][j1]);
            }
        };
        for (let i = 0; i <= n; i++) {
            for (let j = 0; j <= n; j++) {
                if (i < n) {
                    edge(i, j, i + 1, j);
                }
                if (j < n) {
                    edge(i, j, i, j + 1);
                }
            }
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
        geo.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
        const lines = new THREE.LineSegments(geo, gridMat);
        lines.renderOrder = 1;
        group.add(lines);

        // Crisp rim outlines (blob boundary + each hole), high angular resolution.
        const rimBoost = Math.min(1, glow * 1.25);
        const rimLoop = (pts: Array<[number, number]>): void => {
            const rp: number[] = [];
            const rc: number[] = [];
            for (const [x, y] of pts) {
                const hz = height(surface, x, y);
                rp.push(x, hz * heightScale, y);
                pushRGB(rc, x, y, hz, rimBoost);
            }
            const rg = new THREE.BufferGeometry();
            rg.setAttribute("position", new THREE.Float32BufferAttribute(rp, 3));
            rg.setAttribute("color", new THREE.Float32BufferAttribute(rc, 3));
            const loop = new THREE.LineLoop(rg, rimMat);
            loop.renderOrder = 2;
            group.add(loop);
        };
        const boundaryPts: Array<[number, number]> = [];
        for (let k = 0; k < 220; k++) {
            const th = (k / 220) * Math.PI * 2;
            const R = boundaryR(surface, th);
            boundaryPts.push([R * Math.cos(th), R * Math.sin(th)]);
        }
        rimLoop(boundaryPts);
        for (const h of surface.holes) {
            const rot = h.rot ?? 0;
            const cs = Math.cos(rot);
            const sn = Math.sin(rot);
            const ell: Array<[number, number]> = [];
            for (let k = 0; k < 140; k++) {
                const th = (k / 140) * Math.PI * 2;
                const u = h.rx * Math.cos(th);
                const v = h.ry * Math.sin(th);
                ell.push([h.x + u * cs - v * sn, h.y + u * sn + v * cs]);
            }
            rimLoop(ell);
        }

        // Soft under-glow discs on the floor, the only "imagery" allowed.
        const glowOpacity = (theme === "dark" ? 0.1 : 0.13) * glow;
        for (const g of surface.glows) {
            const mat = new THREE.MeshBasicMaterial({
                map: glowTexture(g.c),
                transparent: true,
                opacity: glowOpacity,
                depthWrite: false,
            });
            const plane = new THREE.Mesh(new THREE.PlaneGeometry(lim * 1.7, lim * 1.7), mat);
            plane.rotation.x = -Math.PI / 2;
            plane.position.set(g.x, -0.02, g.y);
            plane.renderOrder = -1;
            group.add(plane);
        }

        gridMat.opacity = theme === "dark" ? 0.96 : 0.9;
        rimMat.opacity = theme === "dark" ? 0.98 : 0.95;
        scene.add(group);
        version++;
    }

    function rebuild(): void {
        disposeGroup();
        build();
    }

    // The two translate percentages baked into a label's CSS transform tell us
    // which corner sits on the point, so we can keep the whole box on screen.
    function anchorPct(tf: string): [number, number] {
        const m = tf.match(/-?\d+(?:\.\d+)?/g);
        return [m ? parseFloat(m[0]) : 0, m && m[1] !== undefined ? parseFloat(m[1]) : 0];
    }

    // Project one surface point (surface x, y) to screen pixels.
    function projectPoint(sx: number, sy: number): { x: number; y: number; front: boolean } {
        const hz = height(surface, sx, sy);
        projV.set(sx, hz * heightScale, sy).project(camera);
        return {
            x: (projV.x * 0.5 + 0.5) * width,
            y: (-projV.y * 0.5 + 0.5) * height0,
            front: projV.z < 1 && projV.z > -1,
        };
    }

    // Elbow leader: from the anchor, a diagonal run to a knee, then a short leg
    // into the label's inner edge at its vertical (or horizontal) middle. Uses a
    // horizontal leg when the label sits mostly to the side, a vertical leg when
    // it sits mostly above or below (the "no horizontal room" case).
    function leaderPath(
        ax: number,
        ay: number,
        bx: number,
        by: number,
        hw: number,
        hh: number,
    ): { x: number; y: number }[] {
        const leg = 13;
        const dx = bx - ax;
        const dy = by - ay;
        let attachX: number;
        let attachY: number;
        let kneeX: number;
        let kneeY: number;
        if (Math.abs(dx) >= Math.abs(dy)) {
            const left = ax < bx; // anchor to the label's left -> attach left edge
            attachX = left ? bx - hw : bx + hw;
            attachY = by;
            kneeX = left ? attachX - leg : attachX + leg;
            kneeY = attachY;
        } else {
            const above = ay < by; // anchor above the label -> attach top edge
            attachY = above ? by - hh : by + hh;
            attachX = bx;
            kneeY = above ? attachY - leg : attachY + leg;
            kneeX = attachX;
        }
        return [
            { x: ax, y: ay },
            { x: kneeX, y: kneeY },
            { x: attachX, y: attachY },
        ];
    }

    // Whether segment (x1,y1)-(x2,y2) intersects the axis-aligned box centred at
    // (bx,by) with half-extents (hw,hh). Used to detect a leader crossing a label.
    function segHitsRect(
        x1: number,
        y1: number,
        x2: number,
        y2: number,
        bx: number,
        by: number,
        hw: number,
        hh: number,
    ): boolean {
        const L = bx - hw;
        const R = bx + hw;
        const T = by - hh;
        const B = by + hh;
        const inside = (x: number, y: number): boolean => x >= L && x <= R && y >= T && y <= B;
        if (inside(x1, y1) || inside(x2, y2)) {
            return true;
        }
        const ccw = (ax: number, ay: number, bx2: number, by2: number, cx2: number, cy2: number): number =>
            (by2 - ay) * (cx2 - ax) - (bx2 - ax) * (cy2 - ay);
        const segSeg = (
            ax: number,
            ay: number,
            bx2: number,
            by2: number,
            cx2: number,
            cy2: number,
            dx2: number,
            dy2: number,
        ): boolean => {
            const d1 = ccw(cx2, cy2, dx2, dy2, ax, ay);
            const d2 = ccw(cx2, cy2, dx2, dy2, bx2, by2);
            const d3 = ccw(ax, ay, bx2, by2, cx2, cy2);
            const d4 = ccw(ax, ay, bx2, by2, dx2, dy2);
            return d1 * d2 < 0 && d3 * d4 < 0;
        };
        return (
            segSeg(x1, y1, x2, y2, L, T, R, T)
            || segSeg(x1, y1, x2, y2, R, T, R, B)
            || segSeg(x1, y1, x2, y2, R, B, L, B)
            || segSeg(x1, y1, x2, y2, L, B, L, T)
        );
    }

    function labelInk(l: ManifoldLabel): string {
        const ink = theme === "light" ? [38, 38, 36] : [236, 234, 227];
        const mixK = theme === "light" ? 0.18 : 0.35;
        const cc = colorAt(surface, l.x, l.y, theme, 1.6 + vibrance * 1.2).map((v, i) =>
            Math.round(v + (ink[i] - v) * mixK)
        );
        return `rgb(${cc.join(",")})`;
    }

    // Fixed per-label offset layout (the original): each label rides its design
    // dx/dy, clamped only to the viewport edge.
    function computeLabelsOffset(): ProjectedLabel3D[] {
        const pad = 6;
        return surface.labels.map((l) => {
            const a = projectPoint(l.x, l.y);
            let lx = a.x + l.dx;
            let ly = a.y + l.dy;
            const [tx, ty] = anchorPct(l.tf);
            const estW = l.name.length * 6.6 + 12;
            const estH = 18;
            const boxLeft = lx + (tx / 100) * estW;
            const boxTop = ly + (ty / 100) * estH;
            if (boxLeft < pad) {
                lx += pad - boxLeft;
            } else if (boxLeft + estW > width - pad) {
                lx += width - pad - (boxLeft + estW);
            }
            if (boxTop < pad) {
                ly += pad - boxTop;
            } else if (boxTop + estH > height0 - pad) {
                ly += height0 - pad - (boxTop + estH);
            }
            return {
                name: l.name,
                ax: a.x,
                ay: a.y,
                lx,
                ly,
                tf: l.tf,
                c: labelInk(l),
                visible: a.front,
                topic: l.topic,
            };
        });
    }

    // Perimeter layout. Each label rides the ring just outside the projected
    // outline, placed by ANGLE around the figure. Overlaps are resolved in angle
    // space: labels spread AROUND the perimeter, so a crowded top offloads its
    // overflow down the sides toward the empty bottom instead of stacking, while a
    // soft spring keeps each as near its own region's direction as room allows.
    // The radius is capped to the viewport so labels never leave the frame, and an
    // elbow leader ties each back to its anchor. Re-solved each frame.
    function computeLabelsRadial(): ProjectedLabel3D[] {
        const pad = 6;
        const gapPx = 15; // min pixel gap between neighbours along the ring
        const iters = 30; // per-frame relaxation passes (state persists between frames)
        const pull = 0.14; // spring back toward each label's own direction, per pass
        const posEase = 0.16; // base smoothing for tiny jitter when nearly still
        const trackGain = 0.06; // ramp toward full tracking as the target moves faster
        const evenness = 0.72; // 0 hug regions, 1 perfectly uniform around the ring

        // Screen centre = the orbit target projected (camera is aimed at it).
        projV.copy(controls.target).project(camera);
        let cx = (projV.x * 0.5 + 0.5) * width;
        let cy = (-projV.y * 0.5 + 0.5) * height0;
        if (!Number.isFinite(cx) || !Number.isFinite(cy)) {
            cx = width / 2;
            cy = height0 / 2;
        }

        // Silhouette support (projected rim): how far the outline reaches in a dir,
        // so a label never sits inside the surface where the figure is wide.
        const cloud: { x: number; y: number }[] = [];
        for (let k = 0; k < 48; k++) {
            const th = (k / 48) * Math.PI * 2;
            const R = boundaryR(surface, th);
            const p = projectPoint(R * Math.cos(th), R * Math.sin(th));
            cloud.push({ x: p.x, y: p.y });
        }
        const reach = (ux: number, uy: number): number => {
            let m = 0;
            for (const p of cloud) {
                const d = (p.x - cx) * ux + (p.y - cy) * uy;
                if (d > m) {
                    m = d;
                }
            }
            return m;
        };

        const TAU = Math.PI * 2;
        const norm = (a: number): number => ((a % TAU) + TAU) % TAU;
        const wrap = (d: number): number => {
            let r = ((d % TAU) + TAU) % TAU;
            if (r > Math.PI) {
                r -= TAU;
            }
            return r;
        };

        interface L {
            l: ManifoldLabel;
            ax: number;
            ay: number;
            visible: boolean;
            hw: number;
            hh: number;
            th: number; // target (region) angle
            ang: number; // current angle
        }
        const items: L[] = surface.labels.map((l) => {
            const a = projectPoint(l.x, l.y);
            let dx = a.x - cx;
            let dy = a.y - cy;
            let len = Math.hypot(dx, dy);
            if (len < 1) {
                dx = l.dx;
                dy = l.dy;
                len = Math.hypot(dx, dy) || 1;
            }
            const th = Math.atan2(dy, dx);
            const w = l.name.length * 6.6 + 12;
            return { l, ax: a.x, ay: a.y, visible: a.front, hw: w / 2, hh: 9, th, ang: th };
        });
        const n = items.length;
        const maxHw = items.reduce((m, x) => Math.max(m, x.hw), 0);

        // The ring is a viewport-fitted ellipse: it ALWAYS fits the frame (so a
        // label is never clamped to an edge, which was the cause of pile-ups), and
        // being frame-shaped it fills the top corners and the sides equally. Where
        // the manifold reaches past it (a wide middle), the silhouette floor pushes
        // that label a little further out so it clears the surface.
        const ERX = Math.max(40, width / 2 - pad - maxHw);
        const ERY = Math.max(30, height0 / 2 - pad - 11);
        const radiusAt = (ux: number, uy: number, hw: number, hh: number): number => {
            const ell = 1 / Math.hypot(ux / ERX, uy / ERY);
            const floor = reach(ux, uy) + gapPx + Math.abs(ux) * hw + Math.abs(uy) * hh;
            // Cap the floor so a very wide figure cannot shove a label off-frame.
            const cappedFloor = Math.min(floor, ell * 1.12);
            return Math.max(ell * 0.9, cappedFloor);
        };

        // Each label's own region direction in the current view, kept so the label
        // stays radially outward from where its region actually sits (correct
        // left/right half AND top/bottom half) rather than scanning toward the
        // centre line.
        const regionTh = items.map((m) => m.th);

        // Fix the cyclic order of the labels to the cyclic order of their anchors,
        // ONCE. Every later step (even spread, de-overlap) keeps this order rather
        // than re-sorting, so a label never swaps past a neighbour, which is what
        // makes leader lines cross. Anchor order in = leader order out = no crossings.
        const fixedOrder = items.map((_, i) => i).sort((i, j) => norm(regionTh[i]) - norm(regionTh[j]));

        // Blend each label's target angle toward an evenly spaced slot, so ALL
        // sides of the figure are used equally (top included), while the ordering
        // still follows each label's own region.
        {
            const step0 = TAU / n;
            let sinS = 0;
            let cosS = 0;
            fixedOrder.forEach((idx, k) => {
                const d = regionTh[idx] - k * step0;
                sinS += Math.sin(d);
                cosS += Math.cos(d);
            });
            const off = Math.atan2(sinS, cosS);
            fixedOrder.forEach((idx, k) => {
                const slot = off + k * step0;
                items[idx].th = items[idx].th + evenness * wrap(slot - items[idx].th);
            });
        }

        // Radial affinity (first resort): keep each label's target within a cone of
        // its own region direction, so it reads radially outward from that region
        // (and therefore stays in the correct half, top or bottom, of the correct
        // hemisphere) instead of scanning across to the centre line. Inside the
        // cone it can still spread for even coverage; the hard de-overlap below can
        // still push a label past the cone when crowding truly demands it.
        const maxDev = 1.22; // ~70 degrees
        items.forEach((m, idx) => {
            const dev = wrap(m.th - regionTh[idx]);
            if (dev > maxDev) {
                m.th = regionTh[idx] + maxDev;
            } else if (dev < -maxDev) {
                m.th = regionTh[idx] - maxDev;
            }
        });

        // Seed the working angle from the PREVIOUS frame (persistent), so the
        // solver refines a stable state instead of re-deriving it from scratch.
        for (const m of items) {
            const prev = ringAngles.get(m.l.name);
            m.ang = prev !== undefined ? prev : m.th;
        }

        // Angle-space relaxation on the FIXED anchor order: enforce a minimum
        // angular gap between cyclic neighbours (never re-sorting, so the order and
        // thus the non-crossing property are preserved), then a soft pull toward
        // each label's (evened) angle.
        for (let it = 0; it < iters; it++) {
            const half = items.map((m) => {
                const ux = Math.cos(m.ang);
                const uy = Math.sin(m.ang);
                const r = Math.max(30, radiusAt(ux, uy, m.hw, m.hh));
                const spanPx = Math.abs(uy) * m.hw + Math.abs(ux) * m.hh + gapPx;
                return spanPx / r;
            });
            for (let k = 0; k < n; k++) {
                const i = fixedOrder[k];
                const j = fixedOrder[(k + 1) % n];
                const gap = norm(items[j].ang - items[i].ang);
                const need = half[i] + half[j];
                if (gap < need) {
                    const shove = (need - gap) / 2;
                    items[i].ang -= shove;
                    items[j].ang += shove;
                }
            }
            for (const m of items) {
                m.ang += pull * wrap(m.th - m.ang);
            }
        }

        ringSettleDelta = 0;
        interface Solved {
            m: L;
            x: number;
            y: number;
            lead: { x: number; y: number }[];
            chip: number;
        }
        const solved: Solved[] = items.map((m) => {
            // Seed next frame's relaxation from this frame's solved angle so the
            // angular spread stays stable frame to frame.
            ringAngles.set(m.l.name, m.ang);

            const ux = Math.cos(m.ang);
            const uy = Math.sin(m.ang);
            const r = radiusAt(ux, uy, m.hw, m.hh);
            // Freshly solved target seat for this frame.
            let bx = cx + ux * r;
            let by = cy + uy * r;

            // Motion-adaptive low-pass on the VISIBLE seat. When the target barely
            // moved (solver/radius jitter while nearly still) we ease gently, so it
            // reads smooth; as the target moves faster (a real zoom or orbit) the
            // ease ramps toward 1, so the seat tracks its anchor instead of lagging
            // behind and stretching the leader. That lag was the "break" when
            // zooming in hard, where perspective makes seats travel far per frame.
            const prev = ringPos.get(m.l.name);
            if (prev) {
                const tdx = bx - prev.x;
                const tdy = by - prev.y;
                const td = Math.hypot(tdx, tdy);
                const alpha = Math.min(1, posEase + td * trackGain);
                bx = prev.x + tdx * alpha;
                by = prev.y + tdy * alpha;
                const moved = td * alpha;
                if (moved > ringSettleDelta) {
                    ringSettleDelta = moved;
                }
            }
            ringPos.set(m.l.name, { x: bx, y: by });

            // How far the box sits inside the outline (crowded): 0 when comfortably
            // outside, rising as it grazes the mesh, to fade in the backing pill.
            const over = reach(ux, uy) - r;
            const chip = Math.max(0, Math.min(1, (over + 6) / 36));
            return { m, x: bx, y: by, lead: leaderPath(m.ax, m.ay, bx, by, m.hw, m.hh), chip };
        });

        // Leader-overlap detection: if a label box sits over ANOTHER label's leader
        // line, raise its pill so the line falls behind it and the text stays
        // readable. (Its own leader ends at the box, so it is excluded.)
        const boxPad = 2;
        for (let i = 0; i < solved.length; i++) {
            const a = solved[i];
            let hit = false;
            for (let j = 0; j < solved.length && !hit; j++) {
                if (j === i) {
                    continue;
                }
                const lead = solved[j].lead;
                for (let s = 0; s < lead.length - 1 && !hit; s++) {
                    if (
                        segHitsRect(
                            lead[s].x,
                            lead[s].y,
                            lead[s + 1].x,
                            lead[s + 1].y,
                            a.x,
                            a.y,
                            a.m.hw + boxPad,
                            a.m.hh + boxPad,
                        )
                    ) {
                        hit = true;
                    }
                }
            }
            if (hit) {
                a.chip = Math.max(a.chip, 1);
            }
        }

        return solved.map((a) => ({
            name: a.m.l.name,
            ax: a.m.ax,
            ay: a.m.ay,
            lx: a.x,
            ly: a.y,
            tf: "translate(-50%, -50%)",
            lead: a.lead,
            chip: a.chip,
            c: labelInk(a.m.l),
            visible: a.m.visible,
            topic: a.m.l.topic,
        }));
    }

    function computeLabels(): ProjectedLabel3D[] {
        return labelLayout === "radial" ? computeLabelsRadial() : computeLabelsOffset();
    }

    let lastLabelHash = "";
    let lastCamHash = "";
    let layoutSettled = false;
    let lastLabels: ProjectedLabel3D[] = [];
    const SETTLE_EPS = 0.25; // px/frame below which the ring is considered at rest
    // Past this camera distance the manifold fills the frame, the perimeter ring
    // has no room, and labels spill off. Worse, the persistent solver drifts to an
    // extreme arrangement that then eases slowly back on zoom-out (looks broken).
    // So we hide labels below HIDE and show again above SHOW; the gap is hysteresis
    // that stops flicker when parked right at the edge.
    const LABEL_HIDE_DIST = 2.5;
    const LABEL_SHOW_DIST = 2.72;
    let labelsHidden = false;
    function emitLabels(): void {
        if (!onLabels) {
            return;
        }
        // Zoomed in past the threshold: hide the labels and freeze the solver. On
        // the way back out we clear the ring so labels snap straight to their
        // resting places (prev-angle undefined = no ease) with no visible readjust.
        const dist = camera.position.distanceTo(controls.target);
        const shouldHide = labelsHidden ? dist < LABEL_SHOW_DIST : dist < LABEL_HIDE_DIST;
        if (shouldHide) {
            if (!labelsHidden) {
                labelsHidden = true;
                // Fade the current labels out in place: keep their seats, drop
                // opacity to 0, and let the overlay's CSS transition dissolve them.
                // The solver stays frozen while hidden.
                lastLabelHash = "";
                onLabels(lastLabels.map((l) => ({ ...l, opacity: 0 })));
            }
            return;
        }
        if (labelsHidden) {
            labelsHidden = false;
            // Snap the ring to fresh resting seats (no stale easing) so labels fade
            // back in already in place instead of drifting across the frame.
            ringAngles.clear();
            ringPos.clear();
            lastCamHash = "";
            layoutSettled = false;
        }
        // A change in camera, size, surface, or layout re-opens the animation; we
        // then ease each frame until the ring settles, at which point we stop
        // recomputing entirely so an idle manifold costs nothing.
        const p = camera.position;
        const t = controls.target;
        const camHash = [version, width, height0, labelLayout, p.x, p.y, p.z, t.x, t.y, t.z]
            .map((v) => (typeof v === "number" ? v.toFixed(3) : v))
            .join("|");
        if (camHash !== lastCamHash) {
            lastCamHash = camHash;
            layoutSettled = false;
        }
        if (layoutSettled) {
            return;
        }

        const labels = computeLabels();
        lastLabels = labels;
        // The offset layout is deterministic (no easing); radial reports how far it
        // still moved this frame. Either way, settle once movement is negligible.
        if (labelLayout !== "radial" || ringSettleDelta < SETTLE_EPS) {
            layoutSettled = true;
        }

        const hash = labels
            .map((l) => `${Math.round(l.lx)},${Math.round(l.ly)},${l.visible ? 1 : 0}`)
            .join("|");
        if (hash === lastLabelHash) {
            return;
        }
        lastLabelHash = hash;
        onLabels(labels);
    }

    // Tap-to-drill (ux-foundation 5). A pointer that presses and releases near
    // the same spot in a short window is a tap, not an orbit drag, so we raycast
    // the surface shell and launch the nearest topic's focus drill. A drag to
    // orbit moves too far to count, so it never fires.
    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let downX = 0;
    let downY = 0;
    let downT = 0;
    let downId = -1;

    function nearestTopic(sx: number, sy: number): string | undefined {
        let best: string | undefined;
        let bestD = Infinity;
        for (const l of surface.labels) {
            if (!l.topic) {
                continue;
            }
            const d = (l.x - sx) * (l.x - sx) + (l.y - sy) * (l.y - sy);
            if (d < bestD) {
                bestD = d;
                best = l.topic;
            }
        }
        return best;
    }

    function pickTopic(clientX: number, clientY: number): void {
        if (!onTopic || !pickMesh) {
            return;
        }
        const rect = renderer.domElement.getBoundingClientRect();
        if (!rect.width || !rect.height) {
            return;
        }
        ndc.set(
            ((clientX - rect.left) / rect.width) * 2 - 1,
            -((clientY - rect.top) / rect.height) * 2 + 1,
        );
        raycaster.setFromCamera(ndc, camera);
        const hit = raycaster.intersectObject(pickMesh, false)[0];
        if (!hit) {
            return;
        }
        // World (x, z) map back to surface (x, y); world y carries the height.
        const slug = nearestTopic(hit.point.x, hit.point.z);
        if (slug) {
            onTopic(slug);
        }
    }

    function onPointerDown(e: PointerEvent): void {
        downX = e.clientX;
        downY = e.clientY;
        downT = performance.now();
        downId = e.pointerId;
    }

    function onPointerUp(e: PointerEvent): void {
        if (e.pointerId !== downId) {
            return;
        }
        downId = -1;
        const moved = Math.hypot(e.clientX - downX, e.clientY - downY);
        if (moved <= 5 && performance.now() - downT <= 500) {
            pickTopic(e.clientX, e.clientY);
        }
    }

    if (onTopic && interactive) {
        renderer.domElement.addEventListener("pointerdown", onPointerDown);
        renderer.domElement.addEventListener("pointerup", onPointerUp);
    }

    build();

    let running = true;
    renderer.setAnimationLoop(() => {
        if (!running) {
            return;
        }
        controls.update();
        renderer.render(scene, camera);
        emitLabels();
    });

    return {
        update(nextSurface: Surface, nextTheme: "light" | "dark"): void {
            surface = nextSurface;
            theme = nextTheme;
            rebuild();
            lastLabelHash = "";
        },
        setShape(shape: ManifoldShapeOpts): void {
            let changed = false;
            if (shape.grid !== undefined && shape.grid !== grid) {
                grid = shape.grid;
                changed = true;
            }
            if (shape.heightScale !== undefined && shape.heightScale !== heightScale) {
                heightScale = shape.heightScale;
                changed = true;
            }
            if (shape.glow !== undefined && shape.glow !== glow) {
                glow = shape.glow;
                changed = true;
            }
            if (shape.vibrance !== undefined && shape.vibrance !== vibrance) {
                vibrance = shape.vibrance;
                changed = true;
            }
            if (changed) {
                rebuild();
                lastLabelHash = "";
            }
        },
        setAutoRotate(on: boolean): void {
            controls.autoRotate = on;
        },
        setLabelLayout(mode: "offset" | "radial"): void {
            if (mode !== labelLayout) {
                labelLayout = mode;
                lastLabelHash = ""; // force a recompute on the next frame
            }
        },
        resize(w: number, h: number): void {
            width = w;
            height0 = h;
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h);
            lastLabelHash = "";
        },
        resetView(): void {
            camera.position.copy(initialCam);
            controls.target.copy(initialTarget);
            controls.update();
        },
        orbitTo(azimuth: number, polar?: number): void {
            const offset = camera.position.clone().sub(controls.target);
            const radius = offset.length() || 3;
            const curPolar = Math.acos(Math.max(-1, Math.min(1, offset.y / radius)));
            const pol = Math.max(
                controls.minPolarAngle + 0.01,
                Math.min(controls.maxPolarAngle - 0.01, polar ?? curPolar),
            );
            const sinP = Math.sin(pol);
            camera.position.set(
                controls.target.x + radius * sinP * Math.sin(azimuth),
                controls.target.y + radius * Math.cos(pol),
                controls.target.z + radius * sinP * Math.cos(azimuth),
            );
            camera.lookAt(controls.target);
            controls.update();
            lastLabelHash = "";
        },
        setDistance(distance: number): void {
            const dir = camera.position.clone().sub(controls.target);
            const len = dir.length() || 1;
            const d = Math.max(controls.minDistance, Math.min(controls.maxDistance, distance));
            camera.position.copy(controls.target).add(dir.multiplyScalar(d / len));
            controls.update();
            lastLabelHash = "";
        },
        dispose(): void {
            running = false;
            renderer.setAnimationLoop(null);
            if (onTopic && interactive) {
                renderer.domElement.removeEventListener("pointerdown", onPointerDown);
                renderer.domElement.removeEventListener("pointerup", onPointerUp);
            }
            disposeGroup();
            controls.dispose();
            fillMat.dispose();
            gridMat.dispose();
            rimMat.dispose();
            renderer.dispose();
            if (renderer.domElement.parentNode === container) {
                container.removeChild(renderer.domElement);
            }
        },
    };
}
