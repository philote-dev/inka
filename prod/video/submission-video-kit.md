# pgrep submission video kit — record the real proofs

Practical, on-the-day shot lists for the graded recordings. This is the companion
to the concept walkthrough in this folder. Read the honest framing first.

## Honest framing (read once)

In short:

- **Wednesday is not a polished demo video.** It is **proof that a real build
  works**: a clean-build recording with a commit hash, test results, a
  clean-machine install recording, and a phone review-session recording.
- **The polished 3 to 5 minute demo video is the Sunday hand-in** (spec section
  12).
- **A prototype cannot produce Wednesday's proofs.** The concept walkthrough in
  this folder is a rehearsal aid, a pitch, and a backup. Do not submit it as a
  graded proof. Making up a measurement is an automatic fail.

So this kit has two parts. Part A is the Wednesday proof reel from the **real
forked build**. Part B is the Sunday polished video, which can reuse the concept
walkthrough's structure once the real surfaces exist.

---

## Part A. Wednesday proof reel (from the real build)

Record these four clips (spec section 6). Target 3 to 4 minutes total.
Everything must run **AI off**. (Stitch order is in the "Stitch the Wednesday
reel" section below.)

### Setup (do this first)

- Screen capture: `Cmd+Shift+5`, record selected region or full screen, include
  the mic if narrating.
- Terminal: large font, clear scrollback so build and test output is legible.
- Clean machine: a fresh macOS VM (UTM or Parallels) or a brand new user account
  with no dev toolchain, for an honest installer test.
- Have the commit hash on screen: `git rev-parse HEAD` and
  `git log -1 --format='%H %s'`.

### Proof A — clean build plus commit hash (W1)

| Step | Action                                                                |
| ---- | --------------------------------------------------------------------- |
| 1    | Show `git rev-parse HEAD` in the terminal.                            |
| 2    | `just clean` to wipe build outputs.                                   |
| 3    | `just run` and capture the full compile until the pgrep window opens. |

Narration: "Forked Anki, building from source. Commit abc123."

### Proof B — the Rust engine change plus tests (W2)

| Step | Action                                                                                                      |
| ---- | ----------------------------------------------------------------------------------------------------------- |
| 1    | `git show --stat` and open the changed `rslib` files to show the real diff.                                 |
| 2    | `just test-rust` so the 3 Rust unit tests pass (points-at-stake ordering, scoring, anti-blocking or limit). |
| 3    | `just test-py` so the 1 Python test that calls the change passes.                                           |
| 4    | In the app, show the change working: the review order reordering by topic weight times weakness.            |
| 5    | Show undo still works and the collection is intact (review, undo, reopen).                                  |

Narration: "A real engine change, the points-at-stake review order, with three
Rust tests and a Python test. Here it is reordering the queue by topic weight
times weakness."

### Proof C — clean-machine install (W5)

| Step | Action                                                                                                                                              |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Produce the installer. `just release build --ref <your-branch>` for the CI unsigned artifact, or build locally with Briefcase from `qt/installer/`. |
| 2    | On a fresh VM or a clean user account with no dev tools, run the installer.                                                                         |
| 3    | Record it installing, the app launching, and one card reviewed.                                                                                     |

Narration: "The installer on a clean machine, and a card reviewed."

Grading hard limit: if either app does not run on a clean device, 50 percent
maximum. This clip matters.

### Proof D — phone review session (W6, W7)

| Step | Action                                                                                                                                                                               |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1    | Build the shared engine for mobile (the `rslib/ffi` crate to an iOS static lib via a `build_xcframework` script, see `technical-architecture.md` (a)) and the minimal SwiftUI shell. |
| 2    | Launch on a real device or the iOS Simulator, load the same Physics GRE deck.                                                                                                        |
| 3    | Screen record a real review session. The engine schedules and grades on device. Sync is not required Wednesday.                                                                      |

Narration: "The same Rust engine running a review session on the phone."

iOS Simulator capture:

```bash
xcrun simctl io booted recordVideo --codec=h264 phone-review.mp4
# Ctrl-C to stop
```

### Stitch the Wednesday reel (optional)

Keep the four clips in the order A, B, C, D. Normalize and concatenate:

```bash
# normalize each clip to 1080p30, then concat (edit the file list to your clips)
for f in proofA proofB proofC proofD; do
  ffmpeg -i "$f.mov" -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x262624,fps=30,format=yuv420p" \
    -c:v libx264 -crf 18 -preset medium -c:a aac -b:a 160k "norm_$f.mp4" -y
done
printf "file 'norm_proofA.mp4'\nfile 'norm_proofB.mp4'\nfile 'norm_proofC.mp4'\nfile 'norm_proofD.mp4'\n" > wed_list.txt
ffmpeg -f concat -safe 0 -i wed_list.txt -c copy pgrep-wednesday-proof-reel.mp4 -y
```

Use `record.mjs`'s title-card technique (or a simple `drawtext` card) between
clips if you want a produced feel, but the graders reward plain and honest over
flashy.

---

## Part B. Sunday polished demo video (3 to 5 min)

Once the real surfaces exist, reuse the concept walkthrough's structure with the
**real app** and add the Friday and Sunday features. Suggested beats:

1. Cold open. One line. "One exam, two apps on one engine, three scores you can
   back up."
2. Home with all three real scores and ranges. Readiness now speaks because
   coverage is above the line.
3. Cards review loop on the real deck.
4. Problems door and the scaffold-fade tutor (the real ladder, AI on).
5. Forced generation. Author a seed, AI conforms siblings, each traced to a
   named source, gold-set gate, and it beats the keyword or vector baseline.
6. AI off. Show the app still gives a score.
7. Progress. Real memory calibration (Brier and log-loss on held-out reviews),
   performance accuracy on held-out questions, and the readiness mapping with a
   range.
8. Ablation. Full versus interleaving-off versus plain Anki, equal study time,
   the pre-stated metric, and what did not work.
9. Sync. Review on phone, then it shows up on desktop, and the documented
   conflict rule.
10. Close. The installer and the phone build, both running AI off.

Capture each beat from the real build the same way as Part A, then assemble with
the concat recipe above. The concept walkthrough in this folder is the visual and
pacing reference for this edit.

---

## Files in this folder

- `record.mjs` — records the concept walkthrough from the prototype.
- `assemble.sh` — turns the raw recording into the 1080p MP4.
- `narration.md` — caption and voiceover script for the concept video.
- `submission-video-kit.md` — this file.
- `raw/` — the raw Playwright recording (git-ignored by size, regenerate anytime).

_Sources: `../../docs_pgrep/plan/build-plan.md`,
`../../docs_pgrep/research/technical-architecture.md`, the project spec, and the `justfile`._
