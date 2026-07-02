Score card with the honesty rule baked in; never show a score without its range, how-sure, and updated line.

```jsx
<ScoreCard kind="memory" value={72} range={[68, 77]} howSure="Fairly sure" updated="Updated 2h ago" sparkline={[0.3,0.45,0.4,0.6,0.55,0.8,0.75]} />
<ScoreCard kind="readiness" abstain={{ missing: 'Coverage sits at 46 percent, below the 70 percent line.' }} />
```

The accent appears only on the glyph and sparkline. Abstain replaces the number entirely and names what is missing.
