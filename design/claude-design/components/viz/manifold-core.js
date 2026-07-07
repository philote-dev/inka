// manifold.js — shared knowledge-manifold renderer for pgrep mockups.
// Same math and structure as the desktop Home hero. Fully data driven:
// pass a `surface` object built from live stats and every peak, hole,
// glow and label follows. The production Three.js version consumes the
// identical structure (bumps -> vertex displacement, holes -> alpha mask).
//
// surface = {
//   boundary: [a0, a3, p3, a2, p2]   // blob radius harmonics
//   bumps:  [{ x, y, h, s }]         // topic peaks. h = Performance, s = footprint
//   dips:   [{ x, y, h, s }]         // rim sinks around gaps
//   holes:  [{ x, y, rx, ry }]       // knowledge gaps (no data -> no surface)
//   glows:  [{ x, y, c }]            // soft under-glow, rgb string
//   labels: [{ name, x, y, dx, dy, tf }]
// }

export const DEFAULT_SURFACE = {
    boundary: [1.04, 0.13, 0.7, 0.05, -1.2],
    bumps: [
        { x: -0.58, y: 0.3, h: 0.40, s: 0.36 },
        { x: 0.55, y: 0.0, h: 0.42, s: 0.38 },
        { x: -0.05, y: 0.6, h: 0.28, s: 0.32 },
        { x: 0.1, y: -0.62, h: 0.14, s: 0.4 },
    ],
    dips: [
        { x: -0.3, y: 0.04, h: 0.10, s: 0.32 },
        { x: 0.38, y: 0.52, h: 0.08, s: 0.28 },
        { x: 0.0, y: 0.15, h: 0.06, s: 0.3 },
    ],
    holes: [
        { x: -0.3, y: 0.04, rx: 0.21, ry: 0.14 },
        { x: 0.38, y: 0.52, rx: 0.16, ry: 0.11 },
    ],
    glows: [
        { x: -0.55, y: 0.28, c: "235,203,139" },
        { x: 0.52, y: 0.05, c: "129,161,193" },
        { x: 0.0, y: -0.4, c: "196,167,214" },
    ],
    labels: [
        { name: "Mechanics", x: -0.58, y: 0.3, dx: -52, dy: -56, tf: "translate(-100%, -100%)" },
        { name: "E and M", x: 0.55, y: 0.0, dx: 56, dy: -66, tf: "translate(0, -100%)" },
        { name: "Quantum", x: -0.05, y: 0.6, dx: -44, dy: 88, tf: "translate(-100%, 0)" },
    ],
};

const PALETTE = {
    amber: [255, 192, 84],
    lilac: [208, 156, 238],
    blue: [72, 146, 220],
};

export function boundaryR(surface, theta) {
    const [a0, a3, p3, a2, p2] = surface.boundary;
    return a0 + a3 * Math.cos(3 * theta + p3) + a2 * Math.cos(2 * theta + p2);
}

export function inHole(surface, x, y) {
    return surface.holes.some(h => Math.pow((x - h.x) / h.rx, 2) + Math.pow((y - h.y) / h.ry, 2) <= 1);
}

export function height(surface, x, y) {
    const g = (cx, cy, s) => Math.exp(-((x - cx) * (x - cx) + (y - cy) * (y - cy)) / (2 * s * s));
    const r = Math.hypot(x, y);
    const R = boundaryR(surface, Math.atan2(y, x));
    const edge = Math.max(0, Math.min(1, (R - r) / 0.35));
    const taper = edge * edge * (3 - 2 * edge);
    let z = 0;
    for (const b of surface.bumps) { z += b.h * g(b.x, b.y, b.s); }
    for (const d of surface.dips) { z -= d.h * g(d.x, d.y, d.s); }
    return z * taper;
}

export function project(x, y, z, opts) {
    const A = -0.5;
    const xr = x * Math.cos(A) - y * Math.sin(A);
    const yr = x * Math.sin(A) + y * Math.cos(A);
    const S = opts.S;
    return {
        X: opts.W / 2 + (xr - yr) * 0.92 * S,
        Y: opts.H * 0.5 + (xr + yr) * 0.58 * S - z * 0.68 * S,
        t: Math.max(0, Math.min(1, ((xr - yr) + 1.55) / 3.1)),
    };
}

export function palette(t) {
    const { amber: a, lilac: m, blue: b } = PALETTE;
    const lerp = (p, q, u) => p.map((v, i) => v + (q[i] - v) * u);
    const c = t < 0.5 ? lerp(a, m, t * 2) : lerp(m, b, (t - 0.5) * 2);
    return c.map(Math.round);
}

// Draws onto `canvas` and returns projected label positions.
// opts = { W, H, S, dpr = 2, glow = 0.7, grid = 64, lineWidth = 0.8, surface = DEFAULT_SURFACE }
export function drawManifold(canvas, opts = {}) {
    const surface = opts.surface || DEFAULT_SURFACE;
    const W = opts.W || 828, H = opts.H || 540, dpr = opts.dpr || 2;
    const S = opts.S || 182;
    const glow = opts.glow ?? 0.7;
    const n = opts.grid || 64;
    const po = { W, H, S };

    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const glowR = S * 1.2;
    for (const g of surface.glows) {
        const p = project(g.x, g.y, 0, po);
        const rg = ctx.createRadialGradient(p.X, p.Y, 0, p.X, p.Y, glowR);
        rg.addColorStop(0, "rgba(" + g.c + "," + (0.07 * glow).toFixed(3) + ")");
        rg.addColorStop(1, "rgba(" + g.c + ",0)");
        ctx.fillStyle = rg;
        ctx.fillRect(p.X - glowR, p.Y - glowR, glowR * 2, glowR * 2);
    }

    const lim = 1.22;
    const pts = [];
    for (let i = 0; i <= n; i++) {
        pts.push([]);
        for (let j = 0; j <= n; j++) {
            const x = -lim + (2 * lim * i) / n;
            const y = -lim + (2 * lim * j) / n;
            const r = Math.hypot(x, y);
            const R = boundaryR(surface, Math.atan2(y, x));
            const vis = r <= R && !inHole(surface, x, y);
            const z = height(surface, x, y);
            const p = project(x, y, z, po);
            pts[i].push({ vis, X: p.X, Y: p.Y, t: p.t, z });
        }
    }

    ctx.lineWidth = opts.lineWidth || 0.8;
    ctx.lineCap = "round";
    const seg = (a, b) => {
        if (!a.vis || !b.vis) { return; }
        const t = (a.t + b.t) / 2;
        const z = (a.z + b.z) / 2;
        const c = palette(t);
        const alpha = Math.min(0.85, glow * (0.46 + 1.5 * Math.max(0, z)));
        ctx.strokeStyle = "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + alpha.toFixed(3) + ")";
        ctx.beginPath();
        ctx.moveTo(a.X, a.Y);
        ctx.lineTo(b.X, b.Y);
        ctx.stroke();
    };
    for (let i = 0; i <= n; i++) {
        for (let j = 0; j <= n; j++) {
            if (i < n) { seg(pts[i][j], pts[i + 1][j]); }
            if (j < n) { seg(pts[i][j], pts[i][j + 1]); }
        }
    }

    return surface.labels.map(l => {
        const p = project(l.x, l.y, height(surface, l.x, l.y), po);
        return { name: l.name, ax: p.X, ay: p.Y, lx: p.X + l.dx, ly: p.Y + l.dy, tf: l.tf };
    });
}

// 2D top-down contour fallback (marching squares over the same surface).
// opts = { W, H, S, dpr = 2, glow = 0.8, grid = 80, levels, surface }
export function drawContour(canvas, opts = {}) {
    const surface = opts.surface || DEFAULT_SURFACE;
    const W = opts.W || 380, H = opts.H || 380, dpr = opts.dpr || 2;
    const S = opts.S || Math.min(W, H) / 2.7;
    const glow = opts.glow ?? 0.8;
    const n = opts.grid || 80;
    const levels = opts.levels || [0.05, 0.1, 0.16, 0.22, 0.29, 0.36];
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const px = (x) => W / 2 + x * S;
    const py = (y) => H / 2 + y * S;

    for (const g of surface.glows) {
        const rg = ctx.createRadialGradient(px(g.x), py(g.y), 0, px(g.x), py(g.y), S);
        rg.addColorStop(0, "rgba(" + g.c + "," + (0.08 * glow).toFixed(3) + ")");
        rg.addColorStop(1, "rgba(" + g.c + ",0)");
        ctx.fillStyle = rg;
        ctx.fillRect(px(g.x) - S, py(g.y) - S, S * 2, S * 2);
    }

    // domain boundary and hole rims, quiet
    ctx.strokeStyle = "rgba(165,161,153,0.3)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let k = 0; k <= 120; k++) {
        const th = (k / 120) * Math.PI * 2;
        const R = boundaryR(surface, th);
        const X = px(R * Math.cos(th)), Y = py(R * Math.sin(th));
        if (k === 0) { ctx.moveTo(X, Y); }
        else { ctx.lineTo(X, Y); }
    }
    ctx.stroke();
    ctx.setLineDash([3, 4]);
    for (const h of surface.holes) {
        ctx.beginPath();
        ctx.ellipse(px(h.x), py(h.y), h.rx * S, h.ry * S, 0, 0, Math.PI * 2);
        ctx.stroke();
    }
    ctx.setLineDash([]);

    const lim = 1.25;
    const xs = [], zs = [], vis = [];
    for (let i = 0; i <= n; i++) {
        zs.push([]);
        vis.push([]);
        xs.push(-lim + (2 * lim * i) / n);
        for (let j = 0; j <= n; j++) {
            const x = -lim + (2 * lim * i) / n;
            const y = -lim + (2 * lim * j) / n;
            const r = Math.hypot(x, y);
            const R = boundaryR(surface, Math.atan2(y, x));
            vis[i].push(r <= R && !inHole(surface, x, y));
            zs[i].push(height(surface, x, y));
        }
    }

    const SEG = {
        1: [["da", "ab"]],
        2: [["ab", "bc"]],
        3: [["da", "bc"]],
        4: [["bc", "cd"]],
        5: [["da", "ab"], ["bc", "cd"]],
        6: [["ab", "cd"]],
        7: [["da", "cd"]],
        8: [["cd", "da"]],
        9: [["ab", "cd"]],
        10: [["ab", "bc"], ["cd", "da"]],
        11: [["bc", "cd"]],
        12: [["bc", "da"]],
        13: [["ab", "bc"]],
        14: [["ab", "da"]],
    };
    ctx.lineWidth = 1;
    ctx.lineCap = "round";
    for (let i = 0; i < n; i++) {
        for (let j = 0; j < n; j++) {
            if (!vis[i][j] || !vis[i + 1][j] || !vis[i][j + 1] || !vis[i + 1][j + 1]) { continue; }
            const x0 = -lim + (2 * lim * i) / n, x1 = -lim + (2 * lim * (i + 1)) / n;
            const y0 = -lim + (2 * lim * j) / n, y1 = -lim + (2 * lim * (j + 1)) / n;
            const za = zs[i][j], zb = zs[i + 1][j], zc = zs[i + 1][j + 1], zd = zs[i][j + 1];
            for (let li = 0; li < levels.length; li++) {
                const L = levels[li];
                const code = (za > L ? 1 : 0) | (zb > L ? 2 : 0) | (zc > L ? 4 : 0) | (zd > L ? 8 : 0);
                const segs = SEG[code];
                if (!segs) { continue; }
                const ept = (e) => {
                    if (e === "ab") {
                        const t = (L - za) / (zb - za);
                        return [x0 + t * (x1 - x0), y0];
                    }
                    if (e === "bc") {
                        const t = (L - zb) / (zc - zb);
                        return [x1, y0 + t * (y1 - y0)];
                    }
                    if (e === "cd") {
                        const t = (L - zd) / (zc - zd);
                        return [x0 + t * (x1 - x0), y1];
                    }
                    const t = (L - za) / (zd - za);
                    return [x0, y0 + t * (y1 - y0)];
                };
                const tcol = Math.max(0, Math.min(1, ((x0 + x1) / 2 + 1.25) / 2.5));
                const c = palette(tcol);
                const alpha = Math.min(0.9, glow * (0.35 + 0.12 * li));
                ctx.strokeStyle = "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + alpha.toFixed(3) + ")";
                for (const [e1, e2] of segs) {
                    const p1 = ept(e1), p2 = ept(e2);
                    ctx.beginPath();
                    ctx.moveTo(px(p1[0]), py(p1[1]));
                    ctx.lineTo(px(p2[0]), py(p2[1]));
                    ctx.stroke();
                }
            }
        }
    }
}
