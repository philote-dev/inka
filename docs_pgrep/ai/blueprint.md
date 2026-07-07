# PGRE Topic Blueprint

**Status: locked (v1).** Owner: Curriculum & Taxonomy Architect.
Machine-readable twin: [`blueprint.json`](blueprint.json). Final slug list:
[`slugs.md`](slugs.md). Last updated 2026-07-03.

This is the single taxonomy every piece of pgrep content tags against. The
bundled deck, the AI-generated cards and problems, the seeds, the coverage map
that gates Readiness, and the interleaving selector all read these tags and
weights. It aligns to the official ETS Physics GRE content breakdown and honors
the locked tag scheme in `docs_pgrep/reference/tag-and-attempt-log-schema.md`. It does
not reinvent that scheme.

## Sources

- ETS Physics GRE content specification, the public topic breakdown and its
  listed subtopics. This is the named source for the taxonomy itself.
- `docs_pgrep/reference/tag-and-attempt-log-schema.md`, the locked tag format and the
  category weights (the contract this file must match).
- `docs_pgrep/README.md` for exam facts, `docs_pgrep/research/three-scores.md`
  for the coverage gate and abstain thresholds, and
  `docs_pgrep/research/feature-interleaving.md` for the two-level taxonomy and
  the big-3 subtopic rule.

---

## 1. Tag-string format (honors L1 exactly)

Two-level hierarchical Anki tags, `::` for hierarchy.

```
topic::<category>                     # category level (required, all 9)
topic::<category>::<subtopic>         # finer level, big-3 only
```

- Category is required. Subtopic tags exist **only** under the big three
  (`mechanics`, `electromagnetism`, `quantum`), per L1.
- Casing is lowercase. Multi-word slugs use `snake_case`.
- A note may carry other, non-`topic::` tags. Only `topic::*` is read by the
  engine. Attempt notes carry the item's finest topic tag plus `pgrep::attempt`.

Examples: `topic::mechanics::oscillations`, `topic::electromagnetism::electrostatics`,
`topic::quantum::schrodinger_solutions`, `topic::optics_waves`, `topic::lab`.

Distinct topic tags in this blueprint: **20** (14 big-3 subtopics plus 6 small
categories). Finest units (seeds): **25**.

Note on seed filenames. The seed folder names files as `<area>-<subtopic>`
(for example `mechanics-oscillations.md`, `em-electrostatics.md`). That file
convention is separate from the tag string. The `seed_file` column in
[`blueprint.json`](blueprint.json) maps each finest unit to its seed filename.

---

## 2. How the weights are used (two different jobs)

The same percentages drive two different mechanisms, so keep them straight.

- **Selector worth (interleaving).** `worth = weight_pct(category) x weakness`.
  All subtopics of a category share the category weight (per L1). Weakness is
  aggregated at the finest tagged level.
- **Coverage gate and Readiness.** These operate at **category level**. Each
  category contributes `readiness_questions = round(weight_pct/100 x 70)` exam
  questions. The 9 weights sum to 100 and the questions sum to 70.

The finest units (below) drive three things: seed authoring (one seed per unit),
the selector's weakness aggregation, and the coverage checklist (the bundled
deck must touch every unit).

---

## 3. The taxonomy

Weights below are the **L1-locked** values. Where the current public ETS figure
differs, it is flagged in section 5.

### Classical Mechanics, 20%, `topic::mechanics`, ~14 questions

| Finest unit                          | Tag                                        | ETS content                                                                                 |
| ------------------------------------ | ------------------------------------------ | ------------------------------------------------------------------------------------------- |
| Newtonian dynamics, work and energy  | `topic::mechanics::dynamics_energy`        | kinematics, Newton's laws, work and energy, systems of particles, 3D particle dynamics      |
| Oscillations                         | `topic::mechanics::oscillations`           | simple, damped, and driven harmonic motion, resonance                                       |
| Rotation and rigid bodies            | `topic::mechanics::rotation`               | rotational motion about a fixed axis, rigid bodies, angular momentum, moment of inertia     |
| Central forces and orbits            | `topic::mechanics::central_forces`         | central forces, celestial mechanics, orbits                                                 |
| Lagrangian and Hamiltonian formalism | `topic::mechanics::lagrangian_hamiltonian` | Lagrangian and Hamiltonian formalism, noninertial frames, elementary fluid dynamics (minor) |

### Electromagnetism, 18%, `topic::electromagnetism`, ~13 questions

| Finest unit                          | Tag                                          | ETS content                                                       |
| ------------------------------------ | -------------------------------------------- | ----------------------------------------------------------------- |
| Electrostatics                       | `topic::electromagnetism::electrostatics`    | Coulomb, fields, potential, Gauss, capacitance, dielectrics       |
| Magnetostatics and the Lorentz force | `topic::electromagnetism::magnetostatics`    | magnetic fields in free space, Lorentz force, Ampere, Biot-Savart |
| Induction and Maxwell's equations    | `topic::electromagnetism::induction_maxwell` | induction, Maxwell's equations and their applications             |
| Electromagnetic waves                | `topic::electromagnetism::em_waves`          | electromagnetic waves, propagation, radiation                     |
| Circuits (DC and AC)                 | `topic::electromagnetism::circuits`          | DC and AC circuits, fields in matter (minor)                      |

### Quantum Mechanics, 13%, `topic::quantum`, ~9 questions

| Finest unit                      | Tag                                     | ETS content                                                                |
| -------------------------------- | --------------------------------------- | -------------------------------------------------------------------------- |
| Formalism                        | `topic::quantum::formalism`             | fundamental concepts, states, operators, measurement, uncertainty          |
| Schrodinger solutions            | `topic::quantum::schrodinger_solutions` | square wells, barriers, harmonic oscillator, hydrogenic atoms              |
| Angular momentum and spin        | `topic::quantum::angular_momentum_spin` | angular momentum, spin                                                     |
| Perturbation theory and symmetry | `topic::quantum::perturbation_symmetry` | elementary perturbation theory, identical particles, wavefunction symmetry |

### Thermodynamics and Statistical Mechanics, 10%, `topic::thermodynamics`, ~7 questions

| Finest unit                              | Tag                     | ETS content                                                                                          |
| ---------------------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------------- |
| Laws and processes                       | `topic::thermodynamics` | laws of thermodynamics, processes, equations of state, ideal gases, thermal expansion, heat transfer |
| Statistical mechanics and kinetic theory | `topic::thermodynamics` | kinetic theory, ensembles, statistical calculation of thermodynamic quantities                       |

### Atomic Physics, 10%, `topic::atomic`, ~7 questions

| Finest unit                   | Tag             | ETS content                                                                              |
| ----------------------------- | --------------- | ---------------------------------------------------------------------------------------- |
| Atomic structure and spectra  | `topic::atomic` | Bohr model, energy quantization, atomic structure, atomic spectra, selection rules       |
| Radiation and atoms in fields | `topic::atomic` | black-body radiation, x-rays, atoms in electric and magnetic fields, electron properties |

### Optics and Wave Phenomena, 8%, `topic::optics_waves`, ~6 questions

| Finest unit                         | Tag                   | ETS content                                                               |
| ----------------------------------- | --------------------- | ------------------------------------------------------------------------- |
| Wave phenomena                      | `topic::optics_waves` | wave properties, superposition, interference, diffraction, Doppler effect |
| Geometrical optics and polarization | `topic::optics_waves` | geometrical optics, polarization                                          |

### Special Relativity, 6%, `topic::special_relativity`, ~4 questions

| Finest unit                          | Tag                         | ETS content                                                                                                                      |
| ------------------------------------ | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Relativistic kinematics and dynamics | `topic::special_relativity` | time dilation, length contraction, simultaneity, four-vectors and Lorentz transformation, energy and momentum, velocity addition |

### Laboratory Methods, 6%, `topic::lab`, ~4 questions

| Finest unit             | Tag          | ETS content                                                                                                                                                                                                                 |
| ----------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Data and error analysis | `topic::lab` | data and error analysis, counting statistics, probability and statistics, electronics, instrumentation, radiation detection, interaction of charged particles with matter, lasers and interferometers, dimensional analysis |

### Specialized Topics, 9%, `topic::specialized`, ~6 questions

| Finest unit                    | Tag                  | ETS content                                                                                                      |
| ------------------------------ | -------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Nuclear and particle physics   | `topic::specialized` | nuclear properties, radioactive decay, fission and fusion, reactions, elementary particle properties             |
| Condensed matter               | `topic::specialized` | crystal structure, x-ray diffraction, thermal and electron properties of solids, semiconductors, superconductors |
| Miscellaneous and astrophysics | `topic::specialized` | astrophysics, mathematical methods, computer applications                                                        |

All three specialized units share the single `topic::specialized` category tag
(strict L1 rule). They are distinct for seed authoring and the coverage
checklist, not for tagging.

---

## 4. Coverage targets

Thresholds come from `docs_pgrep/research/three-scores.md`.

- **Memory floor.** Each covered topic needs at least **5** reviewed cards, else
  it shows "Not enough cards yet."
- **Performance floor.** Each covered topic needs at least **8** scored attempts
  (clean, committed, first-try). Below that it abstains.
- **Readiness gate.** Readiness abstains until topics holding at least **70%** of
  blueprint weight each clear the performance floor. Uncovered weight is named,
  not faked. All score ranges are 80% central intervals.

**Bundled deck.** Distribute cards and problems roughly proportional to
`weight_pct`, and ensure every finest unit clears the memory and performance
floors. The absolute deck size is the content owner's call. The proportions and
the floors are the blueprint's requirement. A nominal example (a 350-card and
140-problem bundle) sits in [`blueprint.json`](blueprint.json) under
`coverage_targets.nominal_example`.

---

## 5. Weight decision (resolved)

The public ETS current breakdown and the L1 table agree on 7 of 9 categories and
differ by one point on two. **Decision: keep L1.** No change to
`tag-and-attempt-log-schema.md` weights.

| Category       | L1 locked (in force) | ETS current public |
| -------------- | -------------------: | -----------------: |
| `quantum`      |                   13 |                 12 |
| `optics_waves` |                    8 |                  9 |
| all others     |            identical |          identical |

Both tables sum to 100. The one-question gap between quantum and optics is
accepted in favor of the values the seed checklist, the sourcing plan, and the
selector already use.

---

## 6. Locked decisions (v1)

Resolved 2026-07-03.

1. **Weights.** Keep L1 (quantum 13, optics_waves 8). See section 5.
2. **Finest-unit depth.** Split Specialized into three finest units (nuclear and
   particle, condensed matter, miscellaneous and astrophysics). No Mechanics
   fluids unit, no Lab electronics unit. Total is **25** finest units, so about
   25 seeds, inside the 20 to 30 target.
3. **Tag depth.** Keep L1 strict. Subtopic tags remain big-3 only. The six small
   categories carry the category tag only.
4. **Coverage gate.** Category level.

---

## 7. Alignment notes (for the other collaborators)

- The seed `CHECKLIST.md` provisional units map one-to-one onto the finest units
  here (same set, harmonized names). The `seed_file` column in the JSON is the
  bridge. When v1 locks, the checklist's `Blueprint ref` column can point at this
  file and its PROVISIONAL flags clear.
- The sourcing plan's category coverage table uses the same 9 slugs and the same
  L1 weights, so no change is needed there unless Frank moves the weights in
  section 5.
- Gold and held-out items must carry the same `topic::*` tags so their coverage
  and leakage can be checked against this blueprint.
