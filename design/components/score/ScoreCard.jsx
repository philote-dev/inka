import React from 'react';

const KINDS = {
  memory: {
    fill: 'var(--memory)', text: 'var(--memory-text)',
    icon: <g><polyline points="3,10 10,6.5 17,10" /><polyline points="3,13.5 10,10 17,13.5" /><polygon points="10,3 14,5.2 10,7.4 6,5.2" /></g>,
  },
  performance: {
    fill: 'var(--performance)', text: 'var(--performance-text)',
    icon: <g><circle cx="10" cy="10" r="7" /><circle cx="10" cy="10" r="3.5" /><circle cx="10" cy="10" r="0.8" fill="currentColor" stroke="none" /></g>,
  },
  readiness: {
    fill: 'var(--readiness)', text: 'var(--readiness-text)',
    icon: <g><path d="M3.5 13.5 a6.5 6.5 0 0 1 13 0" /><line x1="10" y1="13.5" x2="13.5" y2="8.5" /><circle cx="10" cy="13.5" r="1" fill="currentColor" stroke="none" /></g>,
  },
};

function Spark({ points, color }) {
  if (!points || !points.length) return null;
  const pts = points.map((v, i) => `${(i / (points.length - 1)) * 62},${20 - v * 16}`).join(' ');
  return (
    <svg width="62" height="22" viewBox="0 0 62 22" fill="none">
      <polyline points={pts} stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.9" />
    </svg>
  );
}

/** Score card with the honesty anatomy baked in. Number, likely range,
    how sure, last updated. Pass `abstain` to render the honest empty state. */
export function ScoreCard({ kind = 'memory', label, value, range, howSure, updated = 'Updated 2h ago', sparkline, abstain, style }) {
  const k = KINDS[kind] || KINDS.memory;
  const title = label || kind.charAt(0).toUpperCase() + kind.slice(1);
  const card = {
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-card)', padding: 20, boxShadow: 'var(--shadow-card)',
    fontFamily: 'var(--font-ui)', color: 'var(--text)', ...style,
  };
  const head = (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ color: k.text }}>{k.icon}</svg>
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--muted)' }}>{title}</span>
      </div>
      {!abstain && <Spark points={sparkline} color={k.text} />}
    </div>
  );
  if (abstain) {
    return (
      <section style={card}>
        {head}
        <div style={{ fontSize: 16, fontWeight: 600 }}>{abstain.message || 'Not enough evidence yet'}</div>
        {abstain.missing && <p style={{ margin: '8px 0 0', fontSize: 13, lineHeight: 1.5, color: 'var(--muted)' }}>{abstain.missing}</p>}
        <a href="#" onClick={e => { e.preventDefault(); abstain.onLink && abstain.onLink(); }}
          style={{ display: 'inline-block', marginTop: 12, fontSize: 13, color: 'var(--text)', textDecoration: 'underline', textUnderlineOffset: 3 }}>
          {abstain.linkLabel || 'See what is missing'}
        </a>
      </section>
    );
  }
  return (
    <section style={card}>
      {head}
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 40, fontWeight: 500, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      {range && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--muted)', marginTop: 8, fontVariantNumeric: 'tabular-nums' }}>Likely {range[0]} to {range[1]}</div>}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
        <span style={{ fontSize: 11, fontWeight: 500, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)' }}>{howSure}</span>
        <span style={{ fontSize: 12, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>{updated}</span>
      </div>
    </section>
  );
}
