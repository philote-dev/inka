# Demo & Submission Runbook — how to record the required proof

**Status: Wednesday fully mapped; Fri/Sun stubbed.** Shared context in `README.md`. This is the "how to record everything" guide. It maps each **spec deadline requirement** to the **exact proof artifact**, the **exact command**, and a **recording script**.

> **Read this first — an honest reframe.** Wednesday's submission is **not a polished demo video**. It is **proof that a real build works**: (1) a commit hash + clean-build recording, (2) test results, (3) a clean-machine install recording, (4) a phone review-session recording. The polished **3–5 minute demo video is a _Sunday_ hand-in** (spec §12). **A mock/prototype UI cannot produce Wednesday's proofs** — the graders want the forked engine compiling, real tests passing, a real installer, and the real engine running on a phone. The spec is explicit: *"Each deadline needs proof, not a promise,"* and *"Making up … a measurement … is an automatic fail."* So the prototype in `design/prod/` is for **rehearsal + as the L2 visual spec**, not the deliverable.

> **Current reality (2026-07-01):** nothing is built yet — the fork has not been compiled (`out/` toolchain absent = L0 not run). The path to a recordable Wednesday is to **execute the build** (L0 → L1 → L2 in `build-plan.md`). This runbook is the target; the build is the work.

---

## 0. Priority order (from the spec's closing section)

The spec ends with **"Get Anki Building First"**: *"The hardest part of day one is not your features. It is getting Anki to compile from source, making one tiny Rust change show up in the desktop app, and getting the same engine running on a phone. Do that before anything else."*

So the Wednesday order is: **desktop builds → tiny Rust change visible → phone runs the engine** — *then* the review loop, Memory score, and installer. That is exactly `build-plan.md` **L0 → L1 → L2**.

---

## 1. Wednesday — the seven deliverables and their proof

| # | Spec requirement (Wed) | Build layer | Exact command / action | Proof to record |
|---|---|---|---|---|
| W1 | Anki **forked + building from source** | L0.1 | `just run` (dev) or `just build` | Terminal recording of a **clean build**: `just clean` then `just run`, ending in the app window opening |
| W2 | **Rust change** end-to-end + **3 Rust tests + 1 Python test** | L1 | `just test-rust` and `just test-py`; show the diff `git show` | The **diff**, the **passing test output**, and the change **visible in the running app** (points-at-stake order) |
| W3 | **Review loop** on your exam deck | L2.1 | in the app: open the PGRE deck, review cards | Screen recording of a real review session (grade Again/Hard/Good/Easy, next card appears) |
| W4 | **Memory model** with an **honest score** (range + give-up rule) | L2.2 | in the app: Home shows Memory | Screen recording of the Memory score with its **range** + the **abstain** state on thin data |
| W5 | **Installer** that runs on a **clean machine** | L6-early | `just release build --ref <branch>` (CI builds unsigned artifacts) → download → install; or local Briefcase (`qt/installer/`) | Recording of the installer running on a **clean machine/VM** and the app launching |
| W6 | **Phone app builds + runs** on device/emulator | L0.3 | build the `rslib/ffi` static lib + minimal SwiftUI/Compose shell (`technical-architecture.md` (a)) | Recording of the phone app launching |
| W7 | Phone **loads the deck + real review** on the shared engine (no sync yet) | L0.3 / early L3.1 | on phone: open deck, review | **Screen recording of a review session on the phone** |

**Commit hash for the submission:** `git rev-parse HEAD` (and `git log -1 --format='%H %s'`).

---

## 2. The four required Wednesday proof recordings (spec §6 "Proof")

Record these four. Everything above rolls up into them.

### Proof A — clean-build recording (+ commit hash)
1. `git rev-parse HEAD` — show the hash on screen.
2. `just clean` (wipe build outputs).
3. `just run` — capture the full compile until the pgrep window opens.
4. macOS capture: **Cmd+Shift+5** → record the terminal + the window appearing.

### Proof B — test results (the Rust change)
1. `git show --stat` (and open the changed `rslib` files) to show the real Rust diff.
2. `just test-rust` → the **3 Rust unit tests** pass (points-at-stake ordering, scoring, anti-blocking/limit — see `anki-rooting-and-rust.md`).
3. `just test-py` → the **1 Python test** that calls the change passes.
4. Show undo still works + no corruption (spec 7a): review, undo, reopen — collection intact.

### Proof C — clean-machine install recording
1. Produce the installer: `just release build --ref <your-branch>` (CI, unsigned) → download the artifact; **or** build locally with Briefcase from `qt/installer/`.
2. On a **fresh VM / clean user account** (no dev tools), run the installer.
3. Record it installing and the app launching + a card reviewed. (Grading hard limit: *"Either app does not run on a clean device: 50% maximum."*)

### Proof D — phone review-session recording
1. Build the shared engine for mobile (the `rslib/ffi` crate → iOS static lib via a `build_xcframework` script; `technical-architecture.md` (a)) and the minimal SwiftUI shell.
2. Launch on a real device or the iOS Simulator; load the same PGRE deck.
3. **Screen-record a real review session** (the engine schedules + grades on-device). Sync is **not** required Wednesday.

---

## 3. Suggested Wednesday proof-reel order (~3–4 min, optional stitch)

Wednesday only requires the four clips above, but if you stitch one reel, use this order and narration:

1. **Commit + clean build** (Proof A). "Forked Anki, building from source. Commit `abc123`."
2. **The Rust change** (Proof B). "A real engine change — the points-at-stake review order — with 3 Rust tests and a Python test. Here it is reordering the queue by topic weight times weakness."
3. **Desktop review loop** (W3). "A real review session on the Physics GRE deck."
4. **Honest Memory score** (W4). "Memory shown honestly — a point, a likely range, and it abstains when data is thin. No performance or readiness yet; those are Friday and Sunday."
5. **Clean-machine install** (Proof C). "The installer on a clean VM."
6. **Phone review** (Proof D). "The same Rust engine running a review session on the phone."

Keep it honest and plain (the spec rewards this): *"One exam, two apps on one engine, a real engine change, and three scores you can back up beats a flashy app that promises everything."*

---

## 4. Recording tooling (macOS)

- **Screen capture:** Cmd+Shift+5 (record region/full screen; include mic for narration).
- **Terminal:** use a large font; clear scrollback so the build/test output is legible.
- **Clean machine:** a fresh macOS VM (UTM/Parallels) or a new user account with no dev toolchain, to honestly prove the installer.
- **Phone:** iOS Simulator screen-record (`xcrun simctl io booted recordVideo`) or QuickTime device capture for a real device.

---

## 5. Where the prototype fits (and where it doesn't)

`design/prod/pgrep-prototype.html` is a **self-contained, clickable prototype** of the L2 desktop surfaces (Home + honest Memory, the Cards review loop, Study launcher, Problems preview, Progress, Diagnostic), using the real design tokens (`ux-foundation.md`).

- ✅ **Use it to:** rehearse the demo narrative, validate the UX, and hand it to the L2 builder as the **interaction spec** (it mirrors the Svelte components in `claude-design-prompts.md` Part B/C).
- ❌ **Do not** submit it as the Wednesday deliverable — it has no engine, no FSRS, no tests, no installer. Wednesday's proofs (§2) must come from the **real forked build**.

Open it by double-clicking (no toolchain needed). It is dark by default; toggle light/dark and AI-off in the top bar.

---

## 6. Friday / Sunday (stubs — fill when we get there)

- **Friday (spec §6):** AI added + traced to a named source; a pre-release eval (accuracy + wrong-answer rate on a held-out gold set, with a cutoff); beats a keyword/vector baseline; app still scores AI-off. **Mobile two-way sync** + offline-then-sync; phone shows all three scores. Proof: eval numbers + a phone→desktop sync recording. (Build: L4 + L3.)
- **Sunday (spec §6, §12):** memory calibrated (Brier/log-loss + chart on held-out); performance accuracy on held-out questions; readiness mapping written down with a range; the **ablation** (full / interleaving-off / plain Anki); packaged desktop installer + phone build; documented sync conflict rule; both apps score AI-off. **Hand in:** the public AGPL fork + README (exam stated, build instructions, architecture, the Rust-change note + touched-files list), the **3–5 min demo video**, three one-page model descriptions (with give-up rules), and the Brainlift. (Build: L5 + L6.)

---

_Sources: the project spec (`docs_pgrep/spec/Speedrun_….pdf` §6 deadlines, §11 grading, §12 hand-in, "Get Anki Building First"); `build-plan.md` (layers + L2 controller prompt); `anki-rooting-and-rust.md` (the Rust change + tests); `technical-architecture.md` (a) (mobile FFI); the `justfile` + `release.just` (exact recipes)._
