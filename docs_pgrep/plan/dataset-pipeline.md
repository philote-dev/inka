# Dataset pipeline (status board)

The tracked status board for every dataset the AI layer needs: role, source,
build status, location, and owner. Update the status column as builds land.

---

## Where docs live (the split)

- **Tracked plan and methodology** live here in `docs_pgrep/`. This board, the
  build plan, the eval methodology, and the decisions are tracked so they are
  part of the project record.
- **Private data and its manifests** live in `content/` (git-ignored). That
  folder holds copyrighted and held-out material plus the manifests that list
  those private files by path, so it cannot be committed. The manifests
  (`content/manifests/` and the `docs_pgrep/ai/` specs) stay next to the data they
  describe. This board is the tracked summary of them.

---

## Dataset status

| Dataset | Role | Source | Status | Location | Owner |
|---|---|---|---|---|---|
| Corpus (RAG) | generation grounding, named source | OpenStax Vol 1-3, Fitzpatrick x3 | done, 4450 chunks | `content/index/` | agent |
| Held-out ETS items | Performance held-out, never fed | GR0177, GR0877 (clean, app + held-out); GR8677, GR9277 (reserve) | done, 400 items | `content/tier3-private/items/` | agent |
| Brainscape examples | fed card-generation examples | 10 decks | done, 747 cards | `content/examples/brainscape/` | agent |
| CWRU examples | fed card-generation examples | Doc Brown set | done, 292 cards | `content/examples/cwru/` | agent |
| REA reference questions | all fed problem examples (both exams, no split) | REA prep book | done, 200 MCQs | `content/examples/reference-questions/` | agent |
| Community 70 | problem gold source (with the GR9677 gold) | forum RTF | done, 57 keyed, annotated + key-triangulated | `content/gold/candidates/community-70.json` | agent |
| GR9677 gold | problem gold source, real ETS vision-cleaned | GR9677 form | done, 61 promoted | `content/gold/candidates/gr9677-problem-gold.json` | agent |
| Fed problem examples | few-shot for problem gen | REA (all 200 MCQs, both exams) | done, 200 MCQs | `content/examples/reference-questions/` | agent |
| Problem gold set | ruler for problem generation | GR9677 (cleaned) + community 70 | done, 118 drafted + validated, Frank audit pending | `content/gold/problems/` | Frank + me |
| Card gold set (~50) | ruler for card generation | corpus (OpenStax, Fitzpatrick), not CWRU | done, 50 authored + validated, Frank audit pending | `content/gold/cards/` | Frank + me |
| Generated batch | AI vs baselines, blind scored | corpus + gpt-5.5 generator | done, 294 candidates (86 AI, 18 refused) | `content/run/candidates.json` | agent |
| Score report | the gate numbers | batch vs gold | pending, runs after gold is frozen | `content/run/score_report.json` | agent |
| Sealed readiness mock | final readiness validation | GR1777 | sealed | `content/tier3-private/sealed-mock/` | untouched |
| Readiness constants | raw-to-scaled mapping | GR1777 tables | done, extracted | `content/tier3-private/constants/` | agent |
| Memory calibration | FSRS Brier and reliability | anki-revlogs-10k slice | verify first | to be placed | eval agent |

## Firewall (unchanged)

The index reads `content/corpus/` only. Everything under `tier3-private/`,
`gold/`, and `heldout/` stays out of the index and out of every prompt. No ETS is
fed to generation: GR0177 and GR0877 are the clean forms played in the app and
anchor the held-out Performance bank, GR8677 and GR9277 are reserve held-out,
GR9677 is the problem gold (vision-cleaned real ETS, never fed), and GR1777 stays
sealed. Gold is never fed, so a real ETS form as the problem gold is fine. The fed
examples are a clean non-ETS pool (Brainscape and CWRU for cards, all of REA for
problems, no split). The ETS-dedup scan has run: 0 verbatim ETS reprints among the
670 non-ETS items.

## Frank's homework (the L4 gate)

The problem gold (118) and card gold (50) are drafted, machine-verified, and
validated. Community keys were triangulated across three independent solvers, and
the one genuinely contested key was adjudicated. What remains is a short human
audit, then the scored re-run.

- Skim a spot-check sample (the gpt-5.5-dissent problems plus a handful of random
  problems and cards) and confirm the drafting quality holds.
- On your OK, the gold is frozen to verified and the scored batch runs on it.

See `../ai/ai-layer.md` for the current state and the exact review steps. The
fed examples (Brainscape, CWRU, all of REA) are assembled. Everything else on this
board is agent-built and done.
