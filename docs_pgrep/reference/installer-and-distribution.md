# Installer and distribution

This page documents how to build, sign, and distribute pgrep on a clean device.
It covers the desktop Briefcase installer and the iOS distributable path. The
goal is a reproducible build a reviewer can run start to finish.

## Where the desktop app identity lives

The shipped desktop app is assembled by Briefcase. Its identity is defined in
`qt/installer/app/pyproject.toml`, driven by `qt/tools/build_installer.py`, and
rendered through the platform templates under `qt/installer/*-template/`.

| Key (`pyproject.toml`)    | Value                               | Effect                                                                                                                   |
| ------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `formal_name`             | `pgrep`                             | The display name. Becomes `pgrep.app` on macOS, `pgrep.exe` on Windows, and the OS-visible app name.                     |
| `bundle`                  | `net.ankiweb.pgrep`                 | Combined with the app slug it yields the App-ID `net.ankiweb.pgrep.anki`, matching the iOS `net.ankiweb.pgrep.*` family. |
| `project_name`            | `pgrep`                             | Umbrella project name in Briefcase metadata.                                                                             |
| `icon`                    | `resources/pgrep`                   | App icon. Briefcase appends the per-platform extension, so it uses `pgrep.icns` on macOS and `pgrep.png` on Linux.       |
| `icon` (windows override) | `resources/anki`                    | Temporary fallback. See caveats below.                                                                                   |
| `license`, `author`       | `AGPL-3.0-or-later`, `Damien Elmes` | Kept intact for license and attribution.                                                                                 |

The Briefcase app slug stays `anki`. The section header is still
`[tool.briefcase.app.anki]`, `sources` still points at `src/anki`, and the app
runs `python -m anki` through the bootstrap shim in
`qt/installer/app/src/anki/`. Keeping the slug means the Python import path, the
per-platform build directories (`out/installer/build/anki/...`), the Linux
binary and desktop file names, and the icon `cleanup_paths` all keep working.
Only the user-facing identity changed, not the packages.

Two matching values live in `qt/tools/build_installer.py`. The macOS
post-build path uses `pgrep.app` (it must equal `formal_name` plus `.app`), and
the packaged artifact is named `pgrep-<version>-<platform>`.

## Desktop build on a clean device

### Prerequisites

- Base tools: `git`, a recent system Python 3, a Rust toolchain, and a C
  toolchain. The ninja build bootstraps its own pinned Python and downloads the
  remaining build dependencies.
- macOS: Xcode command line tools.
- Linux: to bundle the fcitx5 input method, install the fcitx5 Qt6 plugin and
  `patchelf` first. On Debian and Ubuntu that is `fcitx5-frontend-qt6`,
  `libfcitx5-qt6-1`, and `patchelf`. Pass `--skip_fcitx` to skip this.
- Windows: no extra runtime tools for an unsigned build.

### Unsigned build

Run the wrapper for your platform from the repo root.

```bash
# macOS and Linux
./tools/build-installer
```

```bat
REM Windows
tools\build-installer.bat
```

Both set `RELEASE=2` and run `./ninja installer`. That builds the `anki` and
`aqt` wheels, then runs `build_installer.py build` followed by
`build_installer.py package`. The result lands in `out/installer/dist/` as
`pgrep-<version>-<platform>.<ext>` (`.dmg` on macOS, `.msi` on Windows,
`.tar.zst` on Linux).

### macOS sign and notarize

Signing and notarization run as part of `package` when a signing identity is
present. On a clean device:

1. Export the Apple credentials into the environment:

```bash
export APPLE_CERTIFICATE_P12=...        # base64 of the Developer ID .p12
export APPLE_CERTIFICATE_PASSWORD=...
export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export APPLE_TEAM_ID=TEAMID
export APPLE_NOTARY_KEY=...             # base64 of the App Store Connect .p8
export APPLE_NOTARY_KEY_ID=...
export APPLE_NOTARY_ISSUER_ID=...
export RUNNER_TEMP="$(mktemp -d)"
```

2. Prepare the keychain and the notarization profile:

```bash
.github/scripts/setup_apple_signing.sh
```

This imports the certificate into a temporary keychain and stores a `notarytool`
profile named `briefcase-macOS-$APPLE_TEAM_ID`, which is the exact name Briefcase
looks for.

3. Build with the identity set:

```bash
SIGN_IDENTITY="$APPLE_SIGNING_IDENTITY" ./tools/build-installer
```

`build_installer.py package()` passes `--identity` to Briefcase. Briefcase signs
`pgrep.app`, submits it for notarization using the stored profile, and staples
the ticket. Without `SIGN_IDENTITY` the app is ad-hoc signed, which is fine for
local testing but not for distribution. The signed, notarized `.dmg` is written
to `out/installer/dist/`.

### Windows sign

The Windows binary is `pgrep.exe` and the package is an `.msi`. Signing uses
Azure Trusted Signing in CI (`.github/workflows/release.yml`). The exe is signed
before packaging, then the msi is signed. See the caveat below about the exe
path.

### Linux

`./tools/build-installer` writes a `.tar.zst` to `out/installer/dist/`. Unpack
it and run the bundled `install.sh` to install per user or system wide. There is
no signing step. The desktop entry shows the name `pgrep`.

## iOS distributable

The iOS app is a separate SwiftUI target in `mobile/ios/` (`PgrepStudy`, bundle
`net.ankiweb.pgrep.PgrepStudy`). It is not built by Briefcase (`iOS` is
`supported = false` in the desktop config). It drives the shared Rust engine
through `AnkiFfi.xcframework` and is built with XcodeGen and `xcodebuild`.

### Prerequisites

- Xcode and its command line tools.
- `brew install xcodegen`.
- `rustup target add aarch64-apple-ios aarch64-apple-ios-sim`.
- For device installs and TestFlight: an Apple Developer team, the App ID
  `net.ankiweb.pgrep.PgrepStudy` registered in the portal, and a matching
  provisioning profile.

### Simulator, the fast check

| Command                | What it does                                  |
| ---------------------- | --------------------------------------------- |
| `just ios-xcframework` | Build only the Rust FFI xcframework.          |
| `just ios-run`         | Build the app and launch it in the Simulator. |
| `just ios-smoke`       | Headless XCTest over the review loop.         |

### Device sideload

1. Build the engine and generate the project:

```bash
just ios-xcframework
(cd mobile/ios && xcodegen generate)
```

2. Open `mobile/ios/PgrepStudy.xcodeproj` in Xcode, pick your team under Signing
   and Capabilities, select a connected device, then Run. Xcode installs a
   development-signed build.

3. Command line alternative:

```bash
xcodebuild -project mobile/ios/PgrepStudy.xcodeproj -scheme PgrepStudy \
  -destination 'generic/platform=iOS' -configuration Release \
  -archivePath out/ios/PgrepStudy.xcarchive archive

xcodebuild -exportArchive -archivePath out/ios/PgrepStudy.xcarchive \
  -exportPath out/ios/export -exportOptionsPlist ExportOptions.plist
```

Use an `ExportOptions.plist` with `method` set to `development` or `ad-hoc`, then
install the exported `.ipa` with `xcrun devicectl device install app`.

### TestFlight

1. Archive with the Release configuration and an App Store distribution profile,
   using the same `xcodebuild ... archive` command as above.
2. Export with `method` set to `app-store`, or upload straight from the Xcode
   Organizer.
3. Command line upload:

```bash
xcrun altool --upload-app -f out/ios/export/PgrepStudy.ipa -t ios \
  --apiKey "$APPLE_NOTARY_KEY_ID" --apiIssuer "$APPLE_NOTARY_ISSUER_ID"
```

The app record and the App ID `net.ankiweb.pgrep.PgrepStudy` must already exist
in App Store Connect. After processing, the build appears under TestFlight for
internal or external testers.

## Known caveats and follow-ups

- Windows exe path in CI. `.github/workflows/release.yml` still references
  `Anki.exe` in the sign and verify steps. After this rebrand the binary is
  `pgrep.exe`. That workflow is outside the installer scope and was not changed
  here, so the path must be updated before a signed Windows release will pass.
- Windows icon. The Windows section falls back to `resources/anki` because no
  `pgrep.ico` asset exists and the build host has no image converter. Produce a
  multi-size `pgrep.ico`, drop it in `qt/installer/app/resources/`, and switch
  the windows `icon` to `resources/pgrep`.
- Non-identity metadata. The `url` (apps.ankiweb.net), `long_description`, the
  document type descriptions, the Linux man page, the README, and the legacy
  `anki.xpm` icon still read Anki. These are descriptive text or attribution,
  not app identity, so they were left as is.
