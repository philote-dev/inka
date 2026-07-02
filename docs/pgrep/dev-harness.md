# pgrep dev harness

pgrep is a Physics-GRE prep app forked from Anki. It reuses Anki's shared Rust
engine across two front-ends:

- **Desktop** — the existing Anki Python/Qt + TypeScript app (`pylib/`, `qt/`,
  `ts/`) on top of the core engine (`rslib/`).
- **iOS (Simulator)** — a native SwiftUI app (`mobile/ios/`) that drives the
  _same_ engine through a small C ABI (`rslib/ffi`), packaged for iOS as an
  `.xcframework`.

This page documents how to build, run, and test both targets with the `just`
recipes in the repo-root `justfile`. Run `just --list` to see everything.

## Desktop

| Command          | What it does                                                        |
| ---------------- | ------------------------------------------------------------------- |
| `just build`     | Build the desktop app (pylib + qt).                                 |
| `just run`       | Build and launch Anki in development mode.                          |
| `just test-rust` | Run the Rust test suite.                                            |
| `just test-py`   | Run the Python tests (pylib + qt).                                  |
| `just check`     | Format + full build + all lint/tests (run before finishing a task). |
| `just smoke`     | Fast desktop sanity check (see below).                              |

### `just smoke`

`smoke` is a quick, reliable pre-flight check — much faster than `just check`:

1. **Import smoke** — `SKIP_RUN=1 ./run` builds pylib + qt and imports `aqt`
   without opening the GUI, proving the libraries are importable (the same check
   CI runs under the name "Ensure libs importable").
2. **Rust tests** — `just test-rust`.

It deliberately skips the slow Playwright e2e suite. Use `just test-py` /
`just test-ts` / `just check` when you need broader coverage.

## iOS (Simulator)

The iOS app links `out/ios/AnkiFfi.xcframework`, a build artifact produced from
the `rslib/ffi` crate. The Xcode project is generated from
`mobile/ios/project.yml` by [XcodeGen] and is **gitignored** — `project.yml` is
the source of truth, so regenerate the `.xcodeproj` after cloning or whenever
the spec changes. On first launch the app loads the bundled sample deck at
`mobile/sample-deck/collection.anki2`.

### Prerequisites (one-time)

```
# Rust cross-compile targets (Simulator is required; device is best-effort)
rustup target add aarch64-apple-ios-sim aarch64-apple-ios

# Project generator + Swift protobuf codegen (protoc-gen-swift)
brew install xcodegen swift-protobuf
```

You also need Xcode and its command line tools (`xcodebuild`, `xcrun simctl`),
plus at least one iOS Simulator (any recent iPhone).

### Build & test

| Command                | What it does                                                          |
| ---------------------- | --------------------------------------------------------------------- |
| `just ios-xcframework` | Build `out/ios/AnkiFfi.xcframework` via `tools/build-xcframework.sh`. |
| `just ios-smoke`       | End-to-end iOS smoke (see below). macOS-only; takes a few minutes.    |

`just ios-smoke` delegates to `tools/ios-smoke.sh`, which:

1. builds the xcframework (`tools/build-xcframework.sh`),
2. regenerates the Xcode project (`xcodegen generate` in `mobile/ios/`),
3. auto-detects an available iOS Simulator (the first "iPhone" reported by
   `xcrun simctl list devices available`), and
4. runs the on-Simulator engine XCTest:
   `xcodebuild -project mobile/ios/PgrepStudy.xcodeproj -scheme PgrepStudy
   -destination "platform=iOS Simulator,name=<detected>" test`.

The XCTest (a host-less logic-test bundle) compiles the engine bridge and
generated protos and links the shared xcframework, so a green run proves the
same engine that powers desktop works on iOS.

To target a specific simulator, override the auto-detection:

```
IOS_SIM_NAME="iPhone 16 Pro" just ios-smoke
```

If `xcpretty` is installed it is used to prettify the `xcodebuild` output;
otherwise the raw log is shown. Either way the real test exit status is
preserved.

### Opening the app in Xcode

```
cd mobile/ios
xcodegen generate
open PgrepStudy.xcodeproj
```

Pick an iPhone simulator and Run. From the command line you can also boot a
simulator and inspect it with `xcrun simctl` (e.g.
`xcrun simctl list devices available`, `xcrun simctl boot "iPhone 17 Pro"`,
`open -a Simulator`).

### Regenerating Swift protobuf types

The Swift message types under `mobile/ios/PgrepStudy/Generated` are checked in.
Re-run `tools/gen-swift-protos.sh` after changing any `proto/anki/*.proto`.

## CI (follow-up)

A macOS GitHub Actions job could run `just ios-smoke` on every PR to guard the
iOS build + engine link (the desktop side is already covered by existing CI).
This is **not added yet** — it's pending an owner decision (macOS runner cost /
minutes), so no `.github/workflows/` changes have been made.

[XcodeGen]: https://github.com/yonaskolb/XcodeGen
