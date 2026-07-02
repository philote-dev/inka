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
    { x: -0.62, y: 0.38, h: 0.52, s: 0.38 },
    { x: 0.55, y: 0.02, h: 0.55, s: 0.42 },
    { x: 0.05, y: 0.62, h: 0.24, s: 0.34 },
    { x: -0.05, y: -0.55, h: 0.22, s: 0.38 }
  ],
  dips: [
    { x: 0.0, y: 0.12, h: 0.1, s: 0.35 },
    { x: -0.25, y: 0.03, h: 0.18, s: 0.34 },
    { x: 0.36, y: 0.48, h: 0.16, s: 0.3 }
  ],
  holes: [
    { x: -0.25, y: 0.03, rx: 0.21, ry: 0.12, rot: -0.35 },
    { x: 0.36, y: 0.48, rx: 0.15, ry: 0.085, rot: 0.5 }
  ],
  glows: [
    { x: -0.6, y: 0.35, c: '235,203,139' },
    { x: 0.6, y: 0.0, c: '129,161,193' },
    { x: -0.05, y: 0.45, c: '196,167,214' }
  ],
  labels: [
    { name: 'Mechanics', x: -0.62, y: 0.38, dx: -48, dy: -52, tf: 'translate(-100%, -100%)' },
    { name: 'E and M', x: 0.55, y: 0.02, dx: 56, dy: -66, tf: 'translate(0, -100%)' },
    { name: 'Thermodynamics', x: -0.3, y: 0.55, dx: -60, dy: 56, tf: 'translate(-100%, 0)' },
    { name: 'Quantum', x: 0.5, y: 0.55, dx: 44, dy: 60, tf: 'translate(0, 0)' }
  ]
};

// Full nine-unit syllabus surface for the desktop Home hero. Wider,
// elongated footprint (screen-diagonal major axis) so all nine units keep
// distinct peaks with no overlap. DEFAULT_SURFACE stays the compact
// four-peak form for small embeds (mobile, diagnostic card, library).
export const FULL_SURFACE = {
  boundary: [1.12, 0.09, 2.6, 0.2, 0.55],
  spread: 0.42,
  bumps: [
    { x: -0.6, y: -0.5, h: 0.52, s: 0.3 },     // Classical Mechanics
    { x: 0.56, y: -0.48, h: 0.62, s: 0.32 },   // Electromagnetism
    { x: 1.0, y: -0.14, h: 0.32, s: 0.26 },    // Optics & Waves
    { x: -1.05, y: 0.14, h: 0.42, s: 0.3 },    // Thermo & Stat Mech
    { x: 0.16, y: 0.6, h: 0.48, s: 0.31 },     // Quantum Mechanics
    { x: 0.72, y: 0.4, h: 0.28, s: 0.24 },     // Atomic Physics
    { x: -0.56, y: 0.62, h: 0.26, s: 0.26 },   // Special Relativity
    { x: -0.05, y: -0.62, h: 0.22, s: 0.24 },  // Laboratory Methods
    { x: 0.16, y: 0.04, h: 0.16, s: 0.19 }     // Specialized Topics
  ],
  dips: [
    { x: -0.34, y: 0.04, h: 0.14, s: 0.3 },
    { x: 0.62, y: 0.14, h: 0.11, s: 0.26 }
  ],
  holes: [
    { x: -0.34, y: 0.04, rx: 0.185, ry: 0.11, rot: -0.3 },
    { x: 0.62, y: 0.14, rx: 0.13, ry: 0.08, rot: 0.4 }
  ],
  glows: [
    { x: -0.6, y: -0.5, c: '235,203,139' },
    { x: 0.56, y: -0.48, c: '129,161,193' },
    { x: 0.16, y: 0.6, c: '196,167,214' },
    { x: -0.85, y: 0.4, c: '196,167,214' }
  ],
  labels: [
    { name: 'Classical Mechanics', x: -0.6, y: -0.5, dx: -60, dy: -44, tf: 'translate(-100%, -100%)' },
    { name: 'Electromagnetism', x: 0.56, y: -0.48, dx: 30, dy: -60, tf: 'translate(0, -100%)' },
    { name: 'Optics & Waves', x: 1.0, y: -0.14, dx: 54, dy: -22, tf: 'translate(0, -100%)' },
    { name: 'Thermo & Stat Mech', x: -1.05, y: 0.14, dx: -54, dy: 26, tf: 'translate(-100%, 0)' },
    { name: 'Quantum Mechanics', x: 0.16, y: 0.6, dx: -60, dy: 190, tf: 'translate(-100%, 0)' },
    { name: 'Atomic Physics', x: 0.72, y: 0.4, dx: 64, dy: 46, tf: 'translate(0, 0)' },
    { name: 'Special Relativity', x: -0.56, y: 0.62, dx: -50, dy: 62, tf: 'translate(-100%, 0)' },
    { name: 'Laboratory Methods', x: -0.05, y: -0.62, dx: 10, dy: -60, tf: 'translate(-50%, -100%)' },
    { name: 'Specialized Topics', x: 0.16, y: 0.04, dx: 30, dy: 195, tf: 'translate(0, 0)' }
  ]
};

const PALETTE = {
  amber: [255, 192, 84],
  lilac: [208, 156, 238],
  blue: [72, 146, 220]
};

// Darker ink variants for light mode. Same ramp, paper-legible.
const PALETTE_LIGHT = {
  amber: [169, 117, 42],
  lilac: [126, 101, 147],
  blue: [94, 129, 172]
};

// Reserved score hues as canvas rgb strings. Feed these into surface.glows
// to color a marked region by its leading statistic.
export const SCORE_COLORS = {
  memory: '235,203,139',
  performance: '129,161,193',
  readiness: '196,167,214'
};

export function boundaryR(surface, theta) {
  const [a0, a3, p3, a2, p2] = surface.boundary;
  return a0 + a3 * Math.cos(3 * theta + p3) + a2 * Math.cos(2 * theta + p2);
}

export function inHole(surface, x, y) {
  return surface.holes.some(h => {
    const dx = x - h.x, dy = y - h.y, r = h.rot || 0;
    const cs = Math.cos(r), sn = Math.sin(r);
    const u = dx * cs + dy * sn, v = -dx * sn + dy * cs;
    return (u / h.rx) * (u / h.rx) + (v / h.ry) * (v / h.ry) <= 1;
  });
}

export function height(surface, x, y) {
  const g = (cx, cy, s) => Math.exp(-((x - cx) * (x - cx) + (y - cy) * (y - cy)) / (2 * s * s));
  const r = Math.hypot(x, y);
  const R = boundaryR(surface, Math.atan2(y, x));
  const edge = Math.max(0, Math.min(1, (R - r) / 0.35));
  const taper = edge * edge * (3 - 2 * edge);
  let z = 0;
  for (const b of surface.bumps) z += b.h * g(b.x, b.y, b.s);
  for (const d of surface.dips) z -= d.h * g(d.x, d.y, d.s);
  // Ground-zero holes. The surface tapers down to the base plane at every
  // hole rim, same plane the outer boundary sits on, so gaps read as holes.
  let floor = 1;
  for (const h of surface.holes) {
    const dx = x - h.x, dy = y - h.y, rr = h.rot || 0;
    const cs = Math.cos(rr), sn = Math.sin(rr);
    const u = dx * cs + dy * sn, v = -dx * sn + dy * cs;
    const e = Math.sqrt(Math.pow(u / (h.rx * 1.7), 2) + Math.pow(v / (h.ry * 1.7), 2));
    const w = Math.max(0, Math.min(1, (e - 0.588) / 0.412));
    floor *= w * w * (3 - 2 * w);
  }
  return z * taper * floor;
}

export function project(x, y, z, opts) {
  const A = -0.5;
  const xr = x * Math.cos(A) - y * Math.sin(A);
  const yr = x * Math.sin(A) + y * Math.cos(A);
  const S = opts.S;
  // Lower, more isometric camera with mild perspective. Near cells grow,
  // far cells shrink, so mesh density follows the form.
  const per = 1 + (xr + yr) * 0.14;
  return {
    X: opts.W / 2 + (xr - yr) * 0.92 * S * per,
    Y: opts.H * 0.52 + ((xr + yr) * 0.42 - z * 0.92) * S * per,
    t: Math.max(0, Math.min(1, ((xr - yr) + 1.55) / 3.1))
  };
}

export function palette(t, theme) {
  const { amber: a, lilac: m, blue: b } = theme === 'light' ? PALETTE_LIGHT : PALETTE;
  const lerp = (p, q, u) => p.map((v, i) => v + (q[i] - v) * u);
  const c = t < 0.5 ? lerp(a, m, t * 2) : lerp(m, b, (t - 0.5) * 2);
  return c.map(Math.round);
}

// Region-based color. Each glow source stains the surface around it, so
// hue follows the topic domes instead of a flat screen-space ramp.
export function colorAt(surface, x, y, theme) {
  let r = 0, g = 0, b = 0, w = 0;
  for (const s of surface.glows) {
    const c = s.c.split(',').map(Number);
    const d2 = (x - s.x) * (x - s.x) + (y - s.y) * (y - s.y);
    const k = Math.exp(-d2 / (surface.spread || 0.3));
    r += c[0] * k; g += c[1] * k; b += c[2] * k; w += k;
  }
  if (!w) return [128, 128, 128];
  let rr = r / w, gg = g / w, bb = b / w;
  // Re-saturate after blending so regions keep their hue.
  const avg = (rr + gg + bb) / 3;
  const cl = (v) => Math.max(0, Math.min(255, Math.round(v)));
  const m = theme === 'light' ? 0.55 : 1;
  return [cl((avg + (rr - avg) * 1.6) * m), cl((avg + (gg - avg) * 1.6) * m), cl((avg + (bb - avg) * 1.6) * m)];
}

// Draws onto `canvas` and returns projected label positions.
// opts = { W, H, S, dpr = 2, glow = 0.7, grid = 64, lineWidth = 0.8, surface = DEFAULT_SURFACE }
export function drawManifold(canvas, opts = {}) {
  const surface = opts.surface || DEFAULT_SURFACE;
  const W = opts.W || 828, H = opts.H || 540, dpr = opts.dpr || 2;
  const S = opts.S || 182;
  const glow = opts.glow ?? 0.7;
  const fill = opts.fill ?? 1;
  const theme = opts.theme;
  const n = opts.grid || 64;
  const po = { W, H, S };

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const glowR = S * 1.2;
  for (const g of surface.glows) {
    const p = project(g.x, g.y, 0, po);
    const rg = ctx.createRadialGradient(p.X, p.Y, 0, p.X, p.Y, glowR);
    rg.addColorStop(0, 'rgba(' + g.c + ',' + ((theme === 'light' ? 0.11 : 0.07) * glow).toFixed(3) + ')');
    rg.addColorStop(1, 'rgba(' + g.c + ',0)');
    ctx.fillStyle = rg;
    ctx.fillRect(p.X - glowR, p.Y - glowR, glowR * 2, glowR * 2);
  }

  const visAt = (x, y) => {
    const r = Math.hypot(x, y);
    return r <= boundaryR(surface, Math.atan2(y, x)) && !inHole(surface, x, y);
  };
  // Sampling window follows the actual blob extent, so larger surfaces
  // (FULL_SURFACE) never clip against a fixed limit.
  let lim = 0;
  for (let k = 0; k < 72; k++) lim = Math.max(lim, boundaryR(surface, (k / 72) * Math.PI * 2));
  lim += 0.06;
  const sample = (x, y) => {
    const z = height(surface, x, y);
    const p = project(x, y, z, po);
    const R = boundaryR(surface, Math.atan2(y, x));
    const fade = Math.max(0, Math.min(1, (R - Math.hypot(x, y)) / 0.5));
    return { x, y, z, X: p.X, Y: p.Y, vis: visAt(x, y), c: colorAt(surface, x, y, theme), fade };
  };

  // Data-driven grid density. Lines crowd around holes and the outer edge,
  // and spread out across the peak tops.
  const axisTicks = (cGet, rGet) => {
    const M = 400, w = [];
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
      w.push(Math.max(0.3, d));
    }
    const cum = [0];
    for (let k = 1; k <= M; k++) cum.push(cum[k - 1] + (w[k - 1] + w[k]) / 2);
    const ticks = [];
    let k = 0;
    for (let i = 0; i <= n; i++) {
      const target = (cum[M] * i) / n;
      while (k < M - 1 && cum[k + 1] < target) k++;
      const f = Math.min(1, Math.max(0, (target - cum[k]) / ((cum[k + 1] - cum[k]) || 1)));
      ticks.push(-lim + (2 * lim * (k + f)) / M);
    }
    return ticks;
  };
  const xs = axisTicks(o => o.x, o => o.rx);
  const ys = axisTicks(o => o.y, o => o.ry);
  const pts = [];
  for (let i = 0; i <= n; i++) {
    pts.push([]);
    for (let j = 0; j <= n; j++) {
      pts[i].push(sample(xs[i], ys[j]));
    }
  }

  // Walk a segment endpoint to the exact blob edge or hole rim, so the
  // mesh ends cleanly instead of stair-stepping.
  const clip = (a, b) => {
    let lo = 0, hi = 1;
    for (let k = 0; k < 9; k++) {
      const mid = (lo + hi) / 2;
      if (visAt(a.x + (b.x - a.x) * mid, a.y + (b.y - a.y) * mid)) lo = mid; else hi = mid;
    }
    return sample(a.x + (b.x - a.x) * lo, a.y + (b.y - a.y) * lo);
  };

  // Soft gradient fill inside each grid cell. Height feeds luminosity.
  const fillBase = theme === 'light' ? 0.06 : 0.05;
  const fillGain = theme === 'light' ? 0.7 : 0.85;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const A = pts[i][j], B = pts[i + 1][j], C = pts[i + 1][j + 1], D = pts[i][j + 1];
      if (!A.vis || !B.vis || !C.vis || !D.vis) continue;
      const zc = Math.max(0, (A.z + B.z + C.z + D.z) / 4);
      const fadeC = (A.fade + B.fade + C.fade + D.fade) / 4;
      const alpha = fill * glow * (0.35 + 0.65 * fadeC) * (fillBase + fillGain * Math.pow(zc, 1.4));
      if (alpha < 0.004) continue;
      const c = [(A.c[0] + B.c[0] + C.c[0] + D.c[0]) >> 2, (A.c[1] + B.c[1] + C.c[1] + D.c[1]) >> 2, (A.c[2] + B.c[2] + C.c[2] + D.c[2]) >> 2];
      ctx.fillStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + Math.min(0.5, alpha).toFixed(3) + ')';
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
  ctx.lineCap = 'round';
  const stroke = (a, b) => {
    const z = (a.z + b.z) / 2;
    const c = [(a.c[0] + b.c[0]) >> 1, (a.c[1] + b.c[1]) >> 1, (a.c[2] + b.c[2]) >> 1];
    const fd = 0.6 + 0.4 * (a.fade + b.fade) / 2;
    const alpha = Math.min(0.85, glow * fd * ((theme === 'light' ? 0.55 : 0.46) + 1.5 * Math.max(0, z)));
    ctx.strokeStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + alpha.toFixed(3) + ')';
    ctx.beginPath();
    ctx.moveTo(a.X, a.Y);
    ctx.lineTo(b.X, b.Y);
    ctx.stroke();
  };
  const seg = (a, b) => {
    if (a.vis && b.vis) stroke(a, b);
    else if (a.vis && !b.vis) stroke(a, clip(a, b));
    else if (!a.vis && b.vis) stroke(clip(b, a), b);
  };
  for (let i = 0; i <= n; i++) {
    for (let j = 0; j <= n; j++) {
      if (i < n) seg(pts[i][j], pts[i + 1][j]);
      if (j < n) seg(pts[i][j], pts[i][j + 1]);
    }
  }

  // Clean rims. The blob outline and hole edges read as smooth curves.
  const rimAlpha = Math.min(0.9, glow * (theme === 'light' ? 0.5 : 0.55));
  ctx.lineWidth = (opts.lineWidth || 0.8) * 1.25;
  const rim = (samples) => {
    for (let k = 0; k < samples.length; k++) {
      const a = samples[k], b = samples[(k + 1) % samples.length];
      const c = [(a.c[0] + b.c[0]) >> 1, (a.c[1] + b.c[1]) >> 1, (a.c[2] + b.c[2]) >> 1];
      ctx.strokeStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + rimAlpha.toFixed(3) + ')';
      ctx.beginPath();
      ctx.moveTo(a.X, a.Y);
      ctx.lineTo(b.X, b.Y);
      ctx.stroke();
    }
  };
  const bnd = [];
  for (let k = 0; k < 220; k++) {
    const th = (k / 220) * Math.PI * 2;
    const R = boundaryR(surface, th);
    bnd.push(sample(R * Math.cos(th), R * Math.sin(th)));
  }
  rim(bnd);
  for (const h of surface.holes) {
    const rr = h.rot || 0, cs = Math.cos(rr), sn = Math.sin(rr);
    const e = [];
    for (let k = 0; k < 140; k++) {
      const th = (k / 140) * Math.PI * 2;
      const u = h.rx * Math.cos(th), v = h.ry * Math.sin(th);
      e.push(sample(h.x + u * cs - v * sn, h.y + u * sn + v * cs));
    }
    rim(e);
  }

  // Labels carry the region hue (softened toward the ink color) so the
  // callout text matches its dome, like the reference renders.
  const ink = theme === 'light' ? [38, 38, 36] : [236, 234, 227];
  const mixK = theme === 'light' ? 0.18 : 0.35;
  return surface.labels.map(l => {
    const p = project(l.x, l.y, height(surface, l.x, l.y), po);
    const cc = colorAt(surface, l.x, l.y, theme).map((v, i) => Math.round(v + (ink[i] - v) * mixK));
    return { name: l.name, ax: p.X, ay: p.Y, lx: p.X + l.dx, ly: p.Y + l.dy, tf: l.tf, c: 'rgb(' + cc.join(',') + ')' };
  });
}

// 2D top-down contour fallback (marching squares over the same surface).
// opts = { W, H, S, dpr = 2, glow = 0.8, grid = 80, levels, surface }
export function drawContour(canvas, opts = {}) {
  const surface = opts.surface || DEFAULT_SURFACE;
  const W = opts.W || 380, H = opts.H || 380, dpr = opts.dpr || 2;
  const S = opts.S || Math.min(W, H) / 2.7;
  const glow = opts.glow ?? 0.8;
  const theme = opts.theme;
  const n = opts.grid || 80;
  const levels = opts.levels || [0.05, 0.1, 0.16, 0.22, 0.29, 0.36];
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const px = (x) => W / 2 + x * S;
  const py = (y) => H / 2 + y * S;

  for (const g of surface.glows) {
    const rg = ctx.createRadialGradient(px(g.x), py(g.y), 0, px(g.x), py(g.y), S);
    rg.addColorStop(0, 'rgba(' + g.c + ',' + ((theme === 'light' ? 0.12 : 0.08) * glow).toFixed(3) + ')');
    rg.addColorStop(1, 'rgba(' + g.c + ',0)');
    ctx.fillStyle = rg;
    ctx.fillRect(px(g.x) - S, py(g.y) - S, S * 2, S * 2);
  }

  // domain boundary and hole rims, quiet
  ctx.strokeStyle = theme === 'light' ? 'rgba(110,107,100,0.4)' : 'rgba(165,161,153,0.3)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let k = 0; k <= 120; k++) {
    const th = (k / 120) * Math.PI * 2;
    const R = boundaryR(surface, th);
    const X = px(R * Math.cos(th)), Y = py(R * Math.sin(th));
    if (k === 0) ctx.moveTo(X, Y); else ctx.lineTo(X, Y);
  }
  ctx.stroke();
  ctx.setLineDash([3, 4]);
  for (const h of surface.holes) {
    ctx.beginPath();
    ctx.ellipse(px(h.x), py(h.y), h.rx * S, h.ry * S, h.rot || 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  let lim = 0;
  for (let k = 0; k <= 72; k++) lim = Math.max(lim, boundaryR(surface, (k / 72) * Math.PI * 2));
  lim += 0.08;
  const xs = [], zs = [], vis = [];
  for (let i = 0; i <= n; i++) {
    zs.push([]); vis.push([]);
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
    1: [['da', 'ab']], 2: [['ab', 'bc']], 3: [['da', 'bc']], 4: [['bc', 'cd']],
    5: [['da', 'ab'], ['bc', 'cd']], 6: [['ab', 'cd']], 7: [['da', 'cd']],
    8: [['cd', 'da']], 9: [['ab', 'cd']], 10: [['ab', 'bc'], ['cd', 'da']],
    11: [['bc', 'cd']], 12: [['bc', 'da']], 13: [['ab', 'bc']], 14: [['ab', 'da']],
  };
  ctx.lineWidth = 1;
  ctx.lineCap = 'round';
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      if (!vis[i][j] || !vis[i + 1][j] || !vis[i][j + 1] || !vis[i + 1][j + 1]) continue;
      const x0 = -lim + (2 * lim * i) / n, x1 = -lim + (2 * lim * (i + 1)) / n;
      const y0 = -lim + (2 * lim * j) / n, y1 = -lim + (2 * lim * (j + 1)) / n;
      const za = zs[i][j], zb = zs[i + 1][j], zc = zs[i + 1][j + 1], zd = zs[i][j + 1];
      for (let li = 0; li < levels.length; li++) {
        const L = levels[li];
        const code = (za > L ? 1 : 0) | (zb > L ? 2 : 0) | (zc > L ? 4 : 0) | (zd > L ? 8 : 0);
        const segs = SEG[code];
        if (!segs) continue;
        const ept = (e) => {
          if (e === 'ab') { const t = (L - za) / (zb - za); return [x0 + t * (x1 - x0), y0]; }
          if (e === 'bc') { const t = (L - zb) / (zc - zb); return [x1, y0 + t * (y1 - y0)]; }
          if (e === 'cd') { const t = (L - zd) / (zc - zd); return [x0 + t * (x1 - x0), y1]; }
          const t = (L - za) / (zd - za); return [x0, y0 + t * (y1 - y0)];
        };
        const c = colorAt(surface, (x0 + x1) / 2, (y0 + y1) / 2, theme);
        const alpha = Math.min(0.9, glow * (0.35 + 0.12 * li));
        ctx.strokeStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + alpha.toFixed(3) + ')';
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
