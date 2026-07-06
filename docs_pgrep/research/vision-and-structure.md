# Vision, Structure & MVP

**Status: approved.** Shared mission / constraints / exam facts live in `README.md`.

## 1. Vision & user stories

**One user:** a motivated **post-undergraduate** physics student who has already been taught this material and wants to ace the exam. **No true novices / no cold-starts** in core scope. **No cohort. No instructors.** Lead with the three pillars in order — retrieval → practice questions → practice tests — and defer teaching fallbacks (Learn/content, learn-by-explaining) to post-core.

**Center of gravity:** three co-equal pillars that map onto the three scores, integrated by the readiness view:

- **Cards → Memory** (the generation-effect surface)
- **Problems → Performance** (with reasoning-first help)
- **Timed mocks → Readiness**

_Clarification (locked):_ the scores stay co-equal for honesty. The thesis bias toward problem-solving is not a manual UI tilt or a hand-tuned weighting. It falls out of the engine and the mix (the interleaving selector orders what is due, and the daily session offers both doors). No special-casing.

**Core user stories:**

- **Get oriented** — a short adaptive diagnostic across the PGRE blueprint places each topic as _strong / rusty / cold_.
- **Fill true gaps** _(DEFERRED — teaching fallback, post-core)_ — curated (bundled) learning content for genuinely cold topics. Deferred because the persona is post-undergrad (already oriented), so interleaving needs no cold-start on-ramp. Revisit after the three pillars work; when built, it will also supply a traceable "named source" for AI items.
- **Build memory** — flashcards for concepts, equations, techniques, spaced.
- **Build performance** — exam-style problems that test _application_ to novel questions; help that pushes the learner's reasoning before revealing answers.
- **Build readiness** — full timed, PGRE-shaped mocks (100Q / 170 min, quarter-point wrong-answer penalty, scaled 200 to 990).
- **Know where you stand** — one honest view of memory / performance / readiness, with gaps named.
- **Know what to do next** — a coverage-aware daily study mix.
- **Learn from mistakes** — misses resurface, and optionally become new items.
- **Study anywhere** — desk (deep work) + phone (quick reviews + readiness glance), synced.

**In core:** importing your own deck (breadth/coverage; auto-tagged). **Out of scope:** cohort, instructors. **Future door only:** uploading your own _source materials_ for AI grounding (distinct from deck import).

## 2. App structure / Information Architecture

**Architecture stance:** pgrep is a **product built on the shared, modified Anki Rust engine.** "Reuse Anki" means reuse the _engine_, not the _interface_.

Anki's stack, and where pgrep reaches:

1. `rslib/` — core Rust engine (FSRS, collection/SQLite, sync, search, stats). **Reused + modified.** ← graded Rust change lives here.
2. `proto/` — protobuf API contracts. **Reused + extended.**
3. `pylib/` (+ `rsbridge`) — Python bindings. **Reused + extended.**
4. `aqt/` — PyQt desktop GUI. **Kept as a thin host; screens replaced by pgrep UI.**
5. `ts/` — Svelte/TS web components. **pgrep's own surfaces built here.**
6. Mobile — AnkiDroid (Kotlin/JNI) and iOS (C FFI). **Same engine under pgrep's own mobile UI.**

Mandatory depth = layers 1–3. Layers 4–6 = product surface / design freedom.

**Surfaces (custom pgrep UI):**

- **0. Diagnostic** (first run + re-runnable): adaptive placement → strong/rusty map (no cold bucket in core; persona is post-undergrad). Drives topic _weighting_, not eligibility. **Followed by a "set up your study set" step:** the pool is assembled here, not generated live. Start on the **bundled baseline deck** (AI-off path), **import** your own deck (breadth/coverage only, auto-tagged to the blueprint), and/or **author conceptual seeds** (required to unlock AI generation — import never substitutes for authoring). All contributions land in one topic-tagged, FSRS-scheduled pool. See `feature-forced-generation.md`.
- **1. Home (Readiness):** the three scores with ranges, confidence, % coverage, last-updated, give-up state; plus **Today** — the single best next thing + "Start today's session."
- **2. Study:** two doors after orientation — **Cards** (memory, retrieval) and **Problems** (performance, with the wrong-answer ladder) — **topics interleaved within each door**; commit-before-reveal on problems (no confidence capture); **Focus drill** reuses both doors scoped to one topic; **Exam** mode = full timed mock.
- **3. Progress:** Coverage/Topic map (per-topic mastery + coverage, gating Readiness) + **model calibration** (reliability diagram + Brier for Memory & Performance). No user-confidence capture.
- **4. Content:** Author & Generate (write a seed item → AI conforms to your style; gold-set check) + browse/manage cards & problems. _(Learn/remediation surface deferred — teaching fallback.)_
- **5. Settings:** AI on/off, sync, target retention, test date.

_Cross-cutting under every surface:_ the shared engine (FSRS + our scheduler change), the review/attempt log (feeds all three scores + calibration), sync (desk ↔ phone).

**Mobile subset:** Home (Readiness) + Study (mixed sessions; exam mode optional) + offline & sync. Authoring, Content, deep Progress are desktop-first.

## 3. MVP + milestones

**Timeline stance:** an ambitious Wed/Fri/Sun spine — push hard where it earns points (Rust change, 3-score honesty, learning-science features, AI), don't gold-plate the rest.

**MVP = Wednesday's no-AI core** — the minimum that proves the whole architecture is real. Each milestone has a **floor** (graded requirement) and a **stretch** (ambition, only once floor is solid).

### Milestone 1 — Wednesday (MVP, no AI)

Floor:

- Anki forked + building from source (desktop).
- One real **Rust engine change** end-to-end: diff + 3 Rust unit tests + 1 Python-side test. _(Leading candidate: interleaving scheduler — doubles as Sunday's ablation feature.)_
- pgrep **Study** surface running a review loop on a PGRE card deck.
- **Home** showing the **Memory** score honestly — range + give-up rule (no performance/readiness yet).
- Desktop **installer** on a clean machine.
- **Mobile**: phone build runs on device/emulator, loads the PGRE deck, runs a real review session on the shared engine (no sync yet).

Stretch (non-AI seeds of the POVs): honest Memory score with a model-calibration hook (POV4), manual seed-card authoring (POV2 ph.1), commit-before-reveal gate (POV3), Diagnostic v0.

### Milestone 2 — Friday (AI + sync)

Floor:

- AI card/problem generation, each output traced to a **named source** (bundled corpus).
- **Pre-release eval**: accuracy + wrong-answer rate on a held-out gold set, with a cutoff that blocks bad items.
- **Beats a baseline**: AI beats keyword/vector search, side-by-side.
- App still gives a score with **AI off**.
- **Mobile two-way sync** (no lost/double reviews), offline review then sync.
- Phone shows the **three scores** with ranges + give-up rule.

Stretch: full AI **scaffold-fade tutor** (POV3), **forced-generation → AI-conform** (POV2 full), provisional **Performance** score so Home shows all three.

### Milestone 3 — Sunday (prove it + ship)

Floor:

- **Memory calibration**: calibration chart + Brier/log-loss on held-out reviews.
- **Performance model**: accuracy on held-out exam-style questions.
- **Score mapping** (performance → readiness), written down, with a range.
- **Ablation**: three builds — full / interleaving-off / plain Anki — equal study time, metric pre-stated, report what didn't work.
- Packaged **desktop installer** + **phone build** (signed APK / iOS TestFlight or sideload).
- **Sync conflict** handling (same card, both devices offline → correct, documented merge).
- Both apps run with **AI off** + still give a score.
- Results report + model descriptions + Brainlift.

Stretch: full **Calibration dashboard** (POV4) in Progress, the **Learn/remediation** surface, the **"best next thing"** recommender.

### Beyond Sunday — extensibility roadmap

User-materials upload (parked door) · real-time / conflict-free (CRDT) sync · 100k-card scale + profiling · signed & notarized installers (mac/win/linux) + store-ready phone · upstream a change to Anki/AnkiDroid · deeper score-model validation with longitudinal data · knowledge-graph study planning (spec bonus).

## 4. Open, to be locked in later phases

- Exactly **which Rust change** is the hero (Phase 3).
- **Precise scope** of each POV feature (Phase 2).
