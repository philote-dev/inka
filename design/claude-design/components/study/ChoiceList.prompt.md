Five-choice answer list for problems; blue select, calm blue committed-wrong, never red.

```jsx
<ChoiceList
    choices={[
        { key: "A", content: "ω = √(g/L)" },
        { key: "B", content: "ω = √(2g/L)", state: "selected" },
    ]}
    onSelect={pick}
/>;
```

`committed` dims the row to 62% and adds the tag "Your answer, not correct". There is never a confidence control.
