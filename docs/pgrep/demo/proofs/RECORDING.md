# pgrep L2 — recording script (Wednesday proofs)

These are the exact, verified steps to screen-record the Wednesday deliverables.
The agent already produced the reproducible artifacts and logs in this folder
(`clean-build.log`, `test-rust.log`, `test-py.log`, `wheels.log`,
`installer.log`, `installer-artifact.txt`, `commit.txt`). You record the video.

Repo worktree: `/Users/philote/projects/inka/.worktrees/l2-core` (branch `l2-core`).
Screen capture on macOS: Cmd+Shift+5. Use a large terminal font and clear the
scrollback so the output is legible.

## Proof A. Commit hash + clean build

```
cd /Users/philote/projects/inka/.worktrees/l2-core
git rev-parse HEAD                     # show the commit on screen
git log -1 --format='%H %s'
just clean
just run                               # compile from source until the app window opens
```

Record the terminal through the compile and the app window appearing. (The agent
captured the non-interactive form in `clean-build.log`, ending in
`Build succeeded` and `CLEANBUILD_EXIT=0`.)

## Proof B. The real Rust engine change + tests

```
git show --stat baca070a8              # the points-at-stake selector (L1.1) files
git diff 244bdfad7..baca070a8 -- rslib/src/scheduler/queue/builder/points_at_stake.rs
just test-rust                         # Rust suite incl. the selector tests
just test-py                           # Python suite incl. pgrep tests
```

Rust selector unit tests live in
`rslib/src/scheduler/queue/builder/points_at_stake.rs`; the end-to-end Python
test is `pylib/tests/test_pgrep_selector.py` (sets a deck's review order to
`REVIEW_CARD_ORDER_POINTS_AT_STAKE` and asserts worth-ordering). To show undo and
no corruption: in the app, review a card, Edit > Undo, reopen the collection.

## Proof C. Installer on a clean machine

The unsigned installer is at
`out/installer/dist/anki-26.05-mac-apple.dmg` (a preserved copy is at
`~/pgrep-l2-installer/anki-26.05-mac-apple.dmg`). To rebuild it:

```
just wheels
out/pyenv/bin/python qt/tools/build_installer.py --version 26.05 build \
  --aqt_wheel out/wheels/aqt-*.whl --anki_wheel out/wheels/anki-*.whl --skip_fcitx
out/pyenv/bin/python qt/tools/build_installer.py --version 26.05 package
```

On a fresh macOS VM or a new user account with no dev tools, copy the `.dmg`
over, open it, drag Anki to Applications, then right-click the app and choose
Open (it is ad-hoc signed, not notarized, so Gatekeeper asks once). Record it
launching and a card being reviewed.

## The no-AI core (desktop review loop + honest Memory)

With the app running (`just run`, or the installed app):

1. Tools menu > `pgrep: seed sample content` (creates topic-tagged PGRE cards and
   sample problems, and sets the points-at-stake review order).
2. Tools menu > `pgrep` to open the pgrep window.
3. Home shows the honest Memory score: a point, a likely range, a how-sure read,
   and per-topic breakdown that abstains where data is thin.
4. Study > Cards runs the real FSRS review loop (Again/Hard/Good/Easy).
5. Study > Problems shows commit-before-reveal and the static wrong-answer ladder.
6. Progress shows the coverage bar and the 70% Readiness gate line.
7. Diagnostic places each topic strong or rusty.

Everything runs with AI off (there is no AI in L2).

## Proof D. Phone runs the deck (smoke test from L0.3)

This reuses the L0.3 iOS Simulator engine smoke (the shared Rust engine loading
the sample deck). See the L0 dev harness recipes and
`mobile/sample-deck/collection.anki2`. No mobile UI work is part of L2.
