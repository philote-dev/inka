# PGRE Blueprint Slug List (v1, locked)

**Status: locked (v1), 2026-07-03.** Generated from `blueprint.json`.
Full taxonomy and reasoning: `blueprint.md`.

This is the reconciliation list for the seed, sourcing, and eval
collaborators. Every finest unit, its category, its topic tag, and its
seed filename slug. Tag strings honor the strict L1 scheme (subtopics big-3
only; the six small categories carry the category tag only).

Counts: **9 categories, 20 distinct topic tags, 25 finest units (seeds).**

| # | Category | Finest unit | Topic tag | Seed file slug |
|---:|---|---|---|---|
| 1 | Classical Mechanics | Newtonian dynamics, work and energy | `topic::mechanics::dynamics_energy` | `mechanics-dynamics-energy` |
| 2 | Classical Mechanics | Oscillations | `topic::mechanics::oscillations` | `mechanics-oscillations` |
| 3 | Classical Mechanics | Rotation and rigid bodies | `topic::mechanics::rotation` | `mechanics-rotation` |
| 4 | Classical Mechanics | Central forces and orbits | `topic::mechanics::central_forces` | `mechanics-central-forces` |
| 5 | Classical Mechanics | Lagrangian and Hamiltonian formalism | `topic::mechanics::lagrangian_hamiltonian` | `mechanics-lagrangian-hamiltonian` |
| 6 | Electromagnetism | Electrostatics | `topic::electromagnetism::electrostatics` | `em-electrostatics` |
| 7 | Electromagnetism | Magnetostatics and the Lorentz force | `topic::electromagnetism::magnetostatics` | `em-magnetostatics` |
| 8 | Electromagnetism | Induction and Maxwell's equations | `topic::electromagnetism::induction_maxwell` | `em-induction-maxwell` |
| 9 | Electromagnetism | Electromagnetic waves | `topic::electromagnetism::em_waves` | `em-waves` |
| 10 | Electromagnetism | Circuits (DC and AC) | `topic::electromagnetism::circuits` | `em-circuits` |
| 11 | Quantum Mechanics | Formalism | `topic::quantum::formalism` | `quantum-formalism` |
| 12 | Quantum Mechanics | Schrodinger solutions | `topic::quantum::schrodinger_solutions` | `quantum-schrodinger-solutions` |
| 13 | Quantum Mechanics | Angular momentum and spin | `topic::quantum::angular_momentum_spin` | `quantum-angular-momentum-spin` |
| 14 | Quantum Mechanics | Perturbation theory and symmetry | `topic::quantum::perturbation_symmetry` | `quantum-perturbation-symmetry` |
| 15 | Thermodynamics and Statistical Mechanics | Laws and processes | `topic::thermodynamics` | `thermo-laws-processes` |
| 16 | Thermodynamics and Statistical Mechanics | Statistical mechanics and kinetic theory | `topic::thermodynamics` | `thermo-statmech-kinetic` |
| 17 | Atomic Physics | Atomic structure and spectra | `topic::atomic` | `atomic-structure-spectra` |
| 18 | Atomic Physics | Radiation and atoms in fields | `topic::atomic` | `atomic-radiation-fields` |
| 19 | Optics and Wave Phenomena | Wave phenomena | `topic::optics_waves` | `optics-wave-phenomena` |
| 20 | Optics and Wave Phenomena | Geometrical optics and polarization | `topic::optics_waves` | `optics-geometrical-polarization` |
| 21 | Special Relativity | Relativistic kinematics and dynamics | `topic::special_relativity` | `relativity-kinematics-dynamics` |
| 22 | Laboratory Methods | Data and error analysis | `topic::lab` | `lab-error-analysis` |
| 23 | Specialized Topics | Nuclear and particle physics | `topic::specialized` | `specialized-nuclear-particle` |
| 24 | Specialized Topics | Condensed matter | `topic::specialized` | `specialized-condensed-matter` |
| 25 | Specialized Topics | Miscellaneous and astrophysics | `topic::specialized` | `specialized-misc-astro` |

## The 20 distinct topic tags

- `topic::mechanics::dynamics_energy`
- `topic::mechanics::oscillations`
- `topic::mechanics::rotation`
- `topic::mechanics::central_forces`
- `topic::mechanics::lagrangian_hamiltonian`
- `topic::electromagnetism::electrostatics`
- `topic::electromagnetism::magnetostatics`
- `topic::electromagnetism::induction_maxwell`
- `topic::electromagnetism::em_waves`
- `topic::electromagnetism::circuits`
- `topic::quantum::formalism`
- `topic::quantum::schrodinger_solutions`
- `topic::quantum::angular_momentum_spin`
- `topic::quantum::perturbation_symmetry`
- `topic::thermodynamics`
- `topic::atomic`
- `topic::optics_waves`
- `topic::special_relativity`
- `topic::lab`
- `topic::specialized`

## Reconciliation notes

- Seed `CHECKLIST.md`: same 25 units. Add the new
  `specialized-misc-astro` row, then point `Blueprint ref` at `blueprint.md`
  and clear the PROVISIONAL flags.
- Sourcing plan: category slugs and weights unchanged, no edit needed.
- Gold and held-out items: tag with the `topic::*` values above so coverage
  and leakage check against this list.

