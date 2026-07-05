// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// pgrep knowledge-manifold renderer, ported verbatim (with types) from the
// Claude Design export (design/ux-foundation.md). Fully data driven: pass a
// `surface` built from live stats and every peak, hole, glow, and label
// follows. Canvas 2D for now; the production Three.js version consumes the
// identical `surface` structure (bumps -> vertex displacement, holes -> alpha
// mask), with drawContour as the 2D fallback.

export interface Bump {
    x: number;
    y: number;
    h: number;
    s: number;
}

export interface Hole {
    x: number;
    y: number;
    rx: number;
    ry: number;
    rot?: number;
}

export interface Glow {
    x: number;
    y: number;
    c: string;
}

export interface ManifoldLabel {
    name: string;
    x: number;
    y: number;
    dx: number;
    dy: number;
    tf: string;
    /** Blueprint category slug for the focus-drill entry (ux-foundation 5).
     *  When set, the label becomes a launcher into a topic-scoped Study drill. */
    topic?: string;
}

export interface Surface {
    boundary: number[];
    spread?: number;
    bumps: Bump[];
    dips: Bump[];
    holes: Hole[];
    glows: Glow[];
    labels: ManifoldLabel[];
}

export interface ManifoldOpts {
    W?: number;
    H?: number;
    S?: number;
    dpr?: number;
    glow?: number;
    fill?: number;
    grid?: number;
    lineWidth?: number;
    levels?: number[];
    theme?: "light" | "dark";
    surface?: Surface;
}

export interface ProjectedLabel {
    name: string;
    ax: number;
    ay: number;
    lx: number;
    ly: number;
    tf: string;
    c: string;
    /** Blueprint category slug, carried through so the overlay label can launch
     *  a topic-scoped focus drill when clicked. */
    topic?: string;
}

interface ProjectOpts {
    W: number;
    H: number;
    S: number;
}

export const DEFAULT_SURFACE: Surface = {
    boundary: [1.04, 0.13, 0.7, 0.05, -1.2],
    bumps: [
        { x: -0.62, y: 0.38, h: 0.52, s: 0.38 },
        { x: 0.55, y: 0.02, h: 0.55, s: 0.42 },
        { x: 0.05, y: 0.62, h: 0.24, s: 0.34 },
        { x: -0.05, y: -0.55, h: 0.22, s: 0.38 },
    ],
    dips: [
        { x: 0.0, y: 0.12, h: 0.1, s: 0.35 },
        { x: -0.25, y: 0.03, h: 0.18, s: 0.34 },
        { x: 0.36, y: 0.48, h: 0.16, s: 0.3 },
    ],
    holes: [
        { x: -0.25, y: 0.03, rx: 0.21, ry: 0.12, rot: -0.35 },
        { x: 0.36, y: 0.48, rx: 0.15, ry: 0.085, rot: 0.5 },
    ],
    glows: [
        { x: -0.6, y: 0.35, c: "235,203,139" },
        { x: 0.6, y: 0.0, c: "129,161,193" },
        { x: -0.05, y: 0.45, c: "196,167,214" },
    ],
    labels: [
        { name: "Mechanics", x: -0.62, y: 0.38, dx: -48, dy: -52, tf: "translate(-100%, -100%)", topic: "mechanics" },
        { name: "E and M", x: 0.55, y: 0.02, dx: 56, dy: -66, tf: "translate(0, -100%)", topic: "electromagnetism" },
        {
            name: "Thermodynamics",
            x: -0.3,
            y: 0.55,
            dx: -60,
            dy: 56,
            tf: "translate(-100%, 0)",
            topic: "thermodynamics",
        },
        { name: "Quantum", x: 0.5, y: 0.55, dx: 44, dy: 60, tf: "translate(0, 0)", topic: "quantum" },
    ],
};

// Full nine-unit syllabus surface for the desktop Home hero.
export const FULL_SURFACE: Surface = {
    boundary: [1.12, 0.09, 2.6, 0.2, 0.55],
    spread: 0.42,
    bumps: [
        { x: -0.6, y: -0.5, h: 0.52, s: 0.3 },
        { x: 0.56, y: -0.48, h: 0.62, s: 0.32 },
        { x: 1.0, y: -0.14, h: 0.32, s: 0.26 },
        { x: -1.05, y: 0.14, h: 0.42, s: 0.3 },
        { x: 0.16, y: 0.6, h: 0.48, s: 0.31 },
        { x: 0.72, y: 0.4, h: 0.28, s: 0.24 },
        { x: -0.56, y: 0.62, h: 0.26, s: 0.26 },
        { x: -0.05, y: -0.62, h: 0.22, s: 0.24 },
        { x: 0.16, y: 0.04, h: 0.16, s: 0.19 },
    ],
    dips: [
        { x: -0.34, y: 0.04, h: 0.14, s: 0.3 },
        { x: 0.62, y: 0.14, h: 0.11, s: 0.26 },
    ],
    holes: [
        { x: -0.34, y: 0.04, rx: 0.185, ry: 0.11, rot: -0.3 },
        { x: 0.62, y: 0.14, rx: 0.13, ry: 0.08, rot: 0.4 },
    ],
    glows: [
        { x: -0.6, y: -0.5, c: "235,203,139" },
        { x: 0.56, y: -0.48, c: "129,161,193" },
        { x: 0.16, y: 0.6, c: "196,167,214" },
        { x: -0.85, y: 0.4, c: "196,167,214" },
    ],
    labels: [
        {
            name: "Classical Mechanics",
            x: -0.6,
            y: -0.5,
            dx: -60,
            dy: -44,
            tf: "translate(-100%, -100%)",
            topic: "mechanics",
        },
        {
            name: "Electromagnetism",
            x: 0.56,
            y: -0.48,
            dx: 30,
            dy: -60,
            tf: "translate(0, -100%)",
            topic: "electromagnetism",
        },
        { name: "Optics & Waves", x: 1.0, y: -0.14, dx: 54, dy: -22, tf: "translate(0, -100%)", topic: "optics_waves" },
        {
            name: "Thermo & Stat Mech",
            x: -1.05,
            y: 0.14,
            dx: -54,
            dy: 26,
            tf: "translate(-100%, 0)",
            topic: "thermodynamics",
        },
        { name: "Quantum Mechanics", x: 0.16, y: 0.6, dx: -60, dy: 190, tf: "translate(-100%, 0)", topic: "quantum" },
        { name: "Atomic Physics", x: 0.72, y: 0.4, dx: 64, dy: 46, tf: "translate(0, 0)", topic: "atomic" },
        {
            name: "Special Relativity",
            x: -0.56,
            y: 0.62,
            dx: -50,
            dy: 62,
            tf: "translate(-100%, 0)",
            topic: "special_relativity",
        },
        { name: "Laboratory Methods", x: -0.05, y: -0.62, dx: 10, dy: -60, tf: "translate(-50%, -100%)", topic: "lab" },
        { name: "Specialized Topics", x: 0.16, y: 0.04, dx: 30, dy: 195, tf: "translate(0, 0)", topic: "specialized" },
    ],
};

const PALETTE = { amber: [255, 192, 84], lilac: [208, 156, 238], blue: [72, 146, 220] };
const PALETTE_LIGHT = { amber: [169, 117, 42], lilac: [126, 101, 147], blue: [94, 129, 172] };

// Reserved score hues as canvas rgb strings, to color a region by its leading statistic.
export const SCORE_COLORS = {
    memory: "235,203,139",
    performance: "129,161,193",
    readiness: "196,167,214",
};

export function boundaryR(surface: Surface, theta: number): number {
    const [a0, a3, p3, a2, p2] = surface.boundary;
    return a0 + a3 * Math.cos(3 * theta + p3) + a2 * Math.cos(2 * theta + p2);
}

export function inHole(surface: Surface, x: number, y: number): boolean {
    return surface.holes.some((h) => {
        const dx = x - h.x;
        const dy = y - h.y;
        const r = h.rot || 0;
        const cs = Math.cos(r);
        const sn = Math.sin(r);
        const u = dx * cs + dy * sn;
        const v = -dx * sn + dy * cs;
        return (u / h.rx) * (u / h.rx) + (v / h.ry) * (v / h.ry) <= 1;
    });
}

export function height(surface: Surface, x: number, y: number): number {
    const g = (cx: number, cy: number, s: number) =>
        Math.exp(-((x - cx) * (x - cx) + (y - cy) * (y - cy)) / (2 * s * s));
    const r = Math.hypot(x, y);
    const R = boundaryR(surface, Math.atan2(y, x));
    const edge = Math.max(0, Math.min(1, (R - r) / 0.35));
    const taper = edge * edge * (3 - 2 * edge);
    let z = 0;
    for (const b of surface.bumps) {
        z += b.h * g(b.x, b.y, b.s);
    }
    for (const d of surface.dips) {
        z -= d.h * g(d.x, d.y, d.s);
    }
    let floor = 1;
    for (const h of surface.holes) {
        const dx = x - h.x;
        const dy = y - h.y;
        const rr = h.rot || 0;
        const cs = Math.cos(rr);
        const sn = Math.sin(rr);
        const u = dx * cs + dy * sn;
        const v = -dx * sn + dy * cs;
        const e = Math.sqrt(Math.pow(u / (h.rx * 1.7), 2) + Math.pow(v / (h.ry * 1.7), 2));
        const w = Math.max(0, Math.min(1, (e - 0.588) / 0.412));
        floor *= w * w * (3 - 2 * w);
    }
    return z * taper * floor;
}

export function project(x: number, y: number, z: number, opts: ProjectOpts): { X: number; Y: number; t: number } {
    const A = -0.5;
    const xr = x * Math.cos(A) - y * Math.sin(A);
    const yr = x * Math.sin(A) + y * Math.cos(A);
    const S = opts.S;
    const per = 1 + (xr + yr) * 0.14;
    return {
        X: opts.W / 2 + (xr - yr) * 0.92 * S * per,
        Y: opts.H * 0.52 + ((xr + yr) * 0.42 - z * 0.92) * S * per,
        t: Math.max(0, Math.min(1, ((xr - yr) + 1.55) / 3.1)),
    };
}

export function palette(t: number, theme?: string): number[] {
    const { amber: a, lilac: m, blue: b } = theme === "light" ? PALETTE_LIGHT : PALETTE;
    const lerp = (p: number[], q: number[], u: number) => p.map((v, i) => v + (q[i] - v) * u);
    const c = t < 0.5 ? lerp(a, m, t * 2) : lerp(m, b, (t - 0.5) * 2);
    return c.map(Math.round);
}

export function colorAt(surface: Surface, x: number, y: number, theme?: string): number[] {
    let r = 0;
    let g = 0;
    let b = 0;
    let w = 0;
    for (const s of surface.glows) {
        const c = s.c.split(",").map(Number);
        const d2 = (x - s.x) * (x - s.x) + (y - s.y) * (y - s.y);
        const k = Math.exp(-d2 / (surface.spread || 0.3));
        r += c[0] * k;
        g += c[1] * k;
        b += c[2] * k;
        w += k;
    }
    if (!w) {
        return [128, 128, 128];
    }
    const rr = r / w;
    const gg = g / w;
    const bb = b / w;
    const avg = (rr + gg + bb) / 3;
    const cl = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
    const mul = theme === "light" ? 0.55 : 1;
    return [cl((avg + (rr - avg) * 1.6) * mul), cl((avg + (gg - avg) * 1.6) * mul), cl((avg + (bb - avg) * 1.6) * mul)];
}

// Draws onto `canvas` and returns projected label positions.
export function drawManifold(canvas: HTMLCanvasElement, opts: ManifoldOpts = {}): ProjectedLabel[] {
    const surface = opts.surface || DEFAULT_SURFACE;
    const W = opts.W || 828;
    const H = opts.H || 540;
    const dpr = opts.dpr || 2;
    const S = opts.S || 182;
    const glow = opts.glow ?? 0.7;
    const fill = opts.fill ?? 1;
    const theme = opts.theme;
    const n = opts.grid || 64;
    const po: ProjectOpts = { W, H, S };

    const ctx = canvas.getContext("2d");
    if (!ctx) {
        return [];
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const glowR = S * 1.2;
    for (const g of surface.glows) {
        const p = project(g.x, g.y, 0, po);
        const rg = ctx.createRadialGradient(p.X, p.Y, 0, p.X, p.Y, glowR);
        rg.addColorStop(0, "rgba(" + g.c + "," + ((theme === "light" ? 0.11 : 0.07) * glow).toFixed(3) + ")");
        rg.addColorStop(1, "rgba(" + g.c + ",0)");
        ctx.fillStyle = rg;
        ctx.fillRect(p.X - glowR, p.Y - glowR, glowR * 2, glowR * 2);
    }

    const visAt = (x: number, y: number) => {
        const r = Math.hypot(x, y);
        return r <= boundaryR(surface, Math.atan2(y, x)) && !inHole(surface, x, y);
    };
    let lim = 0;
    for (let k = 0; k < 72; k++) {
        lim = Math.max(lim, boundaryR(surface, (k / 72) * Math.PI * 2));
    }
    lim += 0.06;

    interface Sample {
        x: number;
        y: number;
        z: number;
        X: number;
        Y: number;
        vis: boolean;
        c: number[];
        fade: number;
    }
    const sample = (x: number, y: number): Sample => {
        const z = height(surface, x, y);
        const p = project(x, y, z, po);
        const R = boundaryR(surface, Math.atan2(y, x));
        const fade = Math.max(0, Math.min(1, (R - Math.hypot(x, y)) / 0.5));
        return { x, y, z, X: p.X, Y: p.Y, vis: visAt(x, y), c: colorAt(surface, x, y, theme), fade };
    };

    const axisTicks = (cGet: (o: { x: number; y: number }) => number, rGet: (o: Hole) => number) => {
        const M = 400;
        const wArr: number[] = [];
        for (let k = 0; k <= M; k++) {
            const v = -lim + (2 * lim * k) / M;
            let d = 1 + 0.7 * Math.pow(Math.abs(v) / lim, 6);
            for (const h of surface.holes) {
                const s = Math.max(0.12, rGet(h) * 1.3);
                d += 1.6 * Math.exp(-Math.pow(v - cGet(h), 2) / (2 * s * s));
            }
            for (const b of surface.bumps) {
                d -= 0.6 * (b.h / 0.5) * Math.exp(-Math.pow(v - cGet(b), 2) / (2 * b.s * b.s));
            }
            wArr.push(Math.max(0.3, d));
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
    const pts: Sample[][] = [];
    for (let i = 0; i <= n; i++) {
        pts.push([]);
        for (let j = 0; j <= n; j++) {
            pts[i].push(sample(xs[i], ys[j]));
        }
    }

    const clip = (a: Sample, b: Sample): Sample => {
        let lo = 0;
        let hi = 1;
        for (let k = 0; k < 9; k++) {
            const mid = (lo + hi) / 2;
            if (visAt(a.x + (b.x - a.x) * mid, a.y + (b.y - a.y) * mid)) {
                lo = mid;
            } else {
                hi = mid;
            }
        }
        return sample(a.x + (b.x - a.x) * lo, a.y + (b.y - a.y) * lo);
    };

    const fillBase = theme === "light" ? 0.06 : 0.05;
    const fillGain = theme === "light" ? 0.7 : 0.85;
    for (let i = 0; i < n; i++) {
        for (let j = 0; j < n; j++) {
            const A = pts[i][j];
            const B = pts[i + 1][j];
            const C = pts[i + 1][j + 1];
            const D = pts[i][j + 1];
            if (!A.vis || !B.vis || !C.vis || !D.vis) {
                continue;
            }
            const zc = Math.max(0, (A.z + B.z + C.z + D.z) / 4);
            const fadeC = (A.fade + B.fade + C.fade + D.fade) / 4;
            const alpha = fill * glow * (0.35 + 0.65 * fadeC) * (fillBase + fillGain * Math.pow(zc, 1.4));
            if (alpha < 0.004) {
                continue;
            }
            const c = [
                Math.round((A.c[0] + B.c[0] + C.c[0] + D.c[0]) / 4),
                Math.round((A.c[1] + B.c[1] + C.c[1] + D.c[1]) / 4),
                Math.round((A.c[2] + B.c[2] + C.c[2] + D.c[2]) / 4),
            ];
            ctx.fillStyle = "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + Math.min(0.5, alpha).toFixed(3) + ")";
            ctx.beginPath();
            ctx.moveTo(A.X, A.Y);
            ctx.lineTo(B.X, B.Y);
            ctx.lineTo(C.X, C.Y);
            ctx.lineTo(D.X, D.Y);
            ctx.closePath();
            ctx.fill();
        }
    }

    ctx.lineWidth = opts.lineWidth || 0.8;
    ctx.lineCap = "round";
    const stroke = (a: Sample, b: Sample) => {
        const z = (a.z + b.z) / 2;
        const c = [
            Math.round((a.c[0] + b.c[0]) / 2),
            Math.round((a.c[1] + b.c[1]) / 2),
            Math.round((a.c[2] + b.c[2]) / 2),
        ];
        const fd = 0.6 + (0.4 * (a.fade + b.fade)) / 2;
        const alpha = Math.min(0.85, glow * fd * ((theme === "light" ? 0.55 : 0.46) + 1.5 * Math.max(0, z)));
        ctx.strokeStyle = "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + alpha.toFixed(3) + ")";
        ctx.beginPath();
        ctx.moveTo(a.X, a.Y);
        ctx.lineTo(b.X, b.Y);
        ctx.stroke();
    };
    const seg = (a: Sample, b: Sample) => {
        if (a.vis && b.vis) {
            stroke(a, b);
        } else if (a.vis && !b.vis) {
            stroke(a, clip(a, b));
        } else if (!a.vis && b.vis) {
            stroke(clip(b, a), b);
        }
    };
    for (let i = 0; i <= n; i++) {
        for (let j = 0; j <= n; j++) {
            if (i < n) {
                seg(pts[i][j], pts[i + 1][j]);
            }
            if (j < n) {
                seg(pts[i][j], pts[i][j + 1]);
            }
        }
    }

    const rimAlpha = Math.min(0.9, glow * (theme === "light" ? 0.5 : 0.55));
    ctx.lineWidth = (opts.lineWidth || 0.8) * 1.25;
    const rim = (samples: Sample[]) => {
        for (let k = 0; k < samples.length; k++) {
            const a = samples[k];
            const b = samples[(k + 1) % samples.length];
            const c = [
                Math.round((a.c[0] + b.c[0]) / 2),
                Math.round((a.c[1] + b.c[1]) / 2),
                Math.round((a.c[2] + b.c[2]) / 2),
            ];
            ctx.strokeStyle = "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + rimAlpha.toFixed(3) + ")";
            ctx.beginPath();
            ctx.moveTo(a.X, a.Y);
            ctx.lineTo(b.X, b.Y);
            ctx.stroke();
        }
    };
    const bnd: Sample[] = [];
    for (let k = 0; k < 220; k++) {
        const th = (k / 220) * Math.PI * 2;
        const R = boundaryR(surface, th);
        bnd.push(sample(R * Math.cos(th), R * Math.sin(th)));
    }
    rim(bnd);
    for (const h of surface.holes) {
        const rr = h.rot || 0;
        const cs = Math.cos(rr);
        const sn = Math.sin(rr);
        const e: Sample[] = [];
        for (let k = 0; k < 140; k++) {
            const th = (k / 140) * Math.PI * 2;
            const u = h.rx * Math.cos(th);
            const v = h.ry * Math.sin(th);
            e.push(sample(h.x + u * cs - v * sn, h.y + u * sn + v * cs));
        }
        rim(e);
    }

    const ink = theme === "light" ? [38, 38, 36] : [236, 234, 227];
    const mixK = theme === "light" ? 0.18 : 0.35;
    return surface.labels.map((l) => {
        const p = project(l.x, l.y, height(surface, l.x, l.y), po);
        const cc = colorAt(surface, l.x, l.y, theme).map((v, i) => Math.round(v + (ink[i] - v) * mixK));
        return {
            name: l.name,
            ax: p.X,
            ay: p.Y,
            lx: p.X + l.dx,
            ly: p.Y + l.dy,
            tf: l.tf,
            c: "rgb(" + cc.join(",") + ")",
            topic: l.topic,
        };
    });
}

export interface TopicStat {
    name: string;
    x: number;
    y: number;
    /** Blueprint share, 0..1, drives the footprint size */
    weight: number;
    /** 0..1, drives the peak height */
    performance: number;
    /** 0..1, below the threshold the topic becomes a hole */
    coverage: number;
    /** The leading score, drives the region hue */
    lead: "memory" | "performance" | "readiness";
    dx: number;
    dy: number;
    tf: string;
    /** Blueprint category slug, so a built region can launch its focus drill. */
    topic?: string;
}

// Turn live per-topic stats into a Surface. This is the data link:
// performance drives peak height, blueprint weight drives footprint, the
// leading score drives the region hue, and coverage below the line turns a
// topic into an actual hole, a gap you cannot fake readiness over.
export function buildSurface(topics: TopicStat[], coverageThreshold = 0.4): Surface {
    const bumps: Bump[] = [];
    const dips: Bump[] = [];
    const holes: Hole[] = [];
    const glows: Glow[] = [];
    const labels: ManifoldLabel[] = [];
    for (const t of topics) {
        const footprint = 0.22 + t.weight * 0.9;
        glows.push({ x: t.x, y: t.y, c: SCORE_COLORS[t.lead] });
        labels.push({ name: t.name, x: t.x, y: t.y, dx: t.dx, dy: t.dy, tf: t.tf, topic: t.topic });
        if (t.coverage < coverageThreshold) {
            const rr = 0.1 + t.weight * 0.55;
            holes.push({ x: t.x, y: t.y, rx: rr, ry: rr * 0.7 });
            dips.push({ x: t.x, y: t.y, h: 0.16, s: footprint });
        } else {
            bumps.push({ x: t.x, y: t.y, h: 0.1 + t.performance * 0.55, s: footprint });
        }
    }
    return { boundary: FULL_SURFACE.boundary, spread: 0.42, bumps, dips, holes, glows, labels };
}
