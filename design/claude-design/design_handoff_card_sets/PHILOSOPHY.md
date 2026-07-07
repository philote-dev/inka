# Philosophy: why the wheel is built this way

pgrep's personality is _an honest measuring instrument_. Nothing in the UI
performs; everything reports. That constraint shaped every decision below —
the browse surface earns its theatrics by making the **spatial model** of
your library truthful, then refuses decoration everywhere else.

## 1. The library is a physical queue, not a menu

Anki decks are usually a list. The wheel instead treats each topic as a
**physical stack of cards** occupying space: stacks sit shoulder to
shoulder on a circular carousel that curves _into_ the page. This does three
honest things:

- **Depth = distance from attention.** The set you're considering is
  closest, fully lit, fully opaque. Everything else recedes and dims in
  proportion to how far it is from your focus. Opacity is a literal
  attention gradient, not a style.
- **The queue is circular** because eight topics have no first or last —
  review is a cycle. Scrolling never hits a wall; the shortest path to any
  set is at most four steps.
- **Stacks look like what they are.** A set's face is its _actual_ top
  card's question, not a cover illustration. Back cards physically peek out
  above the front card. Hover doesn't add a glow; it slides the back cards
  up further — the object responds the way paper would.

## 2. Motion rules

- **One shared target.** Wheel, drag, keys, dot clicks, and side-deck
  clicks all write the same target value `T`; a single spring chases it.
  Inputs can never fight each other, and interrupted gestures blend
  naturally.
- **Always settle centered.** Free scroll with a snap on release: browsing
  is analog, but the resting state is always a decision — one set, front
  and center, with an explicit "Click to open" affordance.
- **Shuffle, not slide.** A set in transit bows slightly _toward_ the
  viewer and passes in front before settling (the `fwd` term). This came
  from iteration: a flat lateral slide read as a 2D carousel; a dip _away_
  read as retreat. Pulling a card out of the queue toward you and laying it
  back is how a hand actually shuffles a deck.
- **Front-facing bias.** Decks rotate at less than half the arc's tangent
  angle (`rotK ≈ 0.45`). Full tangent rotation turned side stacks edge-on —
  geometrically correct, visually illegible (cards are thin). The
  compromise keeps the arc's depth path while keeping every visible face
  readable. Legibility beats geometric purity.
- **Stacks peek strictly vertically.** We tried spacing stack layers in Z
  and cascading them sideways; both made rotated side decks look messy or
  see-through. Final rule: back cards offset in Y only (flat in Z ±3px).
  Clean verticals read as "tidy pile" from every angle.
- **The grid open is literal dealing.** Cards fly from the stack's exact
  screen position to their grid cells (FLIP), 16ms apart, slight scatter
  rotation in flight, top-left lands first. Closing reverses it, last card
  leaves first. The animation is the explanation: _these cards were in that
  pile._

## 3. Calm everywhere else

- One easing everywhere: `cubic-bezier(0.32, 0.72, 0, 1)` — pgrep's calm
  spring, decisive start, no bounce.
- Hover states are hairline border-color shifts (`#45433E → #6E6B64`), not
  shadows or scale. The only elevated shadow in the whole design belongs to
  the front card of each stack, because it is physically on top of things.
- Two background tones per theme, both within pgrep's warm gray ramp. No
  gradients, no vignettes; depth is carried entirely by perspective,
  occlusion, and opacity.
- Numbers (card counts) are JetBrains Mono tabular — data is data.
- The add-card composer is inline, in the grid cell where the card will
  live. Creating a card should feel like _placing_ it, not filling a modal
  form. Cancel/Esc backs out; a second Esc closes the set — one consistent
  "step back" gesture.

## 4. What we deliberately did not do

- No cover art, category icons, or color-coding per topic. The cards
  themselves are the identity of a set.
- No progress rings or due-count badges on deck faces (a preview of the
  actual material instead — the face answers "what's in here", not "how
  guilty should I feel").
- No parallax on the header/dots; chrome stays still while the world
  moves.
- No wrap-around minimap or scrollbar. Dots show position; the wheel's
  geometry shows everything else.
