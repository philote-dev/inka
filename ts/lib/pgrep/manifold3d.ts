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

import { boundaryR, colorAt, FULL_SURFACE, height, inHole, type Surface } from "./manifold";

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
    width?: number;
    height?: number;
    /** Called each frame the camera or surface moves, with topic label anchors
     *  projected to pixel space so an HTML overlay can track them. */
    onLabels?: (labels: ProjectedLabel3D[]) => void;
}

export interface ManifoldShapeOpts {
    grid?: number;
    heightScale?: number;
    glow?: number;
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
    /** Label ink, a readable tint of the region hue. */
    c: string;
    /** False when the anchor is behind the camera or off screen. */
    visible: boolean;
}

export interface Manifold3DHandle {
    /** Reshape to a new surface and/or theme. Rebuilds the wireframe. */
    update(surface: Surface, theme: "light" | "dark"): void;
    /** Adjust structural look (density, exaggeration, brightness) live. */
    setShape(opts: ManifoldShapeOpts): void;
    setAutoRotate(on: boolean): void;
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

function visibleAt(surface: Surface, x: number, y: number): boolean {
    const r = Math.hypot(x, y);
    return r <= boundaryR(surface, Math.atan2(y, x)) && !inHole(surface, x, y);
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
    const interactive = opts.interactive ?? true;
    const onLabels = opts.onLabels;
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

    // rgb (sRGB 0..255) -> linear, scaled by brightness, appended to `out`.
    function pushRGB(out: number[], x: number, y: number, z: number, boost: number): void {
        const [r, g, b] = colorAt(surface, x, y, theme);
        const bri = Math.min(1, lineBrightness(surface, x, y, z, theme) * boost);
        scratch.setRGB((r / 255) * bri, (g / 255) * bri, (b / 255) * bri, THREE.SRGBColorSpace);
        out.push(scratch.r, scratch.g, scratch.b);
    }

    // The translucent fill: full-hue rgb with a per-vertex alpha that fades to
    // nothing in the valleys and at the rim, the "loose color fitting" from 2D.
    function pushFill(pos: number[], col: number[], x: number, y: number, z: number): void {
        pos.push(x, z * heightScale, y);
        const [r, g, b] = colorAt(surface, x, y, theme);
        scratch.setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace);
        const zc = Math.max(0, z);
        const base = theme === "dark" ? 0.05 : 0.07;
        const gain = theme === "dark" ? 0.9 : 0.75;
        const a = Math.max(
            0,
            Math.min(0.55, glow * (0.4 + 0.6 * rimFade(surface, x, y)) * (base + gain * Math.pow(zc, 1.3))),
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
        const lim = domainLimit(surface);
        const n = grid;

        const axis: number[] = [];
        for (let i = 0; i <= n; i++) {
            axis.push(-lim + (2 * lim * i) / n);
        }
        const z: number[][] = [];
        const vis: boolean[][] = [];
        for (let i = 0; i <= n; i++) {
            z.push([]);
            vis.push([]);
            for (let j = 0; j <= n; j++) {
                z[i].push(height(surface, axis[i], axis[j]));
                vis[i].push(visibleAt(surface, axis[i], axis[j]));
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
                        pushFill(fpos, fcol, axis[ii], axis[jj], z[ii][jj]);
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
        }

        // Wireframe: an edge exists only if both endpoints are on the surface.
        const positions: number[] = [];
        const colors: number[] = [];
        const edge = (i0: number, j0: number, i1: number, j1: number): void => {
            if (!vis[i0][j0] || !vis[i1][j1]) {
                return;
            }
            positions.push(axis[i0], z[i0][j0] * heightScale, axis[j0]);
            positions.push(axis[i1], z[i1][j1] * heightScale, axis[j1]);
            pushRGB(colors, axis[i0], axis[j0], z[i0][j0], glow);
            pushRGB(colors, axis[i1], axis[j1], z[i1][j1], glow);
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

    // Project topic anchors to pixel space for the HTML label overlay, clamped so
    // no label is clipped by the viewport regardless of its size.
    function computeLabels(): ProjectedLabel3D[] {
        const ink = theme === "light" ? [38, 38, 36] : [236, 234, 227];
        const mixK = theme === "light" ? 0.18 : 0.35;
        const pad = 6;
        return surface.labels.map((l) => {
            const hz = height(surface, l.x, l.y);
            projV.set(l.x, hz * heightScale, l.y).project(camera);
            const visible = projV.z < 1 && projV.z > -1 && Math.abs(projV.x) < 1.4 && Math.abs(projV.y) < 1.4;
            const ax = (projV.x * 0.5 + 0.5) * width;
            const ay = (-projV.y * 0.5 + 0.5) * height0;

            let lx = ax + l.dx;
            let ly = ay + l.dy;
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

            const cc = colorAt(surface, l.x, l.y, theme).map((v, i) => Math.round(v + (ink[i] - v) * mixK));
            return { name: l.name, ax, ay, lx, ly, tf: l.tf, c: `rgb(${cc.join(",")})`, visible };
        });
    }

    let lastLabelHash = "";
    function emitLabels(): void {
        if (!onLabels) {
            return;
        }
        const p = camera.position;
        const t = controls.target;
        const hash = [version, width, height0, p.x, p.y, p.z, t.x, t.y, t.z]
            .map((v) => (typeof v === "number" ? v.toFixed(3) : v))
            .join("|");
        if (hash === lastLabelHash) {
            return;
        }
        lastLabelHash = hash;
        onLabels(computeLabels());
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
            if (changed) {
                rebuild();
                lastLabelHash = "";
            }
        },
        setAutoRotate(on: boolean): void {
            controls.autoRotate = on;
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
        dispose(): void {
            running = false;
            renderer.setAnimationLoop(null);
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
