import React from 'react';

/** Five choices A to E. Monochrome default, thin blue outline for select,
    dimmed with a calm blue tag for a committed wrong answer. Never red. */
export function ChoiceList({ choices, onSelect, style }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontFamily: 'var(--font-ui)', ...style }}>
      {choices.map((c) => {
        const selected = c.state === 'selected';
        const committed = c.state === 'committed';
        return (
          <div key={c.key} onClick={() => onSelect && onSelect(c.key)} style={{
            display: 'flex', alignItems: 'center', gap: 16,
            border: selected ? '1.5px solid var(--performance)' : '1px solid var(--border)',
            background: selected ? 'rgba(129,161,193,0.06)' : 'none',
            opacity: committed ? 0.62 : 1,
            borderRadius: 'var(--radius-row)', padding: '14px 18px',
            cursor: onSelect ? 'pointer' : 'default', transition: 'background 240ms ease, border-color 240ms ease, color 240ms ease',
          }}>
            <span style={{
              width: 26, height: 26, flex: '0 0 26px',
              border: `1px solid ${selected ? 'var(--performance)' : 'var(--border)'}`,
              borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: 'var(--font-mono)', fontSize: 12,
              color: selected ? 'var(--performance-text)' : 'var(--muted)',
            }}>{c.key}</span>
            <span style={{ fontSize: 16, color: 'var(--text)' }}>{c.content}</span>
            {committed && (
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--performance-text)', border: '1px solid rgba(129,161,193,0.45)', borderRadius: 999, padding: '3px 10px', whiteSpace: 'nowrap' }}>
                Your answer, not correct
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
