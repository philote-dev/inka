import React from 'react';
import { drawManifold, DEFAULT_SURFACE } from './manifold-core.js';

/** The knowledge manifold. Canvas wireframe with topic labels and leader
    lines. Fully data driven via `surface`. Production is the same structure
    on a Three.js displaced plane with a D3 contour fallback. */
export function Manifold({ width = 828, height = 540, scale = 182, glow = 0.7, grid = 64, lineWidth = 0.8, surface = DEFAULT_SURFACE, showLabels = true, style }) {
  const canvasRef = React.useRef(null);
  const [labels, setLabels] = React.useState([]);

  React.useEffect(() => {
    if (!canvasRef.current) return;
    const out = drawManifold(canvasRef.current, {
      W: width, H: height, S: scale, dpr: 2, glow, grid, lineWidth, surface,
    });
    setLabels(out || []);
  }, [width, height, scale, glow, grid, lineWidth, surface]);

  return (
    <div style={{ position: 'relative', width, height, fontFamily: 'var(--font-ui)', ...style }}>
      <canvas ref={canvasRef} width={width * 2} height={height * 2} style={{ width, height, display: 'block' }} />
      {showLabels && (
        <svg width={width} height={height} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
          {labels.map((l) => (
            <g key={l.name}>
              <circle cx={l.ax} cy={l.ay} r="2.5" fill="var(--muted)" />
              <line x1={l.ax} y1={l.ay} x2={l.lx} y2={l.ly} stroke="var(--muted)" strokeWidth="1" opacity="0.7" />
            </g>
          ))}
        </svg>
      )}
      {showLabels && labels.map((l) => (
        <div key={l.name} style={{ position: 'absolute', left: l.lx, top: l.ly, transform: l.tf, fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap', padding: '2px 6px' }}>{l.name}</div>
      ))}
    </div>
  );
}
