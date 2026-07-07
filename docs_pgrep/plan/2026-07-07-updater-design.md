# Updater, design (ship a DMG and push updates)

Date: 2026-07-07. Status: draft, one decision open. Author: pair session.

## Context

The desktop app is distributed as a signed, notarized DMG
(`docs_pgrep/reference/installer-and-distribution.md`). We want to push updates
without users hunting for a fresh installer. Mobile updates go through the app
stores, so this spec is the desktop story. User content and progress already flow
over sync; this is only about updating the app binary.

Two layers change independently. Content and data sync with no reinstall. The app
binary (engine plus bundled web UI) needs a new build, so this is where an updater
matters.

## How professionals do it

The standard for non-App-Store apps is Sparkle on macOS and WinSparkle on Windows.
The app ships a public EdDSA key and an appcast feed URL. You build, sign, and
notarize the DMG, then generate a signed `appcast.xml` (RSS of releases, each with
a download URL and an EdDSA signature over the archive bytes) hosted over HTTPS.
The app polls the feed, verifies the signature, and self-updates in the background,
with optional delta patches. This is exactly the "ship a DMG and send updates to
it" model.

## What we already have

The codebase inherits Anki's GitHub-release updater: `qt/aqt/update.py` and
`download_github_update_and_install` in `qt/aqt/package.py`. It checks GitHub
releases, prompts, downloads, and installs. The on-launch check that phoned Anki's
servers was disabled in the de-Anki work; the machinery remains.

## Approaches

- **A. Reuse and rebrand the GitHub-release updater (recommended v1).** Re-point
  it at our GitHub Releases, rebrand the strings, re-enable a launch check.
  Fastest, cross-platform, already most of the way there. UX is notify, download,
  install (not silent).
- **B. Sparkle plus WinSparkle (gold standard, v2).** Signed appcast, seamless
  background self-update, delta patches. Best UX, but real integration work to
  embed Sparkle's framework in the Briefcase and PyQt app plus an appcast
  pipeline.
- **C. Fully custom updater.** Our own feed, downloader, and installer. Full
  control, medium effort, reinvents Sparkle.

Recommendation: ship A now to get updates flowing, and plan B as the polished
self-update once signing and notarization are routine.

## Release pipeline (either approach)

Bump the version, build and sign and notarize the DMG, publish to GitHub Releases,
the app checks the feed, the user updates. For B, run `generate_appcast` after
notarization (order matters, or signatures go stale), host the appcast, and ship
the EdDSA public key in the app.

## Open decisions

- Which approach, A, B, or C.
- Hosting for releases and any appcast (GitHub Releases, or S3 plus CloudFront).
- Cross-platform timing (mac-first, Windows and Linux to follow).

## Constraints

Requires an Apple Developer identity for signing and notarization; there is no
trustworthy silent install without it. Do it in a worktree, finish `just check`
green.
