One rung of the wrong-answer ladder; poses a stored sub-goal, collects self-explanation, reveals only the step.

```jsx
<HintRung step={1} steps={3} hintsUsed={1} budget={3}
  question="Which conservation law applies here, and why."
  onAction={showStep} />
```

Blue accent on the budget dots only. The final answer never appears until Reveal. Tone is supportive, never red.
