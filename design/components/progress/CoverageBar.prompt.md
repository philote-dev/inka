Segmented per-topic coverage bar; the honest gate on Readiness.

```jsx
<CoverageBar segments={[
  { topic: 'Mechanics', weight: 20, covered: 0.8 },
  { topic: 'E and M', weight: 18, covered: 0.55 },
]} threshold={70} note="Below 70 percent, Readiness abstains and points here." />
```

Fills are monochrome. Segment width tracks blueprint weight so the layout teaches what matters.
