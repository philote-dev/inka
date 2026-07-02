import React from 'react';

/** Segmented per-topic coverage bar. Coverage gates Readiness, so the
    abstain note states the rule plainly. */
export function CoverageBar({ segments, threshold = 70, note, style }) {
  const total = segments.reduce((s, x) => s + x.weight, 0);
  const covered = Math.round(segments.reduce((s, x) => s + x.weight * (x.covered || 0), 0) / total * 100);
  return (
    <div style={{ fontFamily: 'var(--font-ui)', color: 'var(--text)', ...style }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>{covered} percent of the exam covered</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>Readiness needs {threshold}</span>
      </div>
      <div style={{ display: 'flex', gap: 3, height: 10 }}>
        {segments.map((s) => (
          <div key={s.topic} title={s.topic} style={{ flex: s.weight, borderRadius: 3, overflow: 'hidden', display: 'flex', border: '1px solid var(--border)' }}>
            <div style={{ width: `${(s.covered || 0) * 100}%`, background: 'var(--text)', opacity: 0.75 }} />
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 3, marginTop: 6 }}>
        {segments.map((s) => (
          <span key={s.topic} style={{ flex: s.weight, fontSize: 10, color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.topic}</span>
        ))}
      </div>
      {note && <p style={{ margin: '10px 0 0', fontSize: 12, lineHeight: 1.5, color: 'var(--muted)' }}>{note}</p>}
    </div>
  );
}
