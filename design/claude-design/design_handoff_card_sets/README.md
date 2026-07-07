# Handoff: Card Sets Browser ("the wheel")

A 3D browse-and-open surface for pgrep's flash card sets. Sets sit in an
infinite circular queue curving into the screen; the centered set is a stack
of cards you can hover, click open into a flat grid of questions, extend with
new cards, and close back into the stack.

Built and tuned interactively against the pgrep design system (dark + light).

## About the design files

The `.dc.html` files in this bundle are **design references created in
HTML** — working prototypes that show the intended look, motion, and
behavior. They are not production code to copy directly. Your task is to
**recreate this design inside the application's existing environment**
(the pgrep Anki-fork frontend — Svelte/TS — or whatever framework the
target app uses), following its established patterns. Every constant,
formula, and timing needed to do that faithfully is in `TECHNICAL-SPEC.md`.

## Fidelity

**High-fidelity.** Colors, type, spacing, radii, timings, and the motion
math are final and tuned. Recreate pixel- and easing-faithfully.

## Contents

- `README.md` — this file
- `PHILOSOPHY.md` — why the design is the way it is; the reasoning behind
  each decision made during the build
- `TECHNICAL-SPEC.md` — complete implementation spec: geometry math,
  animation frames, state machine, DOM structure, tokens, every tuned constant
- `Card Sets.dc.html` — dark reference (source of truth)
- `Card Sets Light.dc.html` — light reference (palette swap of dark; see
  spec §9 for the exact substitution table)
- `support.js` — runtime for the prototypes only; open either `.dc.html`
  next to it in a browser to see the live design. Not part of the handoff
  surface itself.

## The design in one paragraph

Eight topic sets are stacks of cards arranged on a wheel whose hub is
behind the screen: the centered set faces you full-opacity; neighbors
recede left/right along an arc, rotating gently into the page, falling
back in depth, and fading out entirely by ~3 steps away. The queue is
circular — scrolling past the last set wraps seamlessly to the first.
Scroll, drag, arrow keys, edge-deck clicks, and dots all drive one shared
target; the wheel snaps so a set is always centered. Hovering the centered
stack makes the back cards peek up. Clicking it deals every card out into
a 4-column grid (top-left first, ~16ms stagger); the grid ends with a
dashed "Add a card" tile that becomes an inline front/back composer.
Esc or "All sets" deals the cards back into the stack and returns to the
wheel.

## Screens

1. **Wheel** (`data-screen-label="Card sets browse"`) — header, 3D stage,
   8 pager dots. Two shell variants: immersive (logo top-left, streak
   top-right) and app-rail (216px pgrep nav rail).
2. **Set grid** (`data-screen-label="Set grid"`) — back button, set title +
   count, "Study this set" primary button, 4-col card grid, add-card tile /
   composer. Overlays the wheel; the wheel fades to 96.5% scale behind it.

## Variants (Tweaks props on the DC)

- `shell`: `"Immersive"` (default) | `"App rail"`
- `wheelFeel`: `"Ferris"` (default) | `"Shallow"` | `"Deep"` — three tuned
  parameter sets for the wheel geometry (spec §4)

## Assets

No image assets. Logo and icons are inline SVG (stroke `currentColor`,
width 1.5) — all paths are in the reference HTML. Fonts: Inter
(400/500/600) + JetBrains Mono (400/500) from Google Fonts. Math is
MathJax 3 (tex-chtml), inline `\( … \)`.

## Data model the app must provide

```
Set  { name: string, cards: Card[] }
Card { front: string (TeX allowed), back: string }
```

The prototype seeds 8 GRE topic sets (Classical Mechanics, E&M, Quantum,
Thermo/Stat Mech, Optics & Waves, Atomic, Special Relativity, Lab Methods)
with 9–12 real question fronts each — usable as fixture data. Deck faces
show `cards[0].front` as the preview; adding a card appends to the set and
all counts update reactively.
