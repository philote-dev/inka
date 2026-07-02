Reliability diagram for model calibration (not user confidence); lives in Progress.

```jsx
<ReliabilityDiagram tone="memory" brier={0.14} read="well calibrated"
  points={[{p:0.1,o:0.12},{p:0.3,o:0.28},{p:0.5,o:0.47},{p:0.7,o:0.74},{p:0.9,o:0.86}]} />
```

Diagonal is the reference. Always pair the Brier number with a plain-language read. Production uses D3 with the same encoding.
