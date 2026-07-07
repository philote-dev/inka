# Technical spec: Card Sets wheel + grid

Everything needed to reimplement the design without reading the prototype
source. Coordinates are CSS px in a 1440×900 frame. Angles in this doc are
degrees; the math uses radians.

---

## 1. DOM / layer structure

```
frame (1440×900, overflow hidden, bg --bg, [data-screen-label])
├─ (variant "App rail") nav rail, 216px fixed, right hairline border
├─ content wrapper (flex:1, position:relative, overflow:hidden)
│  ├─ WHEEL layer (absolute inset 0, column flex)
│  │  ├─ top bar (immersive variant only): logo left, streak right
│  │  ├─ header: h1 "Your sets" + subline
│  │  ├─ STAGE (flex:1, position:relative, perspective:1500px,
│  │  │         perspective-origin:50% 45%, touch-action:none,
│  │  │         cursor:grab / grabbing while dragging)
│  │  │  └─ 8 × deck wrapper (absolute, left:50%, top:52%,
│  │  │        300×380px, transform-style:preserve-3d,
│  │  │        base transform translate(-50%,-50%),
│  │  │        will-change:transform)  ← positioned per-frame by JS
│  │  │     └─ clickable stack (relative, 100%, preserve-3d)
│  │  │        ├─ back card 3 (absolute inset 0)   ← deepest
│  │  │        ├─ back card 2
│  │  │        ├─ back card 1
│  │  │        └─ front card (flex column: label, preview, footer)
│  │  └─ dots row (8 buttons, 20×20 hit target, 6px dot)
│  └─ GRID layer (absolute inset 0, z-index 10, only when a set is open)
│     ├─ chrome row: back button, title block, "Study this set"
│     └─ scroll area → 4-col grid (max-width 1240, centered)
│        ├─ N × card article (min-height 136px)
│        └─ add tile (dashed) → OR inline composer when adding
```

Key: the stage does **not** use `preserve-3d` — each deck wrapper is its
own stacking context, so sibling overlap is controlled by `z-index`
(computed from distance), while perspective still applies to each deck's
own transform. Stacking INSIDE a deck uses `preserve-3d`.

## 2. State

```
T        target position, float, unbounded (wraps mod 8)   ── input writes
A        animated position, chases T                        ── spring
spread   0→1 intro factor (decks fan out from center on load)
sel      round(T) mod 8            — the centered set (derived, in state)
hovered  deck index under pointer or −1
open     index of opened set or null
closing  true while the close (fly-back) animation runs
adding   true while the composer replaces the add tile
dragging pointer-drag in progress (cursor only)
```

`sel` follows "slide 1 = first" human indexing in labels; internally 0-based.

## 3. The per-frame wheel transform (rAF loop)

For each deck `i` (0…7), with feel constants (§4):

```
off  = wrap(i − A)              // wrap to (−4, +4]: ((v%8)+8)%8, then −8 if >4
phi  = clamp(off · sp · spread, ±maxPhi)          // radians
d    = |off| · spread                              // distance in steps
dx   = R · sin(phi)
dz   = R · (cos(phi) − 1)  −  push·d  +  fwd · sin(π · min(d,1))
rot  = phi · rotK                                  // rotateY, radians
opacity = clamp(1 − dim·(d − 1), 0, 1)             // full ≤1 step, fades after
zIndex  = 1000 − round(d·100)
transform = translate(-50%,-50%)
            translate3d(dx, 0, dz) rotateY(rot)
pointer-events: none when opacity < 0.08
```

Reading the dz sum: circle arc (drops behind as cos falls) + linear extra
recede per step (`push`) + a **forward bow** mid-transit (`fwd`, peaks at
d = 0.5, zero at rest) — the "shuffle toward you" move.

Spring integration, each frame:

```
A      += (T − A)      · (dragging ? 0.40 : 0.16)
spread += (1 − spread) · 0.09          // starts 0.04 on mount
```

## 4. Feel presets (`wheelFeel` prop)

| const   | Ferris (default) | Shallow | Deep  | meaning                        |
|---------|------------------|---------|-------|--------------------------------|
| `R`     | 640              | 920     | 500   | wheel radius, px               |
| `sp`    | 34°              | 23°     | 45°   | angular step between decks     |
| `rotK`  | 0.45             | 0.52    | 0.42  | fraction of tangent rotation   |
| `push`  | 260              | 180     | 350   | extra Z recede per step, px    |
| `fwd`   | 70               | 50      | 100   | forward bow at mid-transit, px |
| `dim`   | 0.52             | 0.38    | 0.66  | opacity falloff per step past 1|
| `maxPhi`| 76°              | 64°     | 86°   | clamp on phi                   |

## 5. Inputs → all write `T`

- **Wheel/trackpad** on stage: `T = T + (deltaY + deltaX) · 0.0032`
  (preventDefault; passive:false). Snap `T = round(T)` 150ms after the
  last wheel event.
- **Drag**: pointerdown on stage stores `(x0, T0)`; move sets
  `T = T0 − (x − x0) / pxPerIndex`, `pxPerIndex = R · sp(rad)`. >6px marks
  it a real drag (suppresses the click that follows). Release snaps.
- **Arrow keys**: `T = round(T) ± 1`. **Enter/Space** opens the centered set.
- **Side-deck click**: `T = round(T) + wrap(i − sel)` (shortest way around).
- **Dot click**: same shortest-path formula.
- No clamping anywhere — the queue is infinite; `wrap()` handles display.

## 6. The stack (per deck)

4 layers, all 300×380, radius 16px:

- Front card: bg `--card`, border 1px `--border`, padding 22px 24px,
  shadow `0 2px 6px rgba(0,0,0,.25), 0 12px 40px rgba(0,0,0,.2)` (dark).
  Content: topic label (11px, 500, uppercase, tracking .08em, `--muted`),
  preview = top card's question (15px/1.55, 5-line clamp), footer = count
  in mono 12px `--faint` + "Click to open" (only on the centered deck).
- Back cards k = 1,2,3: bg `--card-back`, border `--border-back`,
  `transform: translateY(−5k px) translateZ(−k px)`.
  (Z ≈ flat on purpose; ±px only to avoid coplanar flicker.)
- Hover (centered deck only): back cards go to translateY(−12/−23/−34 px);
  front border → `--border-strong`. Transition 280ms calm-spring.

## 7. Open / close (FLIP deal)

**Open** (click centered deck): mount grid layer; wheel layer fades to
opacity 0 / scale .965 (360ms). For each grid card, measure its final rect,
set `transform: translate(deckCenter − cardCenter) rotate(scatter) scale(.82)`,
`opacity 0`, force reflow, then release to identity with
`transform 460ms calm-spring` + `opacity 300ms`, delay `16ms × index`
(+40ms extra on opacity). Scatter rotation: `((i·37) % 9 − 4) · 1.6` deg.
The add tile/composer is part of the grid and animates like a card.

**Close** (back button / Esc): chrome fades (220ms); every card animates
to the deck's current center with the inverse transform, delay
`10ms × (n−1−i)` (top-left leaves last), then the grid unmounts and the
wheel fades back in. Guard: total timeout ≈ `420 + 10(n−1) + 100` ms.

**Esc order**: composer open → close composer; else grid open → close grid.

## 8. Grid + add-card

- Grid: `repeat(4, 1fr)`, gap 14px, max-width 1240, padding 6px 64px 44px.
- Card: bg `--card`, hairline `--border`, radius 14px, padding 18px 20px,
  min-height 136px, question at 14px/1.6. Hover: border → `--border-strong`.
- Add tile: transparent, `1px dashed --border`, radius 14, centered
  `+ Add a card` (13px, 500, `--muted`); hover strengthens both.
- Composer (replaces tile): card-styled cell, two textareas (Front
  "Front. Write it in your own words.", Back "Back. The answer, stated
  plainly."), 13px, bg `--bg-inset`, focus border `--text`; footer right:
  ghost **Cancel** + hairline **Add card**. Empty front → refocus, no
  submit. Submit appends `{front}` to the set, re-typesets MathJax,
  returns to tile.
- Chrome: back button = hairline pill w/ left arrow "All sets"; title
  22px/600 −0.02em; subline "N cards. Esc returns you to your sets."
  (count in mono); primary button `--text` bg / `--bg` text, radius 10,
  padding 11px 22px.

## 9. Tokens

Palette (dark → light substitution used to generate the light file):

| role            | dark      | light     |
|-----------------|-----------|-----------|
| `--bg`          | `#262624` | `#FBFAF8` |
| `--card`        | `#302F2C` | `#FFFFFF` |
| `--card-back`   | `#2D2C29` | `#F5F2EC` |
| `--bg-inset`    | `#2B2A27` | `#F5F2EC` |
| `--border`      | `#45433E` | `#E8E4DA` |
| `--border-back` | `#403E39` | `#EAE6DC` |
| `--border-strong`/`--faint` | `#6E6B64` | `#A5A199` |
| `--muted`       | `#A5A199` | `#6E6B64` |
| `--text`        | `#ECEAE3` | `#262624` |
| text hover/max  | `#FFFFFF` | `#000000` |
| shadows         | black-based | `rgba(38,38,36,.06)` ramp |

Type: Inter (UI), JetBrains Mono (all numbers, `tnum lnum`). Scale used:
11 caption / 12 small / 13 controls / 14 body / 15 preview / 22–24 titles.
Radii: 8 (inputs), 10 (buttons), 14 (grid cards), 16 (deck cards), 999 (dots).
Easing: `cubic-bezier(0.32, 0.72, 0, 1)` everywhere; border/color fades 240ms.

## 10. Accessibility & misc

- Decks: `role="button"`, `aria-label="{name}, {n} cards"`. Dots:
  `aria-label="Go to {name}"`. All interactive targets ≥ 20px hit area.
- Keyboard: ←/→ rotate, Enter/Space open, Esc back (see §7 order).
- MathJax 3 tex-chtml, inline `\( \)`; re-typeset after opening a set and
  after adding a card. `mjx-container { color: inherit }`.
- The wheel layer keeps `pointer-events: none` while a set is open.
- Perspective values (1500px, origin 50% 45%) are part of the tuned look —
  changing them changes every apparent depth.
- Deck wrappers keep `will-change: transform`; per-frame styles are set
  directly (no transitions on the wrapper — the spring IS the animation).
